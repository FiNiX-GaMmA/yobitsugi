#!/usr/bin/env node
/* eslint-disable */
//
// yobitsugi npm wrapper.
//
// Lets JS-native users invoke the Python yobitsugi CLI without ever touching pip:
//
//   npx yobitsugi install
//   npx yobitsugi scan .
//   npx yobitsugi . --provider anthropic
//
// Under the hood this just delegates to `uvx yobitsugi <args>` (preferred — ephemeral,
// no install) or `pipx run yobitsugi <args>` (fallback). Stdio and exit codes are
// forwarded transparently so you can pipe the output, ctrl-C, etc. exactly as if you
// were running the Python CLI directly.
//
// If neither uv nor pipx is on PATH, the script prints install instructions and exits
// with code 127. It deliberately does NOT try to install a Python runtime for you —
// that's the user's call.
//
"use strict";

const { spawn, spawnSync } = require("child_process");

// Order matters: uvx is preferred because it's faster than pipx run and caches better.
const RUNNERS = [
  { bin: "uvx", prefix: [] },
  { bin: "pipx", prefix: ["run"] },
  { bin: "uv", prefix: ["tool", "run"] },
];

function findRunner() {
  for (const r of RUNNERS) {
    const check = spawnSync(r.bin, ["--version"], { stdio: "ignore" });
    if (check.status === 0) return r;
  }
  return null;
}

function fail(msg, code = 127) {
  process.stderr.write(msg);
  if (!msg.endsWith("\n")) process.stderr.write("\n");
  process.exit(code);
}

function main() {
  const runner = findRunner();
  if (!runner) {
    fail(
      "yobitsugi requires Python 3.10+ and one of: uvx, pipx, or uv on PATH.\n" +
        "\n" +
        "  Install uv (recommended):  curl -LsSf https://astral.sh/uv/install.sh | sh\n" +
        "  Or pipx:                   https://pipx.pypa.io/stable/installation/\n" +
        "\n" +
        "Then re-run: npx yobitsugi <args>\n"
    );
  }

  const args = [...runner.prefix, "yobitsugi", ...process.argv.slice(2)];
  const proc = spawn(runner.bin, args, { stdio: "inherit" });

  // Forward signals so ctrl-C and friends terminate the child cleanly.
  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(sig, () => {
      if (!proc.killed) proc.kill(sig);
    });
  }

  proc.on("error", (err) => {
    fail(`failed to spawn ${runner.bin}: ${err.message}`);
  });

  proc.on("exit", (code, signal) => {
    if (signal) {
      // Re-raise the signal so our exit code reflects it.
      process.kill(process.pid, signal);
      return;
    }
    process.exit(code ?? 1);
  });
}

main();
