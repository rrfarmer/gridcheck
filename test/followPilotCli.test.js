"use strict";

const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const http = require("node:http");
const { spawn } = require("node:child_process");
const { createAgentBridgeHttp } = require("../bridge/http");
const { createAgentBridgeRoutes } = require("../bridge/routes");
const { createGridWatch } = require("../bridge/watch");

test("watch --pilot streams an offline pilot without a held login, preserving --no-modules", async (t) => {
  const tree = fs.mkdtempSync(path.join(os.tmpdir(), "gridcheck-follow-"));
  t.after(() => fs.rmSync(tree, { recursive: true, force: true }));
  const requests = [];
  const gateway = http.createServer((req, res) => {
    requests.push([req.method, req.url]);
    res.setHeader("content-type", "application/json");
    if (req.url === "/_evejs-web/v1/account?username=other") res.end(JSON.stringify({ accountID: 11 }));
    else if (req.url === "/_evejs-web/v1/characters?accountID=11") res.end(JSON.stringify({ characters: [{ characterID: 7 }] }));
    else { res.statusCode = 400; res.end(JSON.stringify({ ok: false, error: "unexpected request" })); }
  });
  await new Promise((resolve) => gateway.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => gateway.close(resolve)));

  let clock = 1000;
  const watch = createGridWatch({ findSession: () => null, now: () => clock, wait: async (ms) => { clock += ms; } });
  const seen = [];
  const routes = createAgentBridgeRoutes({
    findSession: () => null,
    watcher: { busy: () => watch.busy(), run: (options, sink) => { seen.push(options); return watch.run(options, sink); } },
  });
  const handshakePath = path.join(tree, "bridge.json");
  const bridge = createAgentBridgeHttp({ routes, port: 0, handshakePath });
  await bridge.start();
  t.after(() => bridge.stop());
  const handshake = JSON.parse(fs.readFileSync(handshakePath, "utf8"));
  handshake.ports = { gateway: gateway.address().port };
  fs.writeFileSync(handshakePath, JSON.stringify(handshake));
  fs.writeFileSync(path.join(tree, "gridcheck.config.json"), JSON.stringify({ configVersion: 1, mode: "attach", handshake: "bridge.json" }));

  const child = spawn(process.execPath, [path.resolve(__dirname, "../bin/gridcheck.js"), "watch", "--pilot", "other",
    "--for", "1", "--every", "0.5", "--no-log", "--no-modules", "--json", "--run", "follow"], {
    env: { ...process.env, GRIDCHECK_TREE: tree }, windowsHide: true, stdio: ["ignore", "pipe", "pipe"],
  });
  t.after(() => { if (child.exitCode === null) child.kill(); });
  let output = "";
  child.stdout.on("data", (chunk) => { output += chunk; });
  child.stderr.on("data", (chunk) => { output += chunk; });
  const code = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => { child.kill(); reject(new Error("watch CLI timed out")); }, 15000);
    child.once("error", (error) => { clearTimeout(timer); reject(error); });
    child.once("close", (value) => { clearTimeout(timer); resolve(value); });
  });
  assert.strictEqual(code, 0, output);
  assert.deepStrictEqual(requests, [["GET", "/_evejs-web/v1/account?username=other"], ["GET", "/_evejs-web/v1/characters?accountID=11"]]);
  assert.deepStrictEqual([seen[0].characterID, seen[0].follow, seen[0].clientMode, seen[0].modules], [7, true, "off", false]);
  const timeline = fs.readFileSync(path.join(tree, "_local/gridcheck/runs/follow/timeline.jsonl"), "utf8").trim().split("\n").map(JSON.parse);
  assert.deepStrictEqual(timeline.map((event) => event.kind), ["START", "PILOT", "END"]);
  assert.strictEqual(timeline[1].online, false);
});
