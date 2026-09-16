const test = require("node:test");
const assert = require("node:assert/strict");
const { createRpc } = require("../uxp/cutdeck/rpc.js");

/* Premiere's cold-start denial, thrown out of the WebSocket constructor. */
const DENIED = "Permission denied to the url ws://127.0.0.1:7891. Manifest entry not found.";

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

test("each request opens and closes its own connection", async () => {
  const h = harness(["open"]);
  let expected = 0;
  for (const type of ["hello", "status"]) {
    const pending = h.rpc({ type });
    (await ready(h, ++expected)).reply({ ok: true });
    await pending;
  }
  assert.equal(h.attempts.length, 2);
  assert.ok(h.attempts.every((s) => s.closed));
});
