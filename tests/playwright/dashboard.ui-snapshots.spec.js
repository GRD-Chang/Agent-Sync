const { test, expect } = require("@playwright/test");
const { spawn, spawnSync } = require("node:child_process");
const fs = require("node:fs/promises");
const os = require("node:os");
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

async function seedSnapshotHome(homeDir) {
  const jobTitles = [
    "job-a",
    "job-b",
    "job-c",
    "job-d",
    "job-e",
    "job-f",
    "job-g",
    "job-h",
    "job-i",
    "job-j",
    "job-k",
    "job-l",
    "job-m",
    "job-n",
    "job-o",
    "job-p",
    "job-q",
    "job-r",
    "job-s",
    "job-t",
    "Overflow containment review: this job title should never push chips outside the filter panel",
    "Unicode-safe-ASCII-only title with a surprisingly long segment: supercalifragilisticexpialidocious-and-beyond",
    `NO_BREAK_${"X".repeat(180)}`,
  ];

  const jobs = jobTitles.map((title) => runBridgeJson(homeDir, ["create-job", "--title", title]));
  jobs.forEach((job, index) => {
    const agent = ["code-agent", "quality-agent", "review-agent", "ops-agent"][index % 4];
    runBridgeJson(homeDir, [
      "create-task",
      "--job",
      job.id,
      "--requirement",
      `seed task ${index + 1}`,
      "--assign",
      agent,
    ]);
  });

  const timelineJob = runBridgeJson(homeDir, [
    "create-job",
    "--title",
    "Dispatch timeline job (UI snapshot) - horizontal scroll and live edge",
  ]);

  const timelineEvents = [
    {
      requirement: "queued req 1",
      assign: "code-agent",
      state: "queued",
      dispatchAt: "2026-03-19T02:12:00Z",
    },
    {
      requirement: "running req 2",
      assign: "quality-agent",
      state: "running",
      result: "actively working",
      dispatchAt: "2026-03-19T03:44:00Z",
    },
    {
      requirement: "blocked req 3",
      assign: "review-agent",
      state: "blocked",
      result: "waiting on input",
      dispatchAt: "2026-03-19T05:08:00Z",
    },
    {
      requirement: "failed req 4",
      assign: "ops-agent",
      state: "failed",
      result: "worker crashed",
      dispatchAt: "2026-03-19T06:37:00Z",
    },
    {
      requirement: "done req 5",
      assign: "team-leader",
      state: "done",
      result: "wrapped up",
      dispatchAt: "2026-03-19T07:55:00Z",
    },
    {
      requirement: "running req 6",
      assign: "planning-agent",
      state: "running",
      result: "collecting evidence",
      dispatchAt: "2026-03-19T09:16:00Z",
    },
    {
      requirement: "blocked req 7",
      assign: "quality-agent",
      state: "blocked",
      result: "pending fixture refresh",
      dispatchAt: "2026-03-19T10:28:00Z",
    },
    {
      requirement: "done req 8",
      assign: "review-agent",
      state: "done",
      result: "review signed off",
      dispatchAt: "2026-03-19T11:54:00Z",
    },
    {
      requirement: "queued req 9",
      assign: "ops-agent",
      state: "queued",
      dispatchAt: "2026-03-19T13:12:00Z",
    },
    {
      requirement: "running req 10",
      assign: "team-leader",
      state: "running",
      result: "triaging live edge",
      dispatchAt: "2026-03-19T14:40:00Z",
    },
    {
      requirement: "done req 11",
      assign: "code-agent",
      state: "done",
      result: "history slice archived",
      dispatchAt: "2026-03-19T16:05:00Z",
    },
    {
      requirement: "blocked req 12",
      assign: "review-agent",
      state: "blocked",
      result: "awaiting final ack",
      dispatchAt: "2026-03-19T17:18:00Z",
    },
    {
      requirement: "queued req 13 with a deliberately long descriptive summary to force timeline width on desktop",
      assign: "ops-agent",
      state: "queued",
      dispatchAt: "2026-03-19T18:26:00Z",
    },
    {
      requirement: "running req 14 with long evidence collection note for horizontal overflow validation",
      assign: "quality-agent",
      state: "running",
      result: "capturing overflow verification evidence for timeline regression coverage",
      dispatchAt: "2026-03-19T19:44:00Z",
    },
    {
      requirement: "done req 15 with long archive note for historical visibility coverage",
      assign: "release-agent",
      state: "done",
      result: "archived historical timeline slice after confirming older cards remain readable",
      dispatchAt: "2026-03-19T20:58:00Z",
    },
  ];

  for (const event of timelineEvents) {
    const task = runBridgeJson(homeDir, [
      "create-task",
      "--job",
      timelineJob.id,
      "--requirement",
      event.requirement,
      "--assign",
      event.assign,
    ]);

    if (event.state === "running") {
      runBridgeJson(homeDir, ["start", task.id, "--job", timelineJob.id, "--result", event.result]);
    } else if (event.state === "blocked") {
      runBridgeJson(homeDir, ["block", task.id, "--job", timelineJob.id, "--result", event.result]);
    } else if (event.state === "failed") {
      runBridgeJson(homeDir, ["fail", task.id, "--job", timelineJob.id, "--result", event.result]);
    } else if (event.state === "done") {
      runBridgeJson(homeDir, ["complete", task.id, "--job", timelineJob.id, "--result", event.result]);
    }

    await patchLastDispatchAt(homeDir, timelineJob.id, task.id, event.dispatchAt);
  }

  return { jobId: timelineJob.id };
}

const {
  expectNoHorizontalOverflow,
  expectChipsContained,
  getTimelineWindowState,
  expectTimelineRailContinuous,
  expectTimelineCardsReadable,
} = require("./ui-layout-assertions");

function getVisibleTimelineIds(state) {
  return state.fullyVisibleIds.length > 0 ? state.fullyVisibleIds : state.mostlyVisibleIds;
}

test.describe("dashboard UI snapshots for task-bridge job/task", () => {
  test("capture tasks job-scope and jobs dispatch timeline", async ({ page }) => {
    const phase = process.env.UI_SNAPSHOT_PHASE || "after";
    const phaseKey = sanitize(String(phase || "snapshot")).toLowerCase();
    const strict = phaseKey !== "before";

    const outDir =
      process.env.UI_SNAPSHOT_DIR || path.join(repoRoot, "artifacts", "ui-screenshots", phaseKey);

    const viewports = [
      { label: "desktop", width: 1440, height: 1100 },
      { label: "narrow", width: 390, height: 844 },
    ];

    let homeDir = process.env.TASK_BRIDGE_HOME;
    let ownsHomeDir = false;
    let jobId = process.env.UI_SNAPSHOT_JOB_ID;
    let seededHome = false;

    if (!homeDir) {
      homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "task-bridge-ui-snapshot-"));
      ownsHomeDir = true;
      await seedSnapshotHome(homeDir);
      seededHome = true;
    }

    // If TASK_BRIDGE_HOME is provided but no jobId is specified, seed a minimal home.
    // This keeps CI/local runs frictionless while still allowing callers to provide
    // an explicit jobId for targeted snapshots.
    if (!jobId) {
      if (!seededHome) {
        await seedSnapshotHome(homeDir);
      }
      jobId = runBridgeJson(homeDir, ["current-job"]).id;
    }

    await fs.mkdir(outDir, { recursive: true });

    const server = await startDashboard(homeDir, 4399);

    try {
      for (const viewport of viewports) {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });

        // TASKS page: Job scope panel
        await page.goto(`${server.baseUrl}/tasks`);
        await page.waitForLoadState("networkidle");

        const jobScope = page.getByTestId("dashboard-tasks-filter-job");
        await expect(jobScope).toBeVisible();
        await jobScope.scrollIntoViewIfNeeded();

        // Capture a realistic state (expanded list) so scroll + truncation are visible.
        const toggle = jobScope.locator("[data-job-scope-toggle]");
        if ((await toggle.count()) > 0) {
          // Expand deterministically.
          // Click can be flaky due to overlapping headings intercepting pointer events;
          // use DOM click (no pointer hit-testing) and then wait briefly.
          const expanded = await toggle.getAttribute("aria-expanded");
          if (expanded !== "true") {
            await toggle.evaluate((node) => node.click());
            await expect(toggle)
              .toHaveAttribute("aria-expanded", "true", { timeout: 1500 })
              .catch(() => null);
          }
        }

        await jobScope.screenshot({
          path: path.join(outDir, `tasks-job-scope-${viewport.label}-${viewport.width}x${viewport.height}.png`),
        });

        if (strict) {
          const jobScopePanel = jobScope.locator("[data-job-scope-panel]");
          await expectNoHorizontalOverflow(page, jobScope, { tolerancePx: 2 });
          await expectNoHorizontalOverflow(page, jobScopePanel, { tolerancePx: 2 });

          const chips = jobScope.locator("[data-job-scope-chip]");
          if ((await chips.count()) > 0) {
            await expectChipsContained(jobScopePanel, chips, { tolerancePx: 2 });
          }
        }

        // JOB detail: dispatch timeline
        const jobDetailUrl = `${server.baseUrl}/jobs?job=${jobId}#job-detail`;

        await page.goto(jobDetailUrl);
        await page.waitForLoadState("networkidle");

        const timeline = page.getByTestId("dashboard-jobs-dispatch-timeline");
        await timeline.waitFor({ state: "visible", timeout: 15000 });
        await timeline.scrollIntoViewIfNeeded();
        await page.waitForTimeout(150);
        await expect(timeline.locator('.dispatch-node-link[data-agent="planning-agent"]')).toHaveCount(1);
        await expect(timeline.locator('.dispatch-node-link[data-agent="release-agent"]')).toHaveCount(1);

        if (strict) {
          const timelineScrollport = page.getByTestId("dashboard-jobs-timeline-scrollport");
          await expectNoHorizontalOverflow(page, timeline, {
            tolerancePx: 2,
            allowInternalScroll: true,
          });
          await expectTimelineRailContinuous(timeline, {
            railSelector: ".dispatch-timeline-rail",
            cardSelector: ".dispatch-node-link",
          });

          await expect
            .poll(async () => {
              const state = await getTimelineWindowState(timeline);
              return Math.round(state.maxScrollLeft - state.scrollLeft);
            })
            .toBeLessThanOrEqual(48);

          await timeline.screenshot({
            path: path.join(
              outDir,
              `job-dispatch-timeline-${viewport.label}-${viewport.width}x${viewport.height}.png`,
            ),
          });

          const latestState = await expectTimelineCardsReadable(timeline, {
            minVisibleCards: viewport.label === "desktop" ? 2 : 1,
          });
          const latestVisibleIds = getVisibleTimelineIds(latestState);
          expect(latestState.cardIds.length).toBeGreaterThan(8);
          expect(latestVisibleIds.length).toBeGreaterThanOrEqual(viewport.label === "desktop" ? 2 : 1);
          if (latestVisibleIds.length < latestState.cardIds.length) {
            expect(latestVisibleIds).toEqual(
              latestState.cardIds.slice(-latestVisibleIds.length),
            );
            expect(latestVisibleIds).toContain(latestState.cardIds.at(-1));
            expect(latestState.mostlyVisibleIds).not.toContain(latestState.cardIds[0]);
          } else {
            expect(latestVisibleIds).toEqual(latestState.cardIds);
          }

          await timelineScrollport.evaluate((node) => {
            node.scrollTo({ left: 0, behavior: "auto" });
            node.dispatchEvent(new Event("scroll", { bubbles: true }));
          });
          await expect
            .poll(async () => {
              const state = await getTimelineWindowState(timeline);
              return Math.round(state.scrollLeft);
            })
            .toBeLessThanOrEqual(2);

          await timeline.screenshot({
            path: path.join(
              outDir,
              `job-dispatch-timeline-scrolled-${viewport.label}-${viewport.width}x${viewport.height}.png`,
            ),
          });

          const olderState = await getTimelineWindowState(timeline);
          const olderVisibleIds = getVisibleTimelineIds(olderState);
          if (olderVisibleIds.length < olderState.cardIds.length) {
            expect(olderVisibleIds).not.toEqual(latestVisibleIds);
            expect(olderState.mostlyVisibleIds).toContain(olderState.cardIds[0]);
            expect(olderState.mostlyVisibleIds[0]).toBe(olderState.cardIds[0]);
            expect(olderState.mostlyVisibleIds).not.toContain(olderState.cardIds.at(-1));
          } else {
            expect(olderVisibleIds).toEqual(olderState.cardIds);
          }
        } else {
          await timeline.screenshot({
            path: path.join(
              outDir,
              `job-dispatch-timeline-${viewport.label}-${viewport.width}x${viewport.height}.png`,
            ),
          });
        }
      }
    } finally {
      await stopDashboard(server);
      if (ownsHomeDir && homeDir) {
        await fs.rm(homeDir, { recursive: true, force: true });
      }
    }
  });
});
