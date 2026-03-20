const { test, expect } = require("@playwright/test");
const { spawn } = require("node:child_process");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");

const repoRoot = path.resolve(__dirname, "..", "..");
const pythonBin = path.join(repoRoot, ".venv", "bin", "python");
const navKeys = ["overview", "jobs", "tasks", "worker-queue", "alerts", "health"];
const placeholderKeys = ["jobs", "tasks", "worker-queue", "alerts", "health"];

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

async function makeHome(prefix) {
  return fs.mkdtemp(path.join(os.tmpdir(), prefix));
}

async function seedOverviewHome(homeDir) {
  const jobDir = path.join(homeDir, "jobs", "job-seeded");
  const taskDir = path.join(jobDir, "tasks", "task-running");
  await fs.mkdir(taskDir, { recursive: true });
  await fs.writeFile(
    path.join(jobDir, "job.json"),
    JSON.stringify(
      {
        id: "job-seeded",
        title: "Seeded dashboard job",
        created_at: "2026-03-20T00:00:00Z",
        updated_at: "2026-03-20T00:05:00Z",
        status: "running",
      },
      null,
      2,
    ),
    "utf-8",
  );
  await fs.writeFile(
    path.join(taskDir, "task.json"),
    JSON.stringify(
      {
        id: "task-running",
        job_id: "job-seeded",
        title: "Seeded running task",
        status: "running",
        assigned_agent: "worker-1",
        created_at: "2026-03-20T00:00:00Z",
        updated_at: "2026-03-20T00:05:00Z",
        result: "Running verification",
      },
      null,
      2,
    ),
    "utf-8",
  );
}

test("dashboard redirects root to overview and renders seeded overview shell", async ({ page }) => {
  const homeDir = await makeHome("task-bridge-dashboard-happy-");
  await seedOverviewHome(homeDir);
  const server = await startDashboard(homeDir, 4173);

  try {
    const response = await page.goto(`${server.baseUrl}/`);
    expect(response).not.toBeNull();
    await expect(page).toHaveURL(`${server.baseUrl}/overview`);
    await expect(page.getByTestId("dashboard-shell")).toBeVisible();
    await expect(page.getByTestId("dashboard-primary-nav")).toBeVisible();
    for (const navKey of navKeys) {
      await expect(page.getByTestId(`dashboard-nav-${navKey}`)).toBeVisible();
    }
    await expect(page.getByTestId("dashboard-nav-overview")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("dashboard-overview-hero")).toBeVisible();
    await expect(page.getByTestId("dashboard-overview-task-status")).toBeVisible();
    await expect(page.getByTestId("dashboard-overview-worker-utilization")).toBeVisible();
    await expect(page.getByTestId("dashboard-overview-worker-list")).toBeVisible();
    await expect(page.getByTestId("dashboard-overview-recent-updates")).toBeVisible();
    await expect(page.getByTestId("dashboard-overview-empty-state")).toHaveCount(0);
    await expect(page.getByTestId("dashboard-overview-error-state")).toHaveCount(0);
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("dashboard overview empty state keeps read-only shell", async ({ page }) => {
  const homeDir = await makeHome("task-bridge-dashboard-empty-");
  const server = await startDashboard(homeDir, 4174);

  try {
    const response = await page.goto(`${server.baseUrl}/overview`);
    expect(response).not.toBeNull();
    expect(response.status()).toBe(200);
    await expect(page.getByTestId("dashboard-shell")).toBeVisible();
    await expect(page.getByTestId("dashboard-primary-nav")).toBeVisible();
    await expect(page.getByTestId("dashboard-nav-overview")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("dashboard-overview-empty-state")).toBeVisible();
    await expect(page.getByTestId("dashboard-overview-error-state")).toHaveCount(0);
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("dashboard overview unreadable store preserves shell and exposes error state", async ({ page }) => {
  const homeDir = await makeHome("task-bridge-dashboard-error-");
  const jobDir = path.join(homeDir, "jobs", "job-broken");
  await fs.mkdir(jobDir, { recursive: true });
  await fs.writeFile(path.join(jobDir, "job.json"), "{broken", "utf-8");
  const server = await startDashboard(homeDir, 4175);

  try {
    const response = await page.goto(`${server.baseUrl}/overview`);
    expect(response).not.toBeNull();
    expect(response.status()).toBe(500);
    await expect(page.getByTestId("dashboard-shell")).toBeVisible();
    await expect(page.getByTestId("dashboard-primary-nav")).toBeVisible();
    await expect(page.getByTestId("dashboard-nav-overview")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("dashboard-page-title")).toBeVisible();
    await expect(page.getByTestId("dashboard-overview-error-state")).toBeVisible();
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

for (const [index, pageKey] of placeholderKeys.entries()) {
  test(`dashboard placeholder route ${pageKey} keeps shell-only contract`, async ({ page }) => {
    const homeDir = await makeHome(`task-bridge-dashboard-${pageKey}-`);
    const server = await startDashboard(homeDir, 4180 + index);

    try {
      const response = await page.goto(`${server.baseUrl}/${pageKey}`);
      expect(response).not.toBeNull();
      expect(response.status()).toBe(200);
      await expect(page.getByTestId("dashboard-shell")).toBeVisible();
      await expect(page.getByTestId("dashboard-primary-nav")).toBeVisible();
      await expect(page.getByTestId("dashboard-boundary-note")).toBeVisible();
      await expect(page.getByTestId("dashboard-page-title")).toBeVisible();
      await expect(page.getByTestId(`dashboard-${pageKey}-shell`)).toBeVisible();
      await expect(page.getByTestId(`dashboard-nav-${pageKey}`)).toHaveAttribute("aria-current", "page");
      await expect(page.locator("form, button, input, textarea, select")).toHaveCount(0);
    } finally {
      await stopDashboard(server);
      await fs.rm(homeDir, { recursive: true, force: true });
    }
  });
}
