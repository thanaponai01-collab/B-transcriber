/* The Transform tab's heartbeat poll: fast (150 ms) for 2 s after activity, then once a second,
   backing off to once every 4 s while nothing changes. The timer ticks every 150 ms either way,
   so the idle rate has to be enforced per tick. */
const test = require("node:test");
const assert = require("node:assert/strict");
const { createAlignFeature } = require("../uxp/cutdeck/features/align.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");

test("align poll: fast right after activity, then backs off while idle and nothing changes", async (t) => {
  t.mock.timers.enable({ apis: ["setInterval", "Date"], now: 1_000_000 });
  let reads = 0;
  const ppro = { Project: { getActiveProject: () => { reads++; return { getActiveSequence: () => null }; } } };
  const ctl = createController({ render: () => {}, initialState: { sequence: null, transform: null } });
  const align = createAlignFeature({ ppro, ctl });
  const run = async (ms) => {
    for (let i = 0; i < ms / 150; i++) {
      t.mock.timers.tick(150);
      for (let j = 0; j < 20; j++) await Promise.resolve();
    }
  };
  align.startPolling();
  await run(1950);
  const fast = reads;
  assert.ok(fast >= 10, `only ${fast} reads in the 2 s after activity`);
  reads = 0;
  await run(6000);
  assert.ok(reads <= 4, `${reads} reads in 6 s of unchanged idle (expected about 3: 1 s, 2 s, 4 s apart)`);
  assert.ok(reads >= 2, `${reads} reads in 6 s of idle: the idle poll stopped`);
  reads = 0;
  await run(12000);
  align.stopPolling();
  assert.ok(reads >= 3 && reads <= 4, `${reads} reads in 12 s at the backed-off rate (expected 3, every 4 s)`);
});

test("align poll: a change or activity brings the idle rate back to once a second", async (t) => {
  t.mock.timers.enable({ apis: ["setInterval", "Date"], now: 1_000_000 });
  let name = "A";
  const seq = { get name() { return name; } };
  const ppro = { Project: { getActiveProject: () => ({ getActiveSequence: () => seq }) } };
  const ctl = createController({ render: () => {}, initialState: { sequence: null, transform: null } });
  const align = createAlignFeature({ ppro, ctl });
  const run = async (ms) => {
    for (let i = 0; i < ms / 150; i++) {
      t.mock.timers.tick(150);
      await new Promise((resolve) => setImmediate(resolve));
    }
  };
  align.startPolling();
  await run(12000);
  assert.equal(align.currentPollInterval(), 4000);
  name = "B";
  let reset = false;
  for (let ms = 0; ms < 4500 && !reset; ms += 150) {
    await run(150);
    reset = align.currentPollInterval() === 1000;
  }
  assert.ok(reset, "a changed read did not reset the idle rate");
  await run(6000);
  assert.ok(align.currentPollInterval() > 1000);
  align.noteActivity();
  t.mock.timers.tick(2500);
  assert.equal(align.currentPollInterval(), 1000, "activity did not reset the idle rate");
  align.stopPolling();
});
