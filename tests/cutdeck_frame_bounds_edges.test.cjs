/* transform/frameBounds.js edges the main test file leaves open: which clips count as "underneath"
   at the playhead (start inclusive, end exclusive), and when a saved frame counts as finished
   (same non-zero size on two polls in a row). */
const test = require("node:test");
const assert = require("node:assert/strict");
const fake = require("./fakes/premiere.cjs");
const { measureDrawnBounds } = require("../uxp/cutdeck/transform/frameBounds.js");

const WAIT = { timeoutMs: 200, intervalMs: 1 };
const BOUNDS = { left: 11, top: 904, right: 429, bottom: 991 };

function harness({ playhead = 50, itemStart = 10, sizeFor = () => 99, lower = [] } = {}) {
  const { project } = fake.createProject();
  let disabled = false;
  const item = {
    isDisabled: () => Promise.resolve(disabled),
    getStartTime: () => Promise.resolve(fake.tickTime(itemStart)),
    getEndTime: () => Promise.resolve(fake.tickTime(100)),
    getTrackIndex: () => Promise.resolve(1),
    createSetDisabledAction: (d) => fake.action(() => { disabled = d; }),
  };
  const muteCalls = [];
  const lowerTrack = {
    isMuted: () => Promise.resolve(false),
    setMute: (m) => { muteCalls.push(m); return Promise.resolve(true); },
    getTrackItems: () => Promise.resolve(lower.map(([s, e]) => ({
      isDisabled: () => Promise.resolve(false),
      getStartTime: () => Promise.resolve(fake.tickTime(s)),
      getEndTime: () => Promise.resolve(fake.tickTime(e)),
    }))),
  };
  const seq = {
    getPlayerPosition: () => Promise.resolve(fake.tickTime(playhead)),
    getVideoTrackCount: () => Promise.resolve(2),
    getVideoTrack: (i) => Promise.resolve(i === 0 ? lowerTrack : { isMuted: () => Promise.resolve(false), getTrackItems: () => Promise.resolve([]) }),
  };
  const polls = [];
  const ppro = { Exporter: { exportSequenceFrame: () => Promise.resolve(true) } };
  const getEntry = (name) => {
    polls.push(name);
    const size = sizeFor(polls.length);
    return Promise.resolve({ getMetadata: () => Promise.resolve({ size }), delete: () => Promise.resolve(true) });
  };
  const uxp = { storage: { localFileSystem: { getTemporaryFolder: () => Promise.resolve({ nativePath: "C:\Temp\PluginData", getEntry }) } } };
  const rpcAtPolls = [];
  const rpc = () => { rpcAtPolls.push(polls.length); return Promise.resolve({ bounds: BOUNDS }); };
  const run = () => measureDrawnBounds({ ppro, project, seq, item, frame: { width: 1920, height: 1080 }, rpc, uxp, wait: WAIT });
  return { run, muteCalls, rpcAtPolls };
}

test("a clip below that starts exactly at the playhead counts as underneath (start inclusive)", async () => {
  const h = harness({ lower: [[50, 100]] });
  await h.run();
  assert.deepEqual(h.muteCalls, [true, false], "the track below is muted for the save, then restored");
});

test("a clip below that ends exactly at the playhead does not count (end exclusive)", async () => {
  const h = harness({ lower: [[10, 50]] });
  await h.run();
  assert.deepEqual(h.muteCalls, [], "nothing underneath: no track is touched");
});

test("a clip below that starts after the playhead does not count", async () => {
  const h = harness({ lower: [[51, 100]] });
  await h.run();
  assert.deepEqual(h.muteCalls, []);
});

test("a playhead exactly on the clip's first tick is accepted", async () => {
  const h = harness({ playhead: 10, itemStart: 10 });
  assert.deepEqual(await h.run(), BOUNDS);
});

test("a frame whose size is still growing is not finished: the helper is asked only after two equal polls", async () => {
  const sizes = [10, 20, 99, 99, 99, 99];
  const h = harness({ sizeFor: (n) => sizes[Math.min(n - 1, sizes.length - 1)] });
  assert.deepEqual(await h.run(), BOUNDS);
  assert.ok(h.rpcAtPolls[0] >= 4, `asked the helper after ${h.rpcAtPolls[0]} polls, before the size settled`);
});

test("a frame that never stops growing is an error, not a result", async () => {
  const h = harness({ sizeFor: (n) => n * 10 });
  await assert.rejects(h.run(), /did not finish saving/);
  assert.deepEqual(h.rpcAtPolls, [], "the helper was never asked");
});

test("a frame that never appears is an error, not a result", async () => {
  const h = harness({ sizeFor: () => null });
  await assert.rejects(h.run(), /did not finish saving/);
  assert.deepEqual(h.rpcAtPolls, []);
});

test("a zero-byte frame that stays zero-byte is an error, not a result", async () => {
  const h = harness({ sizeFor: () => 0 });
  await assert.rejects(h.run(), /did not finish saving/);
  assert.deepEqual(h.rpcAtPolls, []);
});
