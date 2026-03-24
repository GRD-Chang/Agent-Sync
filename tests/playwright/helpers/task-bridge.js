const fs = require("node:fs");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

const repoRoot = path.resolve(__dirname, "..", "..", "..");
const srcRoot = path.join(repoRoot, "src");
const interpreterOverrideKeys = ["TASK_BRIDGE_PLAYWRIGHT_PYTHON", "TASK_BRIDGE_PYTHON"];

let cachedPythonExecutable = null;

function buildProbeEnv(extraEnv = {}) {
  const inheritedPythonPath = process.env.PYTHONPATH || "";
  const pythonPath = [srcRoot, inheritedPythonPath].filter(Boolean).join(path.delimiter);
  return {
    ...process.env,
    PYTHONPATH: pythonPath,
    PYTHONUNBUFFERED: "1",
    ...extraEnv,
  };
}

function candidateExecutables() {
  const fromEnv = interpreterOverrideKeys
    .map((key) => (process.env[key] || "").trim())
    .filter(Boolean);

  const virtualEnv = (process.env.VIRTUAL_ENV || "").trim();
  const fromVirtualEnv = virtualEnv
    ? [
        path.join(virtualEnv, "bin", "python"),
        path.join(virtualEnv, "bin", "python3"),
        path.join(virtualEnv, "Scripts", "python.exe"),
      ]
    : [];

  const fromRepo = [
    path.join(repoRoot, ".venv", "bin", "python"),
    path.join(repoRoot, ".venv", "bin", "python3"),
    path.join(repoRoot, ".venv", "Scripts", "python.exe"),
  ];

  return [...fromEnv, ...fromVirtualEnv, ...fromRepo, "python3", "python"];
}

function probePython(candidate) {
  const result = spawnSync(
    candidate,
    ["-c", "import task_bridge, jinja2, starlette, uvicorn"],
    {
      cwd: repoRoot,
      env: buildProbeEnv(),
      encoding: "utf-8",
    },
  );

  if (result.error) {
    return { ok: false, reason: result.error.message };
  }

  if (result.status === 0) {
    return { ok: true, reason: "" };
  }

  const stderr = (result.stderr || result.stdout || "").trim();
  return { ok: false, reason: stderr || `exit ${result.status}` };
}

function getBridgePythonExecutable() {
  if (cachedPythonExecutable) {
    return cachedPythonExecutable;
  }

  const failures = [];
  const seen = new Set();

  for (const candidate of candidateExecutables()) {
    if (!candidate || seen.has(candidate)) {
      continue;
    }
    seen.add(candidate);

    if (path.isAbsolute(candidate) && !fs.existsSync(candidate)) {
      failures.push(`${candidate} (not found)`);
      continue;
    }

    const probe = probePython(candidate);
    if (probe.ok) {
      cachedPythonExecutable = candidate;
      return cachedPythonExecutable;
    }
    failures.push(`${candidate} (${probe.reason})`);
  }

  throw new Error(
    [
      "Unable to find a Python interpreter for the Playwright dashboard harness.",
      "Set TASK_BRIDGE_PLAYWRIGHT_PYTHON to a Python 3.11+ interpreter with the dashboard dependencies installed,",
      "or run the tests from an environment where `python3`/`python` can import task_bridge from ./src.",
      "Candidates tried:",
      ...failures.map((entry) => `- ${entry}`),
    ].join("\n"),
  );
}

function buildBridgeEnv(homeDir, extraEnv = {}) {
  return buildProbeEnv({
    TASK_BRIDGE_HOME: homeDir,
    HOME: homeDir,
    ...extraEnv,
  });
}

function spawnBridge(homeDir, args, options = {}) {
  const { env: extraEnv, ...spawnOptions } = options;
  return spawn(getBridgePythonExecutable(), ["-m", "task_bridge", ...args], {
    cwd: repoRoot,
    env: buildBridgeEnv(homeDir, extraEnv),
    ...spawnOptions,
  });
}

function spawnBridgeSync(homeDir, args, options = {}) {
  const { env: extraEnv, ...spawnOptions } = options;
  return spawnSync(getBridgePythonExecutable(), ["-m", "task_bridge", ...args], {
    cwd: repoRoot,
    env: buildBridgeEnv(homeDir, extraEnv),
    ...spawnOptions,
  });
}

module.exports = {
  buildBridgeEnv,
  getBridgePythonExecutable,
  repoRoot,
  spawnBridge,
  spawnBridgeSync,
};
