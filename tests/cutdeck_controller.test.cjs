const test = require("node:test");
const assert = require("node:assert/strict");
const { createController } = require("../uxp/cutdeck/features/controller.js");

test("createController requires a render function", () => {
  assert.throws(() => createController({}), /render function/);
  assert.throws(() => createController({ render: "not-a-fn" }), /render function/);
});

test("initializes state with busy false and default Ready status", () => {
  const renders = [];
  const ctl = createController({
    render: (s) => renders.push(JSON.parse(JSON.stringify(s))),
    initialState: { customField: 42 },
  });

  assert.equal(ctl.state.customField, 42);
  assert.equal(ctl.state.busy, false);
  assert.deepEqual(ctl.state.status, { text: "Ready", level: "ready" });
  assert.equal(renders.length, 0);
});

test("setStatus updates state.status and invokes render", () => {
  const renders = [];
  const ctl = createController({
    render: (s) => renders.push(JSON.parse(JSON.stringify(s))),
  });

  ctl.setStatus("Custom message", "error");
  assert.deepEqual(ctl.state.status, { text: "Custom message", level: "error" });
  assert.equal(renders.length, 1);
  assert.deepEqual(renders[0].status, { text: "Custom message", level: "error" });
});

test("busy gate drops a second call", async () => {
  const renders = [];
  const ctl = createController({
    render: (s) => renders.push(JSON.parse(JSON.stringify(s))),
  });

  let resolveFirst;
  let firstRan = false;
  let secondRan = false;

  const firstPromise = ctl.act(() => new Promise((resolve) => {
    firstRan = true;
    resolveFirst = resolve;
  }));

  // While first is in-flight, busy is true
  assert.equal(ctl.state.busy, true);

  // Attempt second call: must be dropped
  const secondPromise = ctl.act(async () => {
    secondRan = true;
  });

  await secondPromise;
  assert.equal(secondRan, false, "second call should have been dropped by busy gate");

  resolveFirst();
  await firstPromise;

  assert.equal(firstRan, true);
  assert.equal(ctl.state.busy, false);
});

test("a thrown Error's message lands in status with level error", async () => {
  const renders = [];
  const ctl = createController({
    render: (s) => renders.push(JSON.parse(JSON.stringify(s))),
  });

  // Temporarily suppress console.error
  const origError = console.error;
  console.error = () => {};
  try {
    await ctl.act(async () => {
      throw new Error("Something broke in Premiere");
    });
  } finally {
    console.error = origError;
  }

  assert.equal(ctl.state.busy, false);
  assert.deepEqual(ctl.state.status, {
    text: "Something broke in Premiere",
    level: "error",
  });
});

test("status left busy by fn resets to Ready", async () => {
  const ctl = createController({
    render: () => {},
  });

  await ctl.act(async () => {
    // Left at busy
    ctl.state.status = { text: "Still working...", level: "busy" };
  });

  assert.equal(ctl.state.busy, false);
  assert.deepEqual(ctl.state.status, { text: "Ready", level: "ready" });
});

test("status explicitly set to non-busy by fn is preserved", async () => {
  const ctl = createController({
    render: () => {},
  });

  await ctl.act(async () => {
    ctl.setStatus("Completed 12 cuts!", "ready");
  });

  assert.equal(ctl.state.busy, false);
  assert.deepEqual(ctl.state.status, { text: "Completed 12 cuts!", level: "ready" });
});

test("render is called on start and finish", async () => {
  const states = [];
  const ctl = createController({
    render: (s) => states.push({ busy: s.busy, status: { ...s.status } }),
  });

  await ctl.act(async () => {
    assert.equal(states.length, 1);
    assert.equal(states[0].busy, true);
    assert.deepEqual(states[0].status, { text: "Processing…", level: "busy" });
  });

  assert.equal(states.length, 2);
  assert.equal(states[1].busy, false);
  assert.deepEqual(states[1].status, { text: "Ready", level: "ready" });
});
