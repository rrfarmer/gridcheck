"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const { nativeClientPorts, portsForSlot, serverEnvironment } = require("../core/ports");
const { loadTreeConfig, validateConfig } = require("../core/treeConfig");
const { prepareClientLaunch, waitForNativeChat } = require("../core/client");

test("native profile retains game isolation and pins the two native destinations", () => {
  const block = portsForSlot(141);
  assert.equal(nativeClientPorts(block), block);
  const ports = nativeClientPorts(block, true);
  assert.equal(ports.game, block.game);
  assert.equal(ports.gateway, block.gateway);
  assert.equal(ports.xmpp, 5222);
  assert.equal(ports.cdn, 443);
  assert.equal(serverEnvironment(ports).EVEJS_XMPP_SERVER_PORT, "5222");
  assert.equal(serverEnvironment(ports).EVEJS_PROXY_LOOPBACK_CDN_LISTEN_PORT, "443");
  assert.deepEqual(validateConfig({ configVersion: 1, nativeClient: true }), []);
  assert.match(validateConfig({ configVersion: 1, nativeClient: "true" }).join(), /nativeClient/);
  assert.equal(loadTreeConfig(__dirname, { env: {} }).nativeClient, false);
});

function setup() {
  const treeRoot = path.resolve("test-tree");
  const exe = path.join(treeRoot, "client", "tq", "bin64", "exefile.exe");
  const resfiles = path.join(treeRoot, "client", "ResFiles");
  const ports = nativeClientPorts(portsForSlot(141), true);
  const output = `    Client: ${exe} /port:${ports.game}\n    ResFiles: ${resfiles}\n    Proxy:  http://127.0.0.1:${ports.gateway}/\nDry run complete. Client launch skipped.`;
  return { treeRoot, exe, resfiles, ports, dataRoot: path.join(treeRoot, "_local"),
    platform: "win32", env: {}, readText: () => 'if "%EVEJS_DRY_RUN%"=="1"',
    run: () => ({ status: 0, stdout: output }), output };
}

test("automation executes Play's complete dry run against the intended server before spawning", () => {
  const opts = setup();
  let called = false;
  const ready = prepareClientLaunch({ ...opts, run: (exe, args, options) => {
    called = true;
    assert.equal(exe, "cmd.exe");
    assert.deepEqual(args, ["/d", "/s", "/c", 'call "%GRIDCHECK_PLAY_LAUNCHER%"']);
    assert.equal(options.input, "");
    assert.equal(options.windowsHide, true);
    assert.equal(options.windowsVerbatimArguments, true, "cmd receives batch quotes without C-runtime backslash escaping");
    assert.equal(options.env.EVEJS_DRY_RUN, "1");
    assert.equal(options.env.EVEJS_SERVER_PORT, "32820");
    assert.equal(options.env.EVEJS_MICROSERVICES_PUBLIC_URL, "http://127.0.0.1:32822/");
    assert.equal(options.env.EVEJS_DATA_ROOT, opts.dataRoot);
    return { status: 0, stdout: opts.output };
  } });
  assert.equal(called, true);
  assert.equal(ready.env.EO_REMOTEFILECACHEFOLDER, opts.resfiles);
  assert.equal(ready.env.HTTPS_PROXY, "http://127.0.0.1:32822/");
  assert.equal(ready.env.EVEJS_DRY_RUN, undefined, "preflight-only variables do not leak to the client");
});

test("wrong native ports, failed or obsolete Play and mismatched targets all refuse launch", () => {
  const opts = setup();
  assert.throws(() => prepareClientLaunch({ ...opts, ports: portsForSlot(141) }), /5222/);
  assert.throws(() => prepareClientLaunch({ ...opts, readText: () => "old Play" }), /dry-run/);
  assert.throws(() => prepareClientLaunch({ ...opts, run: () => ({ status: 1, stdout: "certificate failed" }) }), /certificate failed/);
  assert.throws(() => prepareClientLaunch({ ...opts, run: () => ({ status: null, error: new Error("timeout") }) }), /timeout/);
  assert.throws(() => prepareClientLaunch({ ...opts, exe: path.join(opts.treeRoot, "other.exe") }), /different client/);
  assert.throws(() => prepareClientLaunch({ ...opts, run: () => ({ status: 0, stdout: "no completion marker" }) }), /preflight failed/);
});

test("Windows executes a Play dry run from a path with spaces using real cmd quoting", { skip: process.platform !== "win32" }, (t) => {
  const treeRoot = fs.mkdtempSync(path.join(os.tmpdir(), "gridcheck play launch "));
  t.after(() => fs.rmSync(treeRoot, { recursive: true, force: true }));
  const exe = path.join(treeRoot, "client copy", "tq", "bin64", "exefile.exe");
  const resfiles = path.join(treeRoot, "client copy", "ResFiles");
  fs.writeFileSync(path.join(treeRoot, "Play.bat"), [
    "@echo off", 'if "%EVEJS_DRY_RUN%"=="1" goto gate', "exit /b 9", ":gate",
    `echo     Client: ${exe} /port:%EVEJS_SERVER_PORT%`, `echo     ResFiles: ${resfiles}`,
    "echo     Proxy:  %EVEJS_MICROSERVICES_PUBLIC_URL%", "echo Dry run complete. Client launch skipped.", "exit /b 0",
  ].join("\r\n") + "\r\n");
  const result = prepareClientLaunch({ treeRoot, exe, resfiles,
    dataRoot: path.join(treeRoot, "_local"), ports: nativeClientPorts(portsForSlot(141), true) });
  assert.match(result.output, /Dry run complete/);
  assert.equal(result.env.EO_REMOTEFILECACHEFOLDER, resfiles);
});

test("chat readiness waits for authentication, fails on popup and refuses a timeout", async () => {
  let clock = 0;
  const wait = { deadlineMs: 3000, now: () => clock, sleep: async (ms) => { clock += ms; } };
  let reads = 0;
  await waitForNativeChat({ ...wait, read: async () => ({ ready: ++reads === 2 }) });
  assert.equal(reads, 2);
  await assert.rejects(waitForNativeChat({ ...wait, read: async () => ({ failed: true, ready: true }) }), /never dismiss/);
  await assert.rejects(waitForNativeChat({ ...wait, read: async () => ({ ready: false }) }), /did not authenticate/);
});
