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
        HOME: homeDir,
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

async function expectLocatorContained(locator) {
  const metrics = await locator.evaluate((node) => {
    const rect = node.getBoundingClientRect();
    return {
      clientWidth: node.clientWidth,
      scrollWidth: node.scrollWidth,
      right: rect.right,
      viewport: window.innerWidth,
    };
  });

  // scrollWidth can be larger than clientWidth when descendants are clipped via overflow.
  // We assert on the visual box staying within the viewport.
  expect(metrics.right).toBeLessThanOrEqual(metrics.viewport + 1);
}

async function expectReadOnlyContent(page) {
  await expect(page.getByTestId("dashboard-page-chrome")).toBeVisible();
  await expect(page.getByTestId("dashboard-page-tools")).toBeVisible();
  const interactive = page
    .locator('main > :not([data-testid="dashboard-page-chrome"])')
    .locator(
      'form, select, textarea, button:not([data-readonly-control="timeline-scroll"]):not([data-font-option]):not([data-job-scope-toggle]):not([data-dispatch-scroll]), input:not([data-readonly-control])',
    );
  await expect(interactive).toHaveCount(0);
}

async function getFontSnapshot(page) {
  return page.evaluate(() => ({
    body: getComputedStyle(document.body).fontFamily,
    title: getComputedStyle(document.querySelector(".masthead h1")).fontFamily,
  }));
}

function bridgeEnv(homeDir) {
  return {
    ...process.env,
    PYTHONPATH: path.join(repoRoot, "src"),
    TASK_BRIDGE_HOME: homeDir,
    HOME: homeDir,
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

async function patchLastDispatchAt(homeDir, jobId, taskId, value) {
  const taskPath = path.join(homeDir, "jobs", jobId, "tasks", `${taskId}.json`);
  const payload = JSON.parse(await fs.readFile(taskPath, "utf-8"));
  payload._scheduler = payload._scheduler || {};
  payload._scheduler.last_dispatch_at = value;
  await fs.writeFile(taskPath, `${JSON.stringify(payload, null, 2)}\n`, "utf-8");
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
  taskB1Payload.createdAt = "2026-03-19T08:00:00Z";
  taskB1Payload.updatedAt = "2026-03-19T08:10:00Z";
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
  taskB2Payload.createdAt = "2026-03-20T07:00:00Z";
  taskB2Payload.updatedAt = "2026-03-20T07:10:00Z";
  taskB2Payload._scheduler.final_notified_at = "2026-03-20T08:00:00Z";
  taskB2Payload._scheduler.leader_followup_due_at = "2026-03-20T09:00:00Z";
  await fs.writeFile(taskB2JsonPath, `${JSON.stringify(taskB2Payload, null, 2)}\n`, "utf-8");

  const workPlanPath = path.join(
    homeDir,
    ".openclaw",
    "agents",
    "team-leader",
    "memory",
    "work-plan.md",
  );
  await fs.mkdir(path.dirname(workPlanPath), { recursive: true });
  await fs.writeFile(
    workPlanPath,
    "# Live work plan\n\n- clear blocked review path\n- queue the next follow-up\n",
    "utf-8",
  );

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

  return { jobA, taskA1, taskA2, taskA3, jobB, taskB1, taskB2, workPlanPath };
}

async function seedDenseDashboard(homeDir) {
  const job = runBridgeJson(homeDir, ["create-job", "--title", "dense bilingual register"]);
  const tasksByState = {
    running: [],
    blocked: [],
    failed: [],
    queued: [],
    done: [],
  };
  const stateCounts = {
    running: 6,
    blocked: 6,
    failed: 4,
    queued: 6,
    done: 4,
  };
  const followupDueAt = [
    "2026-03-19T08:00:00Z",
    "2026-03-19T09:00:00Z",
    "2026-03-19T10:00:00Z",
    "2026-03-19T11:00:00Z",
    "2026-03-19T12:00:00Z",
    "2026-03-21T08:00:00Z",
    "2026-03-21T09:00:00Z",
    "2026-03-21T10:00:00Z",
    "2026-03-21T11:00:00Z",
    "2026-03-21T12:00:00Z",
  ];
  let followupIndex = 0;

  for (const [state, count] of Object.entries(stateCounts)) {
    for (let index = 0; index < count; index += 1) {
      const requirement =
        `${state} bilingual task ${index} 中文 English coordination note ` +
        "to stress wrapping across denser dashboard cards.";
      const task = runBridgeJson(homeDir, [
        "create-task",
        "--job",
        job.id,
        "--requirement",
        requirement,
        "--assign",
        `${state}-agent-${index % 3}`,
      ]);
      const result =
        `${state} result ${index} 中文 English detail for scanability ` +
        "and overflow resilience under dense cards.";
      if (state === "running") {
        runBridgeJson(homeDir, ["start", task.id, "--job", job.id, "--result", result]);
      } else if (state === "blocked") {
        runBridgeJson(homeDir, ["block", task.id, "--job", job.id, "--result", result]);
      } else if (state === "failed") {
        runBridgeJson(homeDir, ["fail", task.id, "--job", job.id, "--result", result]);
      } else if (state === "done") {
        runBridgeJson(homeDir, ["complete", task.id, "--job", job.id, "--result", result]);
      }

      if (state === "blocked" || state === "failed") {
        const taskJsonPath = path.join(homeDir, "jobs", job.id, "tasks", `${task.id}.json`);
        const payload = JSON.parse(await fs.readFile(taskJsonPath, "utf-8"));
        payload._scheduler.final_notified_at = `2026-03-19T0${index % 9}:15:00Z`;
        payload._scheduler.leader_followup_due_at = followupDueAt[followupIndex];
        followupIndex += 1;
        await fs.writeFile(taskJsonPath, `${JSON.stringify(payload, null, 2)}\n`, "utf-8");
      }

      tasksByState[state].push(task);
    }
  }

  return { job, tasksByState };
}

async function seedJobsPaginationDashboard(homeDir) {
  const entries = [];
  const titles = [
    "Archive lane review: this long-lived job should stay readable on the last jobs page without pushing the pager off-canvas",
    `NO_BREAK_JOB_${"X".repeat(120)}`,
  ];

  for (let index = 0; index < 14; index += 1) {
    const job = runBridgeJson(homeDir, [
      "create-job",
      "--title",
      titles[index] || `paged-job-${String(index).padStart(2, "0")}`,
    ]);
    const task = runBridgeJson(homeDir, [
      "create-task",
      "--job",
      job.id,
      "--requirement",
      `job ${index} pagination smoke task`,
      "--assign",
      "code-agent",
    ]);
    if (index % 3 === 1) {
      runBridgeJson(homeDir, [
        "start",
        task.id,
        "--job",
        job.id,
        "--result",
        `running result ${index}`,
      ]);
    }
    entries.push({ job, task });
  }

  return {
    entries,
    lastPageEntry: entries[1],
  };
}

async function seedOverflowDashboard(homeDir) {
  const job = runBridgeJson(homeDir, ["create-job", "--title", "overflow containment review"]);
  const longAgent =
    "agent-with-an-extremely-long-routing-label-that-needs-to-wrap-inside-job-detail-cards-without-blowing-out-the-panel-width-1234567890";
  const longToken =
    "metadata-chain-without-natural-breakpoints-abcdefghijklmnopqrstuvwxyz-1234567890-abcdefghijklmnopqrstuvwxyz";
  const task = runBridgeJson(homeDir, [
    "create-task",
    "--job",
    job.id,
    "--requirement",
    `Need to inspect ${longToken} and confirm the dashboard keeps the card contained.`,
    "--assign",
    longAgent,
  ]);
  runBridgeJson(homeDir, [
    "start",
    task.id,
    "--job",
    job.id,
    "--result",
    `result ${longToken} ${longToken}`,
  ]);
  runBridgeJson(homeDir, [
    "update-result",
    task.id,
    "--job",
    job.id,
    "--result",
    "dispatch: overflow seed",
  ]);

  const taskJsonPath = path.join(homeDir, "jobs", job.id, "tasks", `${task.id}.json`);
  const payload = JSON.parse(await fs.readFile(taskJsonPath, "utf-8"));
  payload.assignedAgent = longAgent;
  payload.notifyTarget = `team-leader/${longToken}/${longToken}`;
  payload.detailPath = path.join(homeDir, "jobs", job.id, "details", `${longToken}-${longToken}.md`);
  await fs.mkdir(path.dirname(payload.detailPath), { recursive: true });
  await fs.writeFile(payload.detailPath, `# Overflow detail\n\n${longToken}\n`, "utf-8");
  await fs.writeFile(taskJsonPath, `${JSON.stringify(payload, null, 2)}\n`, "utf-8");

  return { job, task, longAgent };
}

async function seedAgentSupportDashboard(homeDir) {
  const job = runBridgeJson(homeDir, ["create-job", "--title", "agent support timeline regression"]);
  const events = [
    {
      key: "planning",
      requirement: "known worker timeline node",
      assign: "planning-agent",
      dispatchAt: "2026-03-19T08:15:00Z",
    },
    {
      key: "extension",
      requirement: "extension worker timeline node",
      assign: "unknown-agent",
      dispatchAt: "2026-03-19T09:15:00Z",
    },
    {
      key: "unassigned",
      requirement: "unassigned timeline node",
      dispatchAt: "2026-03-19T10:15:00Z",
    },
  ];
  const tasks = {};

  for (const event of events) {
    const args = ["create-task", "--job", job.id, "--requirement", event.requirement];
    if (event.assign) {
      args.push("--assign", event.assign);
    }
    const task = runBridgeJson(homeDir, args);
    tasks[event.key] = task;
    await patchLastDispatchAt(homeDir, job.id, task.id, event.dispatchAt);
  }

  return { job, tasks };
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
      "A single place to inspect the live picture across jobs, tasks, queues, alerts, and health.",
    );
    for (const item of navItems) {
      await expect(page.getByTestId(`dashboard-nav-${item.key}`)).toHaveText(item.label);
    }
    await expect(page.getByTestId("dashboard-nav-overview")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("dashboard-page-title")).toHaveText(
      "Live dispatch posture for the current task bridge",
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
    await expect(page.getByTestId("dashboard-overview-recent-updates")).toBeVisible();
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
    await expect.poll(() => server.getLogs()).toContain("本机打开: http://127.0.0.1:4182/overview");
    await expect.poll(() => server.getLogs()).toContain("远程访问: ssh -L 4182:127.0.0.1:4182 ");
    await expect.poll(() => server.getLogs()).toContain("当前会话看起来像远程或无 GUI 环境");
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
    await page.setViewportSize({ width: 1280, height: 960 });
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
    await expect(page).toHaveURL(
      new RegExp(`/jobs\\?(?:job=${seeded.jobA.id}&view=active|view=active&job=${seeded.jobA.id})#job-detail$`),
    );
    await expect(page.getByTestId("dashboard-jobs-detail")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-timeline")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-dispatch-timeline")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-timeline-scrollport")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-timeline-older")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-timeline-newer")).toBeVisible();
    await expect(page.getByText("Newest dispatches stay pinned on the live edge")).toBeVisible();
    await expect(page.getByText("Showing the latest dispatch slice first.")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-task-groups")).toBeVisible();
    const scrollMetrics = await page.getByTestId("dashboard-jobs-timeline-scrollport").evaluate((node) => ({
      left: node.scrollLeft,
      max: node.scrollWidth - node.clientWidth,
    }));
    expect(scrollMetrics.left).toBeGreaterThanOrEqual(0);
    expect(scrollMetrics.left).toBeGreaterThanOrEqual(Math.max(0, scrollMetrics.max - 40));
    const jobTimelineTop = await page.getByTestId("dashboard-jobs-timeline").evaluate((node) =>
      Math.round(node.getBoundingClientRect().top),
    );
    const jobTaskGroupsTop = await page.getByTestId("dashboard-jobs-task-groups").evaluate((node) =>
      Math.round(node.getBoundingClientRect().top),
    );
    expect(jobTimelineTop).toBeLessThan(jobTaskGroupsTop);
    await expect(page.getByText("Back to job cards")).toBeVisible();
    await expect(page.getByTestId("dashboard-boundary-note")).toContainText(
      "A single place to inspect the live picture across jobs, tasks, queues, alerts, and health.",
    );
    await expectReadOnlyContent(page);

    await page.getByTestId(`dashboard-jobs-task-card-${seeded.taskA2.id}`).click();
    await expect(page).toHaveURL(
      new RegExp(
        `/jobs\\?(?:job=${seeded.jobA.id}&task=${seeded.taskA2.id}&view=active|job=${seeded.jobA.id}&view=active&task=${seeded.taskA2.id}|view=active&job=${seeded.jobA.id}&task=${seeded.taskA2.id})#job-task-detail$`,
      ),
    );
    await expect(page.getByTestId("dashboard-jobs-task-detail")).toContainText("actively working");
    await expect(page.getByTestId("dashboard-jobs-task-detail-preview")).toContainText("Runbook");
    await expect(page.getByTestId("dashboard-jobs-task-timeline")).toContainText("Last dispatch recorded");
    await expect(page.getByTestId("dashboard-jobs-detail")).toHaveCount(0);
    await expect(page.getByTestId("dashboard-jobs-task-groups")).toHaveCount(0);
    await expect(page.getByText("Back to job detail")).toBeVisible();
    await expect(page.getByText("Open in Tasks")).toHaveCount(0);

    await page.getByText("Back to job detail").click();
    await expect(page).toHaveURL(new RegExp(`/jobs\\?(?:job=${seeded.jobA.id}&view=active|view=active&job=${seeded.jobA.id})#job-detail$`));
    await expect(page.getByTestId("dashboard-jobs-detail")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-task-groups")).toBeVisible();

    await page.goto(`${server.baseUrl}/jobs?job=${seeded.jobB.id}&detail_view=plan`);
    await expect(page.getByTestId("dashboard-jobs-detail-view-switch")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-detail-view-plan")).toHaveAttribute("aria-current", "page");
    await expect(page.getByTestId("dashboard-jobs-work-plan")).toContainText("Live work plan");
    await expect(page.getByTestId("dashboard-jobs-work-plan")).toContainText("clear blocked review path");
    await expect(page.getByTestId("dashboard-jobs-task-groups")).toHaveCount(0);
    await expectReadOnlyContent(page);

    await page.getByTestId("dashboard-jobs-detail-view-tasks").click();
    await expect(page).toHaveURL(new RegExp(`/jobs\\?job=${seeded.jobB.id}(?:#job-task-groups)?$`));
    await expect(page.getByTestId("dashboard-jobs-task-groups")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-work-plan")).toHaveCount(0);

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
    const taskTimelineTop = await page.getByTestId("dashboard-tasks-timeline").evaluate((node) =>
      Math.round(node.getBoundingClientRect().top),
    );
    const taskPreviewTop = await page.getByTestId("dashboard-tasks-detail-preview").evaluate((node) =>
      Math.round(node.getBoundingClientRect().top),
    );
    expect(taskTimelineTop).toBeLessThan(taskPreviewTop);
    await expectReadOnlyContent(page);

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

test("alerts cards navigate into canonical tasks detail routes", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-alert-links-"));
  const seeded = await seedLiveDashboard(homeDir);
  const server = await startDashboard(homeDir, 4186);

  try {
    await page.setViewportSize({ width: 1280, height: 960 });
    await page.goto(`${server.baseUrl}/alerts`);
    await expect(page.getByTestId("dashboard-alerts-risk-list")).toBeVisible();
    await expect(page.getByTestId(`dashboard-alerts-followup-task-${seeded.taskB2.id}`)).toBeVisible();
    await expect(page.getByTestId(`dashboard-alerts-followup-task-${seeded.taskB1.id}`)).toHaveCount(0);

    await page.getByTestId(`dashboard-alerts-risk-task-${seeded.taskB2.id}`).click();
    await expect(page).toHaveURL(
      `${server.baseUrl}/tasks?job=${seeded.jobB.id}&task=${seeded.taskB2.id}#tasks-detail`,
    );
    await expect(page.getByTestId("dashboard-tasks-detail")).toContainText("worker crashed");

    await page.goto(`${server.baseUrl}/alerts`);
    await page.getByTestId(`dashboard-alerts-followup-task-${seeded.taskB2.id}`).click();
    await expect(page).toHaveURL(
      `${server.baseUrl}/tasks?job=${seeded.jobB.id}&task=${seeded.taskB2.id}#tasks-detail`,
    );
    await expect(page.getByTestId("dashboard-tasks-detail")).toContainText("worker crashed");
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
      "Task register with detail preview",
    );
    await page.getByTestId("dashboard-locale-zh-cn").click();
    await expect(page).toHaveURL(
      `${server.baseUrl}/tasks?job=${seeded.jobA.id}&task=${seeded.taskA2.id}&lang=zh-CN`,
    );
    await expect(page.locator("html")).toHaveAttribute("lang", "zh-CN");
    await expect(page.getByTestId("dashboard-page-title")).toHaveText("Tasks 总表与详情预览");
    await expect(page.getByTestId("dashboard-tasks-detail")).toContainText("进行中");
    await expect(page.getByTestId("dashboard-boundary-note")).toContainText(
      "集中查看当前 store 里已有的 jobs、tasks、queue、告警和健康信息。",
    );
    await expect(page.getByTestId("dashboard-locale-zh-cn")).toHaveAttribute("aria-current", "page");

    await page.getByTestId("dashboard-locale-en").click();
    await expect(page).toHaveURL(`${server.baseUrl}/tasks?job=${seeded.jobA.id}&task=${seeded.taskA2.id}`);
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(page.getByTestId("dashboard-page-title")).toHaveText(
      "Task register with detail preview",
    );
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("jobs timeline keeps raw agent hooks stable across locale-safe fallbacks", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-agent-hooks-"));
  const seeded = await seedAgentSupportDashboard(homeDir);
  const server = await startDashboard(homeDir, 4187);

  try {
    await page.goto(`${server.baseUrl}/jobs?job=${seeded.job.id}&lang=zh-CN`);

    const planningNode = page.getByTestId(`dashboard-jobs-timeline-node-${seeded.tasks.planning.id}`);
    await expect(planningNode).toContainText("planning-agent");
    expect(await planningNode.getAttribute("data-agent")).toBe("planning-agent");
    expect(await planningNode.getAttribute("data-agent-fallback")).toBe("explicit-theme");

    const extensionNode = page.getByTestId(`dashboard-jobs-timeline-node-${seeded.tasks.extension.id}`);
    await expect(extensionNode).toContainText("unknown-agent");
    expect(await extensionNode.getAttribute("data-agent")).toBe("unknown-agent");
    expect(await extensionNode.getAttribute("data-agent-fallback")).toBe("default-theme");

    const unassignedNode = page.getByTestId(`dashboard-jobs-timeline-node-${seeded.tasks.unassigned.id}`);
    await expect(unassignedNode).toContainText("未分配");
    expect(await unassignedNode.getAttribute("data-agent")).toBeNull();
    expect(await unassignedNode.getAttribute("data-agent-fallback")).toBe("unassigned");

    await page.getByTestId("dashboard-locale-en").click();
    await expect(page.locator("html")).toHaveAttribute("lang", "en");
    await expect(unassignedNode).toContainText("Unassigned");
    expect(await unassignedNode.getAttribute("data-agent")).toBeNull();
    expect(await unassignedNode.getAttribute("data-agent-fallback")).toBe("unassigned");
    expect(await extensionNode.getAttribute("data-agent")).toBe("unknown-agent");
    expect(await extensionNode.getAttribute("data-agent-fallback")).toBe("default-theme");
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("font presets switch and persist without breaking dense bilingual layout", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-fonts-"));
  const seeded = await seedDenseDashboard(homeDir);
  const server = await startDashboard(homeDir, 4185);

  try {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${server.baseUrl}/tasks?job=${seeded.job.id}&lang=zh-CN`);

    await expect(page.getByTestId("dashboard-font-switch")).toBeVisible();
    await expect(page.locator('[data-testid="dashboard-page-chrome"] [data-testid="dashboard-font-switch"]')).toBeVisible();
    await expect(page.locator(".masthead [data-testid='dashboard-font-switch']")).toHaveCount(0);
    await expect(page.locator("html")).toHaveAttribute("data-font-preset", "sans");
    await expect(page.locator("body")).toHaveAttribute("data-font-preset", "sans");
    await expect(page.getByTestId("dashboard-font-sans")).toHaveAttribute("aria-pressed", "true");
    const defaultFonts = await getFontSnapshot(page);
    await expectNoHorizontalOverflow(page);

    await page.getByTestId("dashboard-font-editorial").click();
    await expect(page.locator("html")).toHaveAttribute("data-font-preset", "editorial");
    await expect(page.locator("body")).toHaveAttribute("data-font-preset", "editorial");
    await expect(page.getByTestId("dashboard-font-editorial")).toHaveAttribute("aria-pressed", "true");
    const editorialFonts = await getFontSnapshot(page);
    expect(editorialFonts.body).not.toBe(defaultFonts.body);
    await expectNoHorizontalOverflow(page);

    await page.getByTestId("dashboard-font-precision").click();
    await expect(page.locator("html")).toHaveAttribute("data-font-preset", "precision");
    await expect(page.locator("body")).toHaveAttribute("data-font-preset", "precision");
    const precisionFonts = await getFontSnapshot(page);
    expect(precisionFonts.body).not.toBe(editorialFonts.body);
    await expectNoHorizontalOverflow(page);

    await page.getByTestId("dashboard-font-mono").click();
    await expect(page.locator("html")).toHaveAttribute("data-font-preset", "mono");
    await expect(page.locator("body")).toHaveAttribute("data-font-preset", "mono");
    await expect(page.getByTestId("dashboard-font-mono")).toHaveAttribute("aria-pressed", "true");
    const monoFonts = await getFontSnapshot(page);
    expect(monoFonts.title).not.toBe(precisionFonts.title);
    expect(await page.evaluate(() => window.localStorage.getItem("task-bridge.dashboard.font"))).toBe("mono");
    await expectNoHorizontalOverflow(page);

    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-font-preset", "mono");
    await expect(page.locator("body")).toHaveAttribute("data-font-preset", "mono");
    await expect(page.getByTestId("dashboard-font-mono")).toHaveAttribute("aria-pressed", "true");
    await expectNoHorizontalOverflow(page);
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("job detail task cards keep long agent labels and metadata contained", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-overflow-"));
  const seeded = await seedOverflowDashboard(homeDir);
  const server = await startDashboard(homeDir, 4186);
  const cardSelector = `[data-testid="dashboard-jobs-task-card-${seeded.task.id}"]`;

  try {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${server.baseUrl}/jobs?job=${seeded.job.id}`);

    await expect(page.locator(cardSelector)).toBeVisible();
    await expect(page.locator(cardSelector)).toContainText("agent-with-an-extremely-long-routing-label");
    await expectNoHorizontalOverflow(page);
    await expectLocatorContained(page.locator(cardSelector));
    await expectLocatorContained(page.locator(`${cardSelector} .task-preview-meta`));

    await page.locator(cardSelector).click();
    await expect(page.getByTestId("dashboard-jobs-task-detail")).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await expectLocatorContained(
      page.locator('[data-testid="dashboard-jobs-task-detail"] .detail-stack > .detail-card:first-child'),
    );
    await expectLocatorContained(
      page.locator(
        '[data-testid="dashboard-jobs-task-detail"] .detail-stack > .detail-card:first-child .meta-grid',
      ),
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
        "A single place to inspect the live picture across jobs, tasks, queues, alerts, and health.",
      );
      await expectReadOnlyContent(page);
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
    await expect(page.getByTestId("dashboard-alerts-followups")).toContainText(seeded.taskB2.id);
    await expect(page.getByTestId(`dashboard-alerts-followup-task-${seeded.taskB1.id}`)).toHaveCount(0);

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

test("dense tasks and alerts keep pagination, anchors, and priority visibility stable", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-dense-"));
  const seeded = await seedDenseDashboard(homeDir);
  const server = await startDashboard(homeDir, 4184);

  try {
    await page.setViewportSize({ width: 1280, height: 960 });

    await page.goto(`${server.baseUrl}/tasks?job=${seeded.job.id}`);
    await expect(page.getByTestId("dashboard-tasks-status-ribbon")).toBeVisible();
    await expect(page.getByTestId("dashboard-tasks-pagination")).toBeVisible();
    await expect(page.getByTestId("dashboard-tasks-pagination-page-2")).toBeVisible();
    await expectNoHorizontalOverflow(page);

    const firstTaskGroups = await page.locator('[data-testid^="dashboard-tasks-group-"]').evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("data-testid")),
    );
    expect(firstTaskGroups).toEqual([
      "dashboard-tasks-group-running",
      "dashboard-tasks-group-blocked",
    ]);

    await page.getByTestId("dashboard-tasks-pagination-page-2").click();
    await expect(page).toHaveURL(new RegExp(`/tasks\\?(?=.*job=${seeded.job.id})(?=.*page=2).*#tasks-registry$`));
    const tasksRegistryTop = await page.locator("#tasks-registry").evaluate((node) =>
      Math.round(node.getBoundingClientRect().top),
    );
    expect(tasksRegistryTop).toBeLessThan(180);
    await expectNoHorizontalOverflow(page);

    const secondTaskGroups = await page.locator('[data-testid^="dashboard-tasks-group-"]').evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("data-testid")),
    );
    expect(secondTaskGroups).toEqual([
      "dashboard-tasks-group-failed",
      "dashboard-tasks-group-queued",
      "dashboard-tasks-group-done",
    ]);

    await page.getByTestId(`dashboard-tasks-list-card-${seeded.tasksByState.failed[0].id}`).click();
    await expect(page).toHaveURL(
      new RegExp(
        `/tasks\\?(?=.*job=${seeded.job.id})(?=.*page=2)(?=.*task=${seeded.tasksByState.failed[0].id}).*#tasks-detail$`,
      ),
    );
    await expect(page.locator("a.inline-back-link")).toHaveAttribute(
      "href",
      `/tasks?job=${seeded.job.id}&page=2#tasks-registry`,
    );

    await page.setViewportSize({ width: 390, height: 844 });
    await expectNoHorizontalOverflow(page);

    await page.goto(`${server.baseUrl}/alerts`);
    await expect(page.getByTestId("dashboard-alerts-risk-group-blocked")).toBeVisible();
    await expect(page.getByTestId("dashboard-alerts-risk-group-failed")).toBeVisible();
    await expect(page.getByTestId("dashboard-alerts-risk-pagination-page-2")).toBeVisible();
    await expect(page.getByTestId("dashboard-alerts-followups")).toContainText("No unresolved follow-ups");
    await expect(page.getByTestId("dashboard-alerts-followup-pagination")).toHaveCount(0);
    await expectNoHorizontalOverflow(page);

    await page.getByTestId("dashboard-alerts-risk-pagination-page-2").click();
    await expect(page).toHaveURL(new RegExp("/alerts\\?(?=.*risk_page=2).*#alerts-risk-list$"));
    const riskTop = await page.locator("#alerts-risk-list").evaluate((node) =>
      Math.round(node.getBoundingClientRect().top),
    );
    expect(riskTop).toBeLessThan(180);
    await expect(page.getByTestId("dashboard-alerts-risk-group-failed")).toBeVisible();

    await expect(page.getByTestId("dashboard-alerts-followups")).toContainText("No unresolved follow-ups");
    await expect(page.getByTestId("dashboard-alerts-followup-pagination")).toHaveCount(0);
    await expectNoHorizontalOverflow(page);
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});

test("jobs pagination keeps anchors, selection, and narrow-width containment stable", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-jobs-pagination-"));
  const seeded = await seedJobsPaginationDashboard(homeDir);
  const server = await startDashboard(homeDir, 4186);

  try {
    await page.setViewportSize({ width: 1280, height: 960 });

    await page.goto(`${server.baseUrl}/jobs`);
    await expect(page.getByTestId("dashboard-jobs-pagination")).toBeVisible();
    await expect(page.getByTestId("dashboard-jobs-pagination-page-2")).toBeVisible();
    await expectNoHorizontalOverflow(page);

    const paginationPlacement = await page.evaluate(() => {
      const list = document.querySelector('[data-testid="dashboard-jobs-list"]');
      const pagination = document.querySelector('[data-testid="dashboard-jobs-pagination"]');
      const cards = Array.from(document.querySelectorAll('[data-testid^="dashboard-jobs-list-card-"]'));
      if (!list || !pagination || cards.length === 0) {
        return null;
      }
      const listRect = list.getBoundingClientRect();
      const paginationRect = pagination.getBoundingClientRect();
      const lastCardBottom = Math.max(...cards.map((node) => node.getBoundingClientRect().bottom));
      return {
        listBottom: Math.round(listRect.bottom),
        paginationTop: Math.round(paginationRect.top),
        paginationBottom: Math.round(paginationRect.bottom),
        lastCardBottom: Math.round(lastCardBottom),
      };
    });

    expect(paginationPlacement).not.toBeNull();
    expect(paginationPlacement.paginationTop).toBeGreaterThanOrEqual(
      paginationPlacement.lastCardBottom - 1,
    );
    expect(paginationPlacement.paginationBottom).toBeLessThanOrEqual(
      paginationPlacement.listBottom + 1,
    );

    await page.getByTestId("dashboard-jobs-pagination-page-2").click();
    await expect(page).toHaveURL(new RegExp("/jobs\\?(?=.*page=2).*#jobs-registry$"));
    await expect
      .poll(async () => page.evaluate(() => Math.round(window.scrollY)))
      .toBeGreaterThan(600);
    await expect
      .poll(async () =>
        page.locator("#jobs-registry").evaluate((node) => {
          const rect = node.getBoundingClientRect();
          return {
            top: Math.round(rect.top),
            bottom: Math.round(rect.bottom),
            viewport: window.innerHeight,
          };
        }),
      )
      .toMatchObject({
        bottom: expect.any(Number),
        top: expect.any(Number),
        viewport: expect.any(Number),
      });
    const jobsRegistryMetrics = await page.locator("#jobs-registry").evaluate((node) => {
      const rect = node.getBoundingClientRect();
      return {
        top: Math.round(rect.top),
        bottom: Math.round(rect.bottom),
        viewport: window.innerHeight,
      };
    });
    expect(jobsRegistryMetrics.top).toBeLessThan(jobsRegistryMetrics.viewport - 80);
    expect(jobsRegistryMetrics.bottom).toBeGreaterThan(120);
    await expect(
      page.getByTestId("dashboard-jobs-pagination").getByRole("link", { name: "Next" }),
    ).toHaveCount(0);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(page.getByTestId("dashboard-jobs-pagination")).toBeVisible();
    await expectNoHorizontalOverflow(page);
    await page.setViewportSize({ width: 1280, height: 960 });

    await page.getByTestId(`dashboard-jobs-list-card-${seeded.lastPageEntry.job.id}`).click();
    await expect(page).toHaveURL(
      new RegExp(`/jobs\\?(?=.*job=${seeded.lastPageEntry.job.id})(?=.*page=2).*#job-detail$`),
    );
    await expect(page.locator("a.inline-back-link")).toHaveAttribute(
      "href",
      `/jobs?page=2#jobs-registry`,
    );

    await page.getByTestId(`dashboard-jobs-task-card-${seeded.lastPageEntry.task.id}`).click();
    await expect(page).toHaveURL(
      new RegExp(
        `/jobs\\?(?=.*job=${seeded.lastPageEntry.job.id})(?=.*task=${seeded.lastPageEntry.task.id})(?=.*page=2).*#job-task-detail$`,
      ),
    );
    await expect(page.locator("a.inline-back-link")).toHaveAttribute(
      "href",
      `/jobs?job=${seeded.lastPageEntry.job.id}&page=2#job-detail`,
    );
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
