const { test, expect } = require("@playwright/test");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");

const repoRoot = path.resolve(__dirname, "..", "..");
const pythonBin = path.join(repoRoot, ".venv", "bin", "python");
const navItems = [
  { key: "overview", label: "Overview", route: "/overview" },
  { key: "jobs", label: "Jobs", route: "/jobs" },
  { key: "tasks", label: "Tasks", route: "/tasks" },
  { key: "worker-queue", label: "Worker & Queue", route: "/worker-queue" },
  { key: "alerts", label: "Alerts", route: "/alerts" },
  { key: "health", label: "Health", route: "/health" },
];
const liveSliceBItems = navItems.filter((item) =>
  ["jobs", "tasks"].includes(item.key),
);
const placeholderItems = navItems.filter((item) =>
  ["worker-queue", "alerts", "health"].includes(item.key),
);

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

function bridgeEnv(homeDir) {
  return {
    ...process.env,
    PYTHONPATH: path.join(repoRoot, "src"),
    TASK_BRIDGE_HOME: homeDir,
    PYTHONUNBUFFERED: "1",
  };
}

function runBridgeJson(homeDir, args) {
  const completed = spawnSync(pythonBin, ["-m", "task_bridge", ...args], {
    cwd: repoRoot,
    env: bridgeEnv(homeDir),
    encoding: "utf-8",
  });
  if (completed.status !== 0) {
    throw new Error(`task_bridge ${args.join(" ")} failed.\n${completed.stderr}`);
  }
  return JSON.parse(completed.stdout);
}

async function seedLiveDashboard(homeDir) {
  const jobA = runBridgeJson(homeDir, ["create-job", "--title", "job-a"]);
  const taskA1 = runBridgeJson(homeDir, [
    "create-task",
    "--job",
    jobA.id,
    "--requirement",
    "queued req",
    "--assign",
    "code-agent",
  ]);
  const taskA2 = runBridgeJson(homeDir, [
    "create-task",
    "--job",
    jobA.id,
    "--requirement",
    "running req",
    "--assign",
    "quality-agent",
  ]);
  runBridgeJson(homeDir, ["start", taskA2.id, "--job", jobA.id, "--result", "actively working"]);
  await fs.writeFile(
    taskA2.detail_path,
    "# Runbook\n\n- capture logs\n- compare outputs\n",
    "utf-8",
  );
  const taskA2JsonPath = path.join(homeDir, "jobs", jobA.id, "tasks", `${taskA2.id}.json`);
  const taskA2Payload = JSON.parse(await fs.readFile(taskA2JsonPath, "utf-8"));
  taskA2Payload._scheduler.last_dispatch_at = taskA2Payload.updatedAt;
  await fs.writeFile(taskA2JsonPath, `${JSON.stringify(taskA2Payload, null, 2)}\n`, "utf-8");

  const jobB = runBridgeJson(homeDir, ["create-job", "--title", "job-b"]);
  const taskB1 = runBridgeJson(homeDir, [
    "create-task",
    "--job",
    jobB.id,
    "--requirement",
    "blocked req",
    "--assign",
    "review-agent",
  ]);
  runBridgeJson(homeDir, ["block", taskB1.id, "--job", jobB.id, "--result", "waiting on input"]);

  return { jobA, taskA1, taskA2, jobB, taskB1 };
}

test("overview renders the live happy path shell", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-happy-"));
  await seedLiveDashboard(homeDir);
  const server = await startDashboard(homeDir, 4173);

  try {
    await page.goto(`${server.baseUrl}/`);
    await expect(page).toHaveURL(`${server.baseUrl}/overview`);
    await expect(page.getByTestId("dashboard-shell")).toBeVisible();
    await expect(page.getByTestId("dashboard-primary-nav")).toBeVisible();
    await expect(page.getByTestId("dashboard-boundary-note")).toContainText(
      "Overview, Jobs, and Tasks are live. Worker & Queue, Alerts, and Health remain shell-ready and intentionally read-only.",
    );
    for (const item of navItems) {
      await expect(page.getByTestId(`dashboard-nav-${item.key}`)).toHaveText(item.label);
    }
    await expect(page.getByTestId("dashboard-nav-overview")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("dashboard-page-title")).toHaveText(
      "Live dispatch posture for the current task bridge.",
    );
    await expect(page.getByTestId("dashboard-overview-hero")).toBeVisible();
    await expect(page.getByTestId("dashboard-overview-task-status")).toContainText(
      "Task status summary",
    );
    await expect(page.getByTestId("dashboard-overview-worker-utilization")).toContainText(
      "Worker utilization summary",
    );
    await expect(page.getByTestId("dashboard-overview-worker-list")).toContainText("quality-agent");
    await expect(page.getByTestId("dashboard-overview-recent-updates")).toContainText("Recent updates");
    await expect(page.getByTestId("dashboard-overview-recent-updates")).toContainText("waiting on input");
    await expect(page.getByTestId("dashboard-overview-empty-state")).toHaveCount(0);
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("overview renders the explicit empty state", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-empty-"));
  const server = await startDashboard(homeDir, 4174);

  try {
    await page.goto(`${server.baseUrl}/overview`);
    await expect(page.getByTestId("dashboard-nav-overview")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("dashboard-overview-empty-state")).toContainText("No jobs or tasks yet");
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("jobs and tasks render live read-only pages", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-live-slice-b-"));
  const seeded = await seedLiveDashboard(homeDir);
  const server = await startDashboard(homeDir, 4175);

  try {
    await page.goto(`${server.baseUrl}/jobs?job=${seeded.jobA.id}`);
    await expect(page.getByTestId("dashboard-nav-jobs")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("dashboard-jobs-page")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-list")).toContainText("job-a");
    await expect(page.getByTestId("dashboard-jobs-detail")).toContainText("queued req");
    await expect(page.getByTestId("dashboard-boundary-note")).toContainText(
      "Overview, Jobs, and Tasks are live. Worker & Queue, Alerts, and Health remain shell-ready and intentionally read-only.",
    );
    await expect(page.locator("main button, main form, main input, main select, main textarea")).toHaveCount(0);

    await page.goto(`${server.baseUrl}/tasks?job=${seeded.jobA.id}&task=${seeded.taskA2.id}`);
    await expect(page.getByTestId("dashboard-nav-tasks")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("dashboard-tasks-page")).toBeVisible();
    await expect(page.getByTestId("dashboard-tasks-list")).toContainText(seeded.taskA2.id);
    await expect(page.getByTestId("dashboard-tasks-detail")).toContainText("actively working");
    await expect(page.getByTestId("dashboard-tasks-detail-preview")).toContainText("Runbook");
    await expect(page.getByTestId("dashboard-tasks-timeline")).toContainText("Last dispatch recorded");
    await expect(page.locator("main button, main form, main input, main select, main textarea")).toHaveCount(0);
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("jobs and tasks render explicit empty states", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-empty-live-slice-b-"));
  const server = await startDashboard(homeDir, 4176);

  try {
    await page.goto(`${server.baseUrl}/jobs`);
    await expect(page.getByTestId("dashboard-jobs-empty-state")).toContainText("No jobs yet");
    await page.goto(`${server.baseUrl}/tasks`);
    await expect(page.getByTestId("dashboard-tasks-empty-state")).toContainText("No tasks yet");
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("worker queue, alerts, and health remain shell-only placeholders", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-shell-slice-b-"));
  const server = await startDashboard(homeDir, 4177);

  try {
    for (const item of placeholderItems) {
      await page.goto(`${server.baseUrl}${item.route}`);
      await expect(page.getByTestId(`dashboard-${item.key}-shell`)).toBeVisible();
      await expect(page.getByTestId(`dashboard-nav-${item.key}`)).toHaveAttribute("aria-current", "page");
      await expect(page.getByTestId("dashboard-boundary-note")).toContainText(
        "Overview, Jobs, and Tasks are live. Worker & Queue, Alerts, and Health remain shell-ready and intentionally read-only.",
      );
      await expect(page.getByTestId("dashboard-page-title")).toContainText(item.label);
      await expect(page.locator("main button, main form, main input, main select, main textarea")).toHaveCount(0);
    }
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

  const server = await startDashboard(homeDir, 4178);

  try {
    const response = await page.goto(`${server.baseUrl}/overview`);
    expect(response).not.toBeNull();
    expect(response.status()).toBe(500);
    await expect(page.getByTestId("dashboard-primary-nav")).toBeVisible();
    await expect(page.getByTestId("dashboard-page-title")).toHaveText("Overview unavailable");
    await expect(page.getByTestId("dashboard-overview-error-state")).toContainText("Store read failed");
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});
