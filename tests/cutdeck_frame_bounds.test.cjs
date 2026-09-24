/* transform/frameBounds.js: measures where a clip is drawn by saving the frame with it on and
   off. The fake host behaves like the real one (live 2026-09-24): exportSequenceFrame resolves at
   once and the frame is drawn LATER, from the timeline as it is then. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fake = require("./fakes/premiere.cjs");
const { measureDrawnBounds } = require("../uxp/cutdeck/transform/frameBounds.js");

const WAIT = { timeoutMs: 200, intervalMs: 1 };

function setup({ playhead = 50, failSecondSave = false, neverWrite = false, startDisabled = false } = {}) {
  const { project, undoSteps } = fake.createProject();
  let disabled = startDisabled;
  const item = {
    isDisabled: () => Promise.resolve(disabled),
    getStartTime: () => Promise.resolve(fake.tickTime(10)),
    getEndTime: () => Promise.resolve(fake.tickTime(100)),
    createSetDisabledAction: (d) => fake.action(() => { disabled = d; }),
  };
  const seq = { getPlayerPosition: () => Promise.resolve(fake.tickTime(playhead)) };
  const written = [];
  const pending = [];
  const ppro = { Exporter: { exportSequenceFrame: (s, t, name) => {
    if (failSecondSave && written.length + pending.length === 1) return Promise.reject(new Error("export failed"));
    if (!neverWrite) pending.push(name);
    return Promise.resolve(true);
  } } };
  const getEntry = (n) => {
    const i = pending.indexOf(n);
    if (i !== -1) { pending.splice(i, 1); written.push({ name: n, hidden: disabled }); }
    return Promise.resolve(written.some((w) => w.name === n) ? { getMetadata: () => Promise.resolve({ size: 99 }) } : null);
  };
  const uxp = { storage: { localFileSystem: { getTemporaryFolder: () => Promise.resolve({ nativePath: "C:\\Temp\\PluginData", getEntry }) } } };
  const requests = [];
  const rpc = (req) => { requests.push(req); return Promise.resolve({ bounds: { left: 11, top: 904, right: 429, bottom: 991 } }); };
  const run = () => measureDrawnBounds({ ppro, project, seq, item, frame: { width: 1920, height: 1080 }, rpc, uxp, wait: WAIT });
  return { run, undoSteps, written, requests, isDisabled: () => disabled };
}

test("saves the frame with the clip on, then off, switches it back on, and asks the helper for the box", async () => {
  const h = setup();
  assert.deepEqual(await h.run(), { left: 11, top: 904, right: 429, bottom: 991 });
  assert.deepEqual(h.written.map((w) => w.hidden), [false, true]);
  assert.equal(h.isDisabled(), false);
  assert.deepEqual(h.undoSteps, ["CutDeck: measure (hide clip)", "CutDeck: measure (show clip)"]);
  assert.equal(h.requests.length, 1);
  assert.equal(h.requests[0].type, "frame_bounds");
  assert.match(h.requests[0].on, /^C:\\Temp\\PluginData\\cutdeck-bounds-.*-on\.png$/);
  assert.match(h.requests[0].off, /-off\.png$/);
});

test("refuses when the playhead is not over the clip, touching nothing", async () => {
  for (const playhead of [5, 100]) {
    const h = setup({ playhead });
    await assert.rejects(h.run(), /playhead over it/);
    assert.deepEqual(h.undoSteps, []);
  }
});

test("a failed second save still switches the clip back on", async () => {
  const h = setup({ failSecondSave: true });
  await assert.rejects(h.run(), /export failed/);
  assert.equal(h.isDisabled(), false);
  assert.equal(h.requests.length, 0);
});

test("if the first frame is never written, the clip is never switched off", async () => {
  const h = setup({ neverWrite: true });
  await assert.rejects(h.run(), /did not finish saving/);
  assert.deepEqual(h.undoSteps, []);
});

test("a clip that is already switched off is refused and left off", async () => {
  const h = setup({ startDisabled: true });
  await assert.rejects(h.run(), /switched off on the timeline/);
  assert.equal(h.isDisabled(), true);
  assert.deepEqual(h.undoSteps, []);
});
