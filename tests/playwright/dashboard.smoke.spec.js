const { test, expect } = require("@playwright/test");
const { spawn } = require("node:child_process");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");

const repoRoot = path.resolve(__dirname, "..", "..");
const pythonBin = path.join(repoRoot, ".venv", "bin", "python");
const navLabels = ["Overview", "Jobs", "Tasks", "Worker & Queue", "Alerts", "Health"];

async function startDashboard(homeDir, port) {
  const child = spawn(
    pythonBin,
    ["-m", "task_bridge", "dashboard", "--host", "127.0.0.1", "--port", String(port)],
    {
      cwd: repoRoot,
      env: {
        PATH: process.env.PATH,
        PYTHONPATH: "src",
        TASK_BRIDGE_HOME: homeDir,
        PYTHONUNBUFFERED: "1",
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );

  let logs = "";
  child.stdout.on("data", (chunk) => {
    logs += chunk.toString();
  });
  child.stderr.on("data", (chunk) => {
    logs += chunk.toString();
  });

  const baseUrl = `http://127.0.0.1:${port}`;
  await waitForServer(`${baseUrl}/overview`, () => logs);
  return { child, baseUrl, getLogs: () => logs };
}

async function stopDashboard(server) {
  if (!server || server.child.killed) {
    return;
  }

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

async function waitForServer(url, getLogs) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status === 500) {
        return;
      }
    } catch {
      // Keep polling until the server is listening.
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Dashboard server did not start in time.\n${getLogs()}`);
}

test("overview is reachable with nav, summary cards, and empty state", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-empty-"));
  const server = await startDashboard(homeDir, 4173);

  try {
    await page.goto(`${server.baseUrl}/`);
    await expect(page).toHaveURL(`${server.baseUrl}/overview`);
    await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
    for (const label of navLabels) {
      await expect(page.getByRole("link", { name: label })).toBeVisible();
    }
    await expect(page.getByRole("heading", { name: "Task Status Summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Worker Utilization Summary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recent Updates" })).toBeVisible();
    await expect(page.getByText("No jobs or tasks yet")).toBeVisible();
    await expect(page.getByText("Queued", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Running", { exact: true }).first()).toBeVisible();
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("overview renders an error state when store data is unreadable", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-error-"));
  const jobDir = path.join(homeDir, "jobs", "job-broken");
  await fs.mkdir(jobDir, { recursive: true });
  await fs.writeFile(path.join(jobDir, "job.json"), "{broken", "utf-8");

  const server = await startDashboard(homeDir, 4174);

  try {
    const response = await page.goto(`${server.baseUrl}/overview`);
    expect(response).not.toBeNull();
    expect(response.status()).toBe(500);
    await expect(page.getByRole("navigation", { name: "Primary" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Dashboard unavailable" })).toBeVisible();
    await expect(page.getByText("Store read failed")).toBeVisible();
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});
