const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createRpc, URL } = require("../uxp/cutdeck/core/rpc.js");

/* Premiere's cold-start denial, thrown out of the WebSocket constructor. */
const DENIED = `Permission denied to the url ${URL}. Manifest entry not found.`;

function fakeSocket() {
  const socket = {
    sent: [], closed: false,
    send(payload) { socket.sent.push(payload); },
    close() { socket.closed = true; },
    reply(value) { socket.onmessage({ data: JSON.stringify(value) }); },
  };
  return socket;
}

/* Drives the retry loop without real timers, and records each attempt. */
function harness(behaviors) {
  const attempts = [];
  const sleeps = [];
  const retries = [];
  const rpc = createRpc({
    createSocket: () => {
      const behavior = behaviors[Math.min(attempts.length, behaviors.length - 1)];
      const socket = fakeSocket();
      attempts.push(socket);
      if (behavior === "throw") throw new Error(DENIED);
      const fire = (name) => setTimeout(() => socket[name] && socket[name]({}), 0);
      if (behavior === "error") fire("onerror");
      else if (behavior === "close") fire("onclose");
      else fire("onopen");
      return socket;
    },
    sleep: (ms) => { sleeps.push(ms); return Promise.resolve(); },
    onRetry: (attempt, total) => retries.push([attempt, total]),
  });
  return { rpc, attempts, sleeps, retries };
}

/* Waits for the loop to reach attempt `n` and send, instead of guessing a delay. */
async function ready(h, n) {
  for (let i = 0; i < 500; i++) {
    const socket = h.attempts[n - 1];
    if (h.attempts.length === n && socket && typeof socket.onmessage === "function") return socket;
    await new Promise((done) => setTimeout(done, 1));
  }
  throw new Error(`attempt ${n} never sent; reached ${h.attempts.length}`);
}

test("a cold-start permission denial is retried, not surfaced", async () => {
  const h = harness(["throw", "throw", "open"]);
  const pending = h.rpc({ type: "hello" });
  (await ready(h, 3)).reply({ ok: true, version: "cutdeck-xml-1" });
  assert.deepEqual(await pending, { ok: true, version: "cutdeck-xml-1" });
  assert.equal(h.attempts.length, 3);
  assert.deepEqual(h.sleeps, [200, 400]);
  assert.deepEqual(h.retries, [[2, 5], [3, 5]]);
});

test("a helper that is not listening yet is retried", async () => {
  const h = harness(["error", "close", "open"]);
  const pending = h.rpc({ type: "hello" });
  (await ready(h, 3)).reply({ ok: true });
  assert.deepEqual(await pending, { ok: true });
  assert.equal(h.attempts.length, 3);
});

test("the last failure is reported once the attempts run out", async () => {
  const h = harness(["throw"]);
  await assert.rejects(h.rpc({ type: "hello" }), new RegExp("Permission denied"));
  assert.equal(h.attempts.length, 5);
});

test("a sent request is never sent twice", async () => {
  const h = harness(["open"]);
  const pending = h.rpc({ type: "prepare", sequence_id: "s" });
  (await ready(h, 1)).onclose({});          // reply lost mid-flight
  await assert.rejects(pending, /Resume last job/);
  assert.equal(h.attempts.length, 1);
  assert.equal(h.attempts[0].sent.length, 1);
});

test("a helper error reply resolves as a failure without reconnecting", async () => {
  const h = harness(["open"]);
  const pending = h.rpc({ type: "start", job_id: "x" });
  (await ready(h, 1)).reply({ ok: false, message: "CutDeck is already processing a sequence" });
  await assert.rejects(pending, /already processing/);
  assert.equal(h.attempts.length, 1);
});

test("a helper error reply keeps its machine-readable code", async () => {
  const h = harness(["open"]);
  const pending = h.rpc({ type: "hello", version: "cutdeck-xml-9" });
  (await ready(h, 1)).reply({ ok: false, code: "version_mismatch", message: "Panel/helper version mismatch" });
  await assert.rejects(pending, (error) => error.code === "version_mismatch");
});

/* Waits until `socket` has sent `n` requests. */
async function sentCount(socket, n) {
  for (let i = 0; i < 500; i++) {
    if (socket.sent.length === n) return;
    await new Promise((done) => setTimeout(done, 1));
  }
  throw new Error(`socket sent ${socket.sent.length}, expected ${n}`);
}

test("requests reuse one open connection (the 1.5 s status poll opens no new sockets)", async () => {
  const h = harness(["open"]);
  const socket = await (async () => { const p = h.rpc({ type: "hello" }); const s = await ready(h, 1); s.reply({ ok: true }); await p; return s; })();
  for (let i = 0; i < 3; i++) {
    const pending = h.rpc({ type: "status" });
    await sentCount(socket, i + 2);
    socket.reply({ ok: true, n: i });
    assert.deepEqual(await pending, { ok: true, n: i });
  }
  assert.equal(h.attempts.length, 1);
  assert.equal(socket.closed, false);
});

test("a connection the helper closes while idle is reopened on the next call", async () => {
  const h = harness(["open"]);
  const first = h.rpc({ type: "restart" });
  const s1 = await ready(h, 1);
  s1.reply({ ok: true, restarting: true });
  await first;
  s1.onclose({});                            // helper exits after the restart reply
  const second = h.rpc({ type: "hello" });
  (await ready(h, 2)).reply({ ok: true });
  assert.deepEqual(await second, { ok: true });
  assert.equal(h.attempts.length, 2);
});

test("overlapping calls go out one at a time, each getting its own reply", async () => {
  const h = harness(["open"]);
  const a = h.rpc({ type: "hello" });
  const b = h.rpc({ type: "status" });
  const socket = await ready(h, 1);
  await sentCount(socket, 1);                // b waits for a's reply before sending
  socket.reply({ ok: true, for: "hello" });
  await sentCount(socket, 2);
  socket.reply({ ok: true, for: "status" });
  assert.deepEqual(await a, { ok: true, for: "hello" });
  assert.deepEqual(await b, { ok: true, for: "status" });
  assert.equal(JSON.parse(socket.sent[1]).type, "status");
});

test("a failed call still lets the next call through", async () => {
  const h = harness(["open"]);
  const a = h.rpc({ type: "prepare" });
  (await ready(h, 1)).onclose({});
  await assert.rejects(a, /Resume last job/);
  const b = h.rpc({ type: "hello" });
  (await ready(h, 2)).reply({ ok: true });
  assert.deepEqual(await b, { ok: true });
});

test("rpc default URL is ws://localhost:7891 and is passed to createSocket", async () => {
  assert.equal(URL, "ws://localhost:7891");

  let connectedUrl = null;
  const rpc = createRpc({
    createSocket: (url) => {
      connectedUrl = url;
      const s = fakeSocket();
      s.send = () => {
        setTimeout(() => s.onmessage && s.onmessage({ data: JSON.stringify({ ok: true }) }), 0);
      };
      setTimeout(() => { if (s.onopen) s.onopen({}); }, 0);
      return s;
    },
    attempts: 1,
  });

  const res = await rpc({ type: "ping" });
  assert.deepEqual(res, { ok: true });
  assert.equal(connectedUrl, "ws://localhost:7891");
});

test("createRpc allows custom url override", async () => {
  let connectedUrl = null;
  const custom = "ws://custom-helper:9999";
  const rpc = createRpc({
    url: custom,
    createSocket: (url) => {
      connectedUrl = url;
      const s = fakeSocket();
      s.send = () => {
        setTimeout(() => s.onmessage && s.onmessage({ data: JSON.stringify({ ok: true }) }), 0);
      };
      setTimeout(() => { if (s.onopen) s.onopen({}); }, 0);
      return s;
    },
    attempts: 1,
  });

  const res = await rpc({ type: "ping" });
  assert.deepEqual(res, { ok: true });
  assert.equal(connectedUrl, custom);
});

test("manifest.json network permissions strictly match rpc URL and contain no invalid IP literals", () => {
  const manifestPath = path.join(__dirname, "..", "uxp", "cutdeck", "manifest.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const domains = manifest.requiredPermissions.network.domains;

  assert.ok(Array.isArray(domains), "network.domains must be an array, not a string or 'all'");
  assert.notEqual(domains, "all");
  assert.ok(domains.includes(URL), `network.domains must include rpc default URL ${URL}`);
  assert.equal(domains.length, 1, "network.domains must be narrowed to the single needed helper URL");

  // Invariant: UXP drops IP literals because _hasAValidTopLevelDomain uses tldjs with /localhost/.
  // Assert no entry uses raw IPv4 syntax (e.g. 127.0.0.1).
  for (const d of domains) {
    assert.doesNotMatch(d, /\d+\.\d+\.\d+\.\d+/, "manifest domain must not use IP literals");
  }
});

test("retired socket probe files and registrations do not exist", () => {
  const probePath = path.join(__dirname, "..", "uxp", "cutdeck", "probe.js");
  assert.equal(fs.existsSync(probePath), false, "probe.js must be deleted");

  const { PROBES } = require("../uxp/cutdeck/features/probes.js");
  assert.equal(PROBES.some((p) => p.id === "socket"), false, "PROBES must not contain socket probe");

  const htmlPath = path.join(__dirname, "..", "uxp", "cutdeck", "index.html");
  const html = fs.readFileSync(htmlPath, "utf8");
  assert.doesNotMatch(html, /id=["']socketprobe["']/, "index.html must not contain socketprobe element");
  assert.doesNotMatch(html, /data-probe=["']socket["']/, "index.html must not contain data-probe='socket'");
});

