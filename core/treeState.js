"use strict";

// Two facts about a tree that the GUI and `gridcheck setup` both check before they
// change it: is its server up, and does it have what a server needs to boot
// (its npm dependencies and its reference data).

const fs = require("node:fs");
const path = require("node:path");

const treeConfig = require("./treeConfig");

const slashed = (file) => String(file).split(path.sep).join("/");
const exists = (file) => {
  try {
    return fs.existsSync(file);
  } catch (_error) {
    return false;
  }
};

function readJSON(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch (_error) {
    return null;
  }
}

function pidAlive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return Boolean(error && error.code === "EPERM");
  }
}

// A server in a container names it in its handshake (EVEJS_AGENT_BRIDGE_CONTAINER): its pid is the container's, not the
// host's, so whether it is up is asked of Docker. Answers are kept for two seconds; Docker being absent is "not up".
const containerChecks = new Map();
function containerRunning(name) {
  const kept = containerChecks.get(name);
  if (kept && Date.now() - kept.atMs < 2000) return kept.up;
  let up = false;
  try {
    up = require("node:child_process").execFileSync("docker", ["inspect", "-f", "{{.State.Running}}", name],
      { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: 5000, windowsHide: true }).trim() === "true";
  } catch (_error) {
    up = false;
  }
  containerChecks.set(name, { up, atMs: Date.now() });
  return up;
}

// The handshake's server is up: its container running, else its pid alive on this host.
function handshakeAlive(handshake) {
  if (!handshake || !handshake.port) return false;
  if (typeof handshake.container === "string" && handshake.container) return containerRunning(handshake.container);
  return pidAlive(Math.trunc(Number(handshake.pid) || 0));
}

// -> { pid, byE2e } for a server that is up, or null.
function serverUpInfo(root, config = treeConfig.loadTreeConfig(root)) {
  const handshake = readJSON(config.handshake);
  if (handshakeAlive(handshake)) return { pid: Number(handshake.pid), byE2e: false };
  const run = readJSON(path.join(config.e2eDir, "run.json"));
  if (run && !run.stoppedAtMs && pidAlive(Math.trunc(Number(run.pid) || 0))) return { pid: Number(run.pid), byE2e: true };
  return null;
}

function serverUpReason(root, config = treeConfig.loadTreeConfig(root)) {
  const up = serverUpInfo(root, config);
  if (!up) return null;
  return `the tree's server is up (pid ${up.pid}${up.byE2e ? ", started by gridcheck up" : ""})`;
}

// -> [{ name, path, ok, fix }]: the tree's npm dependencies and its reference data.
function prerequisites(root, config = treeConfig.loadTreeConfig(root)) {
  const rows = [];
  for (const dir of [root, config.serverDir]) {
    const pkg = readJSON(path.join(dir, "package.json"));
    if (!pkg || !Object.keys(pkg.dependencies || {}).length) continue;
    const where = slashed(path.relative(root, dir)) || ".";
    rows.push({
      name: where === "." ? "the tree's dependencies" : `${where} dependencies`,
      path: where === "." ? "node_modules/" : `${where}/node_modules/`,
      ok: exists(path.join(dir, "node_modules")),
      fix: `npm ci in ${where === "." ? "the tree's root" : where}`,
    });
  }
  rows.push({
    name: "reference data",
    path: `${slashed(path.relative(root, config.dataDir))}/`,
    ok: exists(path.join(config.dataDir, "solarSystems", "data.json")),
    fix: `build ${slashed(path.relative(root, config.dataDir))}: stock EveJS runs tools/DatabaseCreator/CreateDatabase.bat ` +
      "(README, Quick start)",
  });
  return rows;
}

module.exports = {
  handshakeAlive,
  containerRunning, prerequisites, serverUpInfo, serverUpReason };
