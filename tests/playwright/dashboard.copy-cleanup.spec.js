const { test, expect } = require("@playwright/test");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs/promises");
const path = require("node:path");
const os = require("node:os");

const repoRoot = path.resolve(__dirname, "..", "..");
const pythonBin = path.join(repoRoot, ".venv", "bin", "python");

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

async function waitForServer(url, getLogs) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(url);
      if (response.ok || response.status === 500) return;
    } catch {
      // ignore until ready
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`Dashboard server did not start in time.\n${getLogs()}`);
}

async function startDashboard(homeDir, port) {
  const child = spawn(
    pythonBin,
    ["-m", "task_bridge", "dashboard", "--host", "127.0.0.1", "--port", String(port)],
    {
      cwd: repoRoot,
      env: bridgeEnv(homeDir),
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

async function seedDashboard(homeDir) {
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
  await fs.writeFile(taskA2.detail_path, "# Runbook\n\n- capture logs\n- compare outputs\n", "utf-8");
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

  const workPlanPath = path.join(homeDir, ".openclaw", "agents", "team-leader", "memory", "work-plan.md");
  await fs.mkdir(path.dirname(workPlanPath), { recursive: true });
  await fs.writeFile(workPlanPath, "# Live work plan\n\n- clear blocked review path\n- queue the next follow-up\n", "utf-8");

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

const forbiddenVisible = [
  "把 failed 固定放在最前面，首屏先看到最硬的故障，再处理后续协同阻塞。",
  "把 blocked 放在第二条独立流里，既保留依赖阻塞的可见性，也不再淹没 failed。",
  "Review failures first so the most serious issues are visible immediately.",
  "Blocked work appears separately so dependency issues stay visible without crowding out failures.",
  "先查看失败任务，让最严重的问题一眼可见。",
  "阻塞任务会单独展示，方便继续追踪依赖问题，也不会盖住失败项。",
  "Failures stay pinned first",
  "Blocked work stays in a second lane",
  "current job pointer",
  "job.json",
  "detail.md",
  "_scheduler",
  "event model",
  "polling layer",
  "existing store",
];

async function collectVisibleText(page) {
  return page.locator("body").evaluate((node) => {
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    const chunks = [];
    while (walker.nextNode()) {
      const current = walker.currentNode;
      const text = (current.textContent || "").replace(/\s+/g, " ").trim();
      if (!text) continue;
      const parent = current.parentElement;
      if (!parent) continue;
      const style = window.getComputedStyle(parent);
      if (parent.hidden || style.display === "none" || style.visibility === "hidden") continue;
      chunks.push(text);
    }
    return chunks.join("\n");
  });
}

test("dashboard copy cleanup keeps internal-facing copy out of user-visible pages", async ({ page }) => {
  const homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-dashboard-copy-cleanup-"));
  const seeded = await seedDashboard(homeDir);
  const server = await startDashboard(homeDir, 4191);
  const findings = [];

  try {
    await page.setViewportSize({ width: 1440, height: 1100 });

    const pages = [
      {
        locale: "en",
        url: `${server.baseUrl}/overview`,
        testId: "dashboard-overview-hero",
        required: ["Use one view to keep up with work, blockers, and system health.", "Current work at a glance"],
      },
      {
        locale: "en",
        url: `${server.baseUrl}/jobs?job=${seeded.jobB.id}&detail_view=plan`,
        testId: "dashboard-jobs-page",
        required: ["Browse jobs and drill into their tasks without leaving the page.", "Live work plan"],
      },
      {
        locale: "en",
        url: `${server.baseUrl}/tasks?job=${seeded.jobA.id}&task=${seeded.taskA2.id}`,
        testId: "dashboard-tasks-page",
        required: ["Browse tasks, open their saved details, and review the recorded timeline.", "Runbook", "Task filters"],
      },
      {
        locale: "en",
        url: `${server.baseUrl}/worker-queue`,
        testId: "dashboard-worker-queue-hero",
        required: ["See who is busy, what each agent will pick up next, and which queued tasks still need an owner.", "Current load and waiting work"],
      },
      {
        locale: "en",
        url: `${server.baseUrl}/alerts`,
        testId: "dashboard-alerts-hero",
        required: ["Review blocked or failed tasks and any follow-up reminders still waiting on the current job.", "What needs attention now"],
      },
      {
        locale: "en",
        url: `${server.baseUrl}/health`,
        testId: "dashboard-health-hero",
        required: ["Check whether the dashboard can read the latest task data and background status.", "Key health signals"],
      },
      {
        locale: "zh-CN",
        url: `${server.baseUrl}/overview?lang=zh-CN`,
        testId: "dashboard-overview-hero",
        required: ["用一个视图查看任务进度、待处理事项和系统健康。", "当前工作一览"],
      },
      {
        locale: "zh-CN",
        url: `${server.baseUrl}/jobs?job=${seeded.jobB.id}&detail_view=plan&lang=zh-CN`,
        testId: "dashboard-jobs-page",
        required: ["浏览 job，并在同页继续打开它们的 task。创建或调整 job 仍在 CLI 中完成。", "Live work plan"],
      },
      {
        locale: "zh-CN",
        url: `${server.baseUrl}/tasks?job=${seeded.jobA.id}&task=${seeded.taskA2.id}&lang=zh-CN`,
        testId: "dashboard-tasks-page",
        required: ["浏览 task，查看已保存的详情，并按时间线回看任务过程。", "Runbook", "Task 筛选"],
      },
      {
        locale: "zh-CN",
        url: `${server.baseUrl}/worker-queue?lang=zh-CN`,
        testId: "dashboard-worker-queue-hero",
        required: ["查看哪些 agent 正在忙、谁会接下来处理什么，以及哪些排队任务还没有负责人。", "当前负载与待处理工作"],
      },
      {
        locale: "zh-CN",
        url: `${server.baseUrl}/alerts?lang=zh-CN`,
        testId: "dashboard-alerts-hero",
        required: ["集中查看阻塞、失败任务，以及当前 job 里仍待处理的跟进提醒。", "当前需要处理的事项"],
      },
      {
        locale: "zh-CN",
        url: `${server.baseUrl}/health?lang=zh-CN`,
        testId: "dashboard-health-hero",
        required: ["检查 dashboard 是否能读取最新任务数据和后台状态。", "关键健康信号"],
      },
    ];

    for (const spec of pages) {
      await page.goto(spec.url);
      await expect(page.getByTestId(spec.testId)).toBeVisible();
      await expect(page.locator("html")).toHaveAttribute("lang", spec.locale === "zh-CN" ? "zh-CN" : "en");

      const text = await collectVisibleText(page);
      const hit = forbiddenVisible.filter((needle) => text.includes(needle));
      findings.push({ locale: spec.locale, url: spec.url, hit, text });

      for (const copy of spec.required) {
        expect(text).toContain(copy);
      }

      if (spec.url.includes("/health")) {
        expect(text).toContain("daemon_state.json");
      }
    }

    const disallowed = findings.flatMap((item) =>
      item.hit
        .filter((needle) => needle !== "daemon_state.json")
        .map((needle) => `${item.locale} ${item.url} -> ${needle}`),
    );

    expect(disallowed).toEqual([]);
  } finally {
    await stopDashboard(server);
    await fs.rm(homeDir, { recursive: true, force: true });
  }
});
