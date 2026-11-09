"use strict";

// requestJSON sends a GET, or a request marked idempotent, once more when the
// socket it was written to turns out to be reset; any other request fails.

const test = require("node:test");
const assert = require("node:assert");
const http = require("node:http");

const { requestJSON } = require("../bin/gridcheck");

// A server that resets the first connection a request arrives on, and answers
// every later one.
async function resettingServer(t) {
  let requests = 0;
  const server = http.createServer((req, res) => {
    requests += 1;
    if (requests === 1) {
      req.socket.destroy();
      return;
    }
    res.setHeader("content-type", "application/json");
    res.end(JSON.stringify({ ok: true, requests }));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  return { url: `http://127.0.0.1:${server.address().port}/x`, count: () => requests };
}

test("a GET is sent again after a reset", async (t) => {
  const server = await resettingServer(t);
  const { status, json } = await requestJSON(server.url);
  assert.strictEqual(status, 200);
  assert.strictEqual(json.requests, 2);
});

test("a POST marked idempotent is sent again after a reset", async (t) => {
  const server = await resettingServer(t);
  const { json } = await requestJSON(server.url, { method: "POST", body: { a: 1 }, idempotent: true });
  assert.strictEqual(json.requests, 2);
});

test("any other POST fails on a reset and is not sent twice", async (t) => {
  const server = await resettingServer(t);
  await assert.rejects(
    requestJSON(server.url, { method: "POST", body: { a: 1 } }),
    (error) => error.transport === true && /ECONNRESET|UND_ERR_SOCKET/.test(error.message),
  );
  assert.strictEqual(server.count(), 1);
});
