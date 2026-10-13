/* The Transform tab's heartbeat poll: fast (150 ms) for 2 s after activity, then once a second.
   The timer ticks every 150 ms either way, so the idle rate has to be enforced per tick. */
const test = require("node:test");
const assert = require("node:assert/strict");
const { createAlignFeature } = require("../uxp/cutdeck/features/align.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");

test("align poll: fast right after activity, at most once a second when idle", async (t) => {
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
  align.stopPolling();
  assert.ok(reads <= 7, `${reads} reads in 6 s of idle (expected about 6)`);
  assert.ok(reads >= 5, `${reads} reads in 6 s of idle: the idle poll stopped`);
});
