const { test, expect } = require("@playwright/test");
const { spawn } = require("node:child_process");
const fs = require("node:fs/promises");
const path = require("node:path");

const repoRoot = path.resolve(__dirname, "..", "..");
const pythonBin = path.join(repoRoot, ".venv", "bin", "python");

async function waitForServer(url) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const res = await fetch(url);
      if (res.ok || res.status === 500) return;
    } catch {
      // ignore
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`Dashboard server did not start in time: ${url}`);
}

async function startDashboard(homeDir, port) {
  const child = spawn(
    pythonBin,
    ["-m", "task_bridge", "dashboard", "--host", "127.0.0.1", "--port", String(port)],
    {
      cwd: repoRoot,
      env: {
        ...process.env,
        PYTHONPATH: path.join(repoRoot, "src"),
        TASK_BRIDGE_HOME: homeDir,
        HOME: homeDir,
        PYTHONUNBUFFERED: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  let logs = "";
  child.stdout.on("data", (c) => (logs += c.toString()));
  child.stderr.on("data", (c) => (logs += c.toString()));

  const baseUrl = `http://127.0.0.1:${port}`;
  await waitForServer(`${baseUrl}/overview`);
  return { child, baseUrl, getLogs: () => logs };
}

async function stopDashboard(server) {
  if (!server || server.child.killed) return;
  server.child.kill("SIGTERM");
  await new Promise((resolve) => {
    const timer = setTimeout(() => {
      server.child.kill("SIGKILL");
      resolve();
    }, 3000);
    server.child.once("exit", () => {
      clearTimeout(timer);
      resolve();
    });
  });
}

function sanitize(name) {
  return name.replace(/[^a-z0-9_-]+/gi, "-").replace(/-+/g, "-");
}

test.describe("dashboard UI snapshots for task-bridge job/task", () => {
  test("capture tasks job-scope and jobs dispatch timeline", async ({ page }) => {
    const homeDir = process.env.TASK_BRIDGE_HOME;
    const outDir = process.env.UI_SNAPSHOT_DIR;
    const phase = process.env.UI_SNAPSHOT_PHASE || "snapshot";
    const jobId = process.env.UI_SNAPSHOT_JOB_ID;
    const taskId = process.env.UI_SNAPSHOT_TASK_ID;

    if (!homeDir) throw new Error("TASK_BRIDGE_HOME is required");
    if (!outDir) throw new Error("UI_SNAPSHOT_DIR is required");
    if (!jobId) throw new Error("UI_SNAPSHOT_JOB_ID is required");

    await fs.mkdir(outDir, { recursive: true });

    const server = await startDashboard(homeDir, 4399);

    try {
      // TASKS page: Job scope panel
      await page.goto(`${server.baseUrl}/tasks`);
      await page.setViewportSize({ width: 1360, height: 900 });
      await page.waitForLoadState("networkidle");

      const jobScope = page.getByTestId("dashboard-tasks-filter-job");
      await expect(jobScope).toBeVisible();
      await jobScope.scrollIntoViewIfNeeded();
      await jobScope.screenshot({
        path: path.join(outDir, `${phase}-tasks-job-scope.png`),
      });

      // JOB detail: dispatch timeline
      const jobDetailUrl = `${server.baseUrl}/jobs?job=${jobId}`;

      await page.goto(jobDetailUrl);
      await page.waitForLoadState("networkidle");

      const timeline = page.getByTestId("dashboard-dispatch-timeline");
      await expect(timeline).toBeVisible();
      await timeline.scrollIntoViewIfNeeded();
      await timeline.screenshot({
        path: path.join(outDir, `${phase}-job-dispatch-timeline.png`),
      });
    } finally {
      await stopDashboard(server);
    }
  });
});
