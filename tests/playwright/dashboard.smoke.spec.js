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
const liveBaseItems = navItems.filter((item) =>
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

async function expectNoHorizontalOverflow(page) {
  const metrics = await page.evaluate(() => ({
    viewport: window.innerWidth,
    root: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));

  expect(metrics.root).toBeLessThanOrEqual(metrics.viewport + 1);
  expect(metrics.body).toBeLessThanOrEqual(metrics.viewport + 1);
}

async function getTestIdWidth(page, testId) {
  return page.evaluate((value) => {
    const element = document.querySelector(`[data-testid="${value}"]`);
    if (!element) {
      return 0;
    }
    return element.getBoundingClientRect().width;
  }, testId);
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
  const taskA3 = runBridgeJson(homeDir, ["create-task", "--job", jobA.id, "--requirement", "triage backlog"]);

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
  const taskB1JsonPath = path.join(homeDir, "jobs", jobB.id, "tasks", `${taskB1.id}.json`);
  const taskB1Payload = JSON.parse(await fs.readFile(taskB1JsonPath, "utf-8"));
  taskB1Payload._scheduler.final_notified_at = "2026-03-19T09:00:00Z";
  taskB1Payload._scheduler.leader_followup_due_at = "2026-03-19T10:00:00Z";
  await fs.writeFile(taskB1JsonPath, `${JSON.stringify(taskB1Payload, null, 2)}\n`, "utf-8");

  const taskB2 = runBridgeJson(homeDir, [
    "create-task",
    "--job",
    jobB.id,
    "--requirement",
    "failed req",
    "--assign",
    "ops-agent",
  ]);
  runBridgeJson(homeDir, ["fail", taskB2.id, "--job", jobB.id, "--result", "worker crashed"]);
  const taskB2JsonPath = path.join(homeDir, "jobs", jobB.id, "tasks", `${taskB2.id}.json`);
  const taskB2Payload = JSON.parse(await fs.readFile(taskB2JsonPath, "utf-8"));
  taskB2Payload._scheduler.final_notified_at = "2026-03-20T08:00:00Z";
  await fs.writeFile(taskB2JsonPath, `${JSON.stringify(taskB2Payload, null, 2)}\n`, "utf-8");

  await fs.writeFile(
    path.join(homeDir, "daemon_state.json"),
    `${JSON.stringify(
      {
        worker_last_prompt_at: {
          "code-agent": "2026-03-20T09:15:00Z",
          "quality-agent": "2026-03-20T09:20:00Z",
          "review-agent": "2026-03-20T09:30:00Z",
        },
        leader_last_running_notice_at: "2026-03-20T11:45:00Z",
      },
      null,
      2,
    )}\n`,
    "utf-8",
  );

  return { jobA, taskA1, taskA2, taskA3, jobB, taskB1, taskB2 };
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
    await expect(page.getByTestId("dashboard-locale-switch")).toBeVisible();
    await expect(page.getByTestId("dashboard-page-chrome")).toBeVisible();
    await expect(page.getByTestId("dashboard-breadcrumbs")).toBeVisible();
    await expect(page.getByTestId("dashboard-locale-en")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("dashboard-locale-zh-cn")).toBeVisible();
    await expect(page.getByTestId("dashboard-boundary-note")).toContainText(
      "A single place to review the live picture across jobs, tasks, queues, alerts, and health.",
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

test("dashboard startup logs expose access guidance", async () => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-logs-"));
  const server = await startDashboard(homeDir, 4182);

  try {
    await expect.poll(() => server.getLogs()).toContain("Dashboard 启动中");
    await expect.poll(() => server.getLogs()).toContain("监听地址: 127.0.0.1");
    await expect.poll(() => server.getLogs()).toContain("监听端口: 4182");
    await expect.poll(() => server.getLogs()).toContain("本机访问: http://127.0.0.1:4182/overview");
    await expect.poll(() => server.getLogs()).toContain("SSH 端口转发: ssh -L 4182:127.0.0.1:4182 <remote-host>");
    await expect.poll(() => server.getLogs()).toContain("当前命令不会自动打开浏览器");
    await expect.poll(() => server.getLogs()).toContain("停止方式: Ctrl+C");
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

test("jobs and tasks render filtered read-only pages", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-live-slice-b-"));
  const seeded = await seedLiveDashboard(homeDir);
  const server = await startDashboard(homeDir, 4175);

  try {
    await page.goto(`${server.baseUrl}/jobs?view=active`);
    await expect(page.getByTestId("dashboard-nav-jobs")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("dashboard-jobs-page")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-filters")).toBeVisible();
    await expect(page.getByTestId("dashboard-page-chrome")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-view-active")).toHaveClass(/is-active/);
    await expect(page.getByTestId(`dashboard-jobs-list-card-${seeded.jobA.id}`)).toBeVisible();
    await expect(page.getByTestId(`dashboard-jobs-list-card-${seeded.jobB.id}`)).toHaveCount(0);
    await expect(page.getByTestId("dashboard-jobs-detail")).toHaveCount(0);

    await page.getByTestId(`dashboard-jobs-list-card-${seeded.jobA.id}`).click();
    await expect(page).toHaveURL(new RegExp(`/jobs\\?(?:job=${seeded.jobA.id}&view=active|view=active&job=${seeded.jobA.id})$`));
    await expect(page.getByTestId("dashboard-jobs-detail")).toContainText("Open latest task detail");
    await expect(page.getByText("Back to job cards")).toBeVisible();
    await expect(page.getByTestId("dashboard-boundary-note")).toContainText(
      "A single place to review the live picture across jobs, tasks, queues, alerts, and health.",
    );
    await expect(page.locator("main button, main form, main input, main select, main textarea")).toHaveCount(0);

    await page.goto(
      `${server.baseUrl}/tasks?job=${seeded.jobA.id}&state=running&agent=quality-agent`,
    );
    await expect(page.getByTestId("dashboard-nav-tasks")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("dashboard-tasks-page")).toBeVisible();
    await expect(page.getByTestId("dashboard-tasks-filters")).toBeVisible();
    await expect(page.getByTestId(`dashboard-tasks-list-card-${seeded.taskA2.id}`)).toBeVisible();
    await expect(page.getByTestId(`dashboard-tasks-list-card-${seeded.taskA1.id}`)).toHaveCount(0);
    await expect(page.getByTestId("dashboard-tasks-detail")).toHaveCount(0);

    await page.getByTestId(`dashboard-tasks-list-card-${seeded.taskA2.id}`).click();
    await expect(page).toHaveURL(new RegExp(`/tasks\\?(?=.*job=${seeded.jobA.id})(?=.*state=running)(?=.*agent=quality-agent)(?=.*task=${seeded.taskA2.id}).*$`));
    await expect(page.getByTestId("dashboard-tasks-detail")).toContainText("actively working");
    await expect(page.getByTestId("dashboard-tasks-detail")).toContainText("Preview ready");
    await expect(page.getByText("Back to filtered task cards")).toBeVisible();
    await expect(page.getByText("Back to job detail")).toBeVisible();
    await expect(page.getByTestId("dashboard-tasks-detail-preview")).toContainText("Runbook");
    await expect(page.getByTestId("dashboard-tasks-timeline")).toContainText("Last dispatch recorded");
    await expect(page.locator("main button, main form, main input, main select, main textarea")).toHaveCount(0);

    await page.goto(
      `${server.baseUrl}/tasks?job=${seeded.jobA.id}&state=queued&agent=code-agent&task=${seeded.taskA1.id}`,
    );
    await expect(page.getByTestId("dashboard-tasks-detail-preview-missing")).toContainText(
      "No detail.md file exists at the recorded path yet.",
    );
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("locale switch toggles tasks page between English and Simplified Chinese", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-locale-"));
  const seeded = await seedLiveDashboard(homeDir);
  const server = await startDashboard(homeDir, 4179);

  try {
    await page.goto(`${server.baseUrl}/tasks?job=${seeded.jobA.id}&task=${seeded.taskA2.id}`);
    await expect(page.getByTestId("dashboard-page-title")).toHaveText(
      "Task register with detail preview.",
    );
    await page.getByTestId("dashboard-locale-zh-cn").click();
    await expect(page).toHaveURL(
      `${server.baseUrl}/tasks?job=${seeded.jobA.id}&task=${seeded.taskA2.id}&lang=zh-CN`,
    );
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    await expect(page.getByTestId("dashboard-page-title")).toHaveText("任务总表与详情预览。");
    await expect(page.getByTestId("dashboard-tasks-detail")).toContainText("进行中");
    await expect(page.getByTestId("dashboard-boundary-note")).toContainText(
      "集中浏览现有存储中的作业、任务、队列、告警与健康信息。",
    );
    await expect(page.getByTestId("dashboard-locale-zh-cn")).toHaveAttribute("aria-current", "page");

    await page.getByTestId("dashboard-locale-en").click();
    await expect(page).toHaveURL(`${server.baseUrl}/tasks?job=${seeded.jobA.id}&task=${seeded.taskA2.id}`);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.getByTestId("dashboard-page-title")).toHaveText(
      "Task register with detail preview.",
    );
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

test("worker queue, alerts, and health render live read-only base pages", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-live-base-"));
  const seeded = await seedLiveDashboard(homeDir);
  const server = await startDashboard(homeDir, 4177);

  try {
    for (const item of liveBaseItems) {
      await page.goto(`${server.baseUrl}${item.route}`);
      await expect(page.getByTestId(`dashboard-nav-${item.key}`)).toHaveAttribute("aria-current", "page");
      await expect(page.getByTestId("dashboard-boundary-note")).toContainText(
        "A single place to review the live picture across jobs, tasks, queues, alerts, and health.",
      );
      await expect(page.locator("main button, main form, main input, main select, main textarea")).toHaveCount(0);
    }

    await page.goto(`${server.baseUrl}/worker-queue`);
    await expect(page.getByTestId("dashboard-worker-queue-hero")).toBeVisible();
    await expect(page.getByTestId("dashboard-worker-queue-summary")).toContainText("Current load and queue depth");
    await expect(page.getByTestId("dashboard-worker-queue-lanes")).toContainText("quality-agent");
    await expect(page.getByTestId("dashboard-worker-queue-unassigned")).toContainText(seeded.taskA3.id);

    await page.goto(`${server.baseUrl}/alerts`);
    await expect(page.getByTestId("dashboard-alerts-hero")).toBeVisible();
    await expect(page.getByTestId("dashboard-alerts-summary")).toContainText("What needs attention now");
    await expect(page.getByTestId("dashboard-alerts-risk-list")).toContainText(seeded.taskB2.id);
    await expect(page.getByTestId("dashboard-alerts-followups")).toContainText(seeded.taskB1.id);

    await page.goto(`${server.baseUrl}/health`);
    await expect(page.getByTestId("dashboard-health-hero")).toBeVisible();
    await expect(page.getByTestId("dashboard-health-summary")).toContainText("Key runtime facts");
    await expect(page.getByTestId("dashboard-health-checks")).toContainText("daemon_state.json");
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("worker queue, alerts, and health stay within the viewport on desktop widths", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-layout-"));
  await seedLiveDashboard(homeDir);
  const server = await startDashboard(homeDir, 4183);
  const viewports = [1440, 1280, 1100];

  try {
    for (const width of viewports) {
      await page.setViewportSize({ width, height: 960 });

      await page.goto(`${server.baseUrl}/worker-queue`);
      await expect(page.getByTestId("dashboard-worker-queue-lanes")).toBeVisible();
      await expectNoHorizontalOverflow(page);

      await page.goto(`${server.baseUrl}/alerts`);
      await expect(page.getByTestId("dashboard-alerts-risk-list")).toBeVisible();
      await expect(page.getByTestId("dashboard-alerts-followups")).toBeVisible();
      await expectNoHorizontalOverflow(page);
      const riskWidth = await getTestIdWidth(page, "dashboard-alerts-risk-list");
      const followupWidth = await getTestIdWidth(page, "dashboard-alerts-followups");
      expect(riskWidth).toBeGreaterThan(420);
      expect(followupWidth).toBeGreaterThan(340);

      await page.goto(`${server.baseUrl}/health`);
      await expect(page.getByTestId("dashboard-health-checks")).toBeVisible();
      await expectNoHorizontalOverflow(page);
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
