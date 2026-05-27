#!/usr/bin/env node
"use strict";

const { spawnSync } = require("child_process");
const path = require("path");

const packageJson = require("../package.json");
const args = process.argv.slice(2);

function run(command, commandArgs, options) {
  const result = spawnSync(command, commandArgs, {
    stdio: "inherit",
    ...options,
  });

  if (result.error) {
    if (result.error.code === "ENOENT") {
      console.error(`mcp-broker: missing executable: ${command}`);
    } else {
      console.error(`mcp-broker: ${result.error.message}`);
    }
    process.exit(127);
  }

  if (result.signal) {
    console.error(`mcp-broker: command terminated by signal ${result.signal}`);
    process.exit(1);
  }

  process.exit(result.status ?? 1);
}

const devRoot = process.env.MCP_BROKER_NPM_DEV_ROOT;

if (devRoot) {
  const executable =
    process.platform === "win32"
      ? path.join(devRoot, "venv-mcp-broker", "Scripts", "mcp-broker.exe")
      : path.join(devRoot, "venv-mcp-broker", "bin", "mcp-broker");
  run(executable, args, {});
}

run(
  "uvx",
  ["--from", `mcp-broker==${packageJson.version}`, "mcp-broker", ...args],
  {}
);
