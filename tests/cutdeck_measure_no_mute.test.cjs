/* Measuring a text Graphic must not black out the Program Monitor (user report 2026-10-19: the
   anchor "flickers black, like it disabled the tracks"). The measure switches off only the
   Graphic itself for the second frame save, never mutes another track, and the clip is back on
   before the helper is asked. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fake = require("./fakes/premiere.cjs");
const { measureDrawnBounds } = require("../uxp/cutdeck/transform/frameBounds.js");

const WAIT = { timeoutMs: 200, intervalMs: 1 };
const BOUNDS = { left: 11, top: 904, right: 429, bottom: 991 };

function harness({ below = false, above = false } = {}) {
  const { project, undoSteps } = fake.createProject();
  let disabled = false;
  const item = {
    isDisabled: () => Promise.resolve(disabled),
    getStartTime: () => Promise.resolve(fake.tickTime(10)),
    getEndTime: () => Promise.resolve(fake.tickTime(100)),
    getTrackIndex: () => Promise.resolve(1),
    createSetDisabledAction: (d) => fake.action(() => { disabled = d; }),
  };
  const muteCalls = [];
  const clipTrack = (has) => ({
    isMuted: () => Promise.resolve(false),
    setMute: (m) => { muteCalls.push(m); return Promise.resolve(true); },
    getTrackItems: () => Promise.resolve(has ? [{
      isDisabled: () => Promise.resolve(false),
      getStartTime: () => Promise.resolve(fake.tickTime(0)),
      getEndTime: () => Promise.resolve(fake.tickTime(200)),
    }] : []),
  });
  const tracks = [clipTrack(below), clipTrack(false), clipTrack(above)];
  tracks[1].getTrackItems = () => Promise.resolve([item]);
  const seq = {
    getPlayerPosition: () => Promise.resolve(fake.tickTime(50)),
    getVideoTrackCount: () => Promise.resolve(3),
    getVideoTrack: (t) => Promise.resolve(tracks[t]),
  };
  const saved = [];
  const ppro = { Exporter: { exportSequenceFrame: (s, t, name) => { saved.push({ name, disabled }); return Promise.resolve(true); } } };
  const getEntry = () => Promise.resolve({ getMetadata: () => Promise.resolve({ size: 99 }), delete: () => Promise.resolve(true) });
  const uxp = { storage: { localFileSystem: { getTemporaryFolder: () => Promise.resolve({ nativePath: "C:\\Temp\\PluginData", getEntry }) } } };
  const requests = [];
  const rpc = (req) => { requests.push({ req, disabled }); return Promise.resolve({ bounds: BOUNDS }); };
  const run = () => measureDrawnBounds({ ppro, project, seq, item, frame: { width: 1920, height: 1080 }, rpc, uxp, wait: WAIT });
  return { run, muteCalls, saved, requests, undoSteps, isDisabled: () => disabled };
}

for (const [label, opts] of [["video underneath", { below: true }], ["a clip above", { above: true }], ["clips above and below", { below: true, above: true }]]) {
  test(`with ${label}: no track is muted; only the Graphic is off for the second save`, async () => {
    const h = harness(opts);
    assert.deepEqual(await h.run(), BOUNDS);
    assert.deepEqual(h.muteCalls, [], "no track muted, so the monitor never goes black");
    assert.deepEqual(h.saved.map((s) => s.disabled), [false, true], "clip on, then only the clip off");
    assert.equal(h.isDisabled(), false, "clip switched back on");
    assert.equal(h.requests.length, 1);
    assert.equal(h.requests[0].disabled, false, "clip back on before the helper is asked");
    assert.ok(h.requests[0].req.off, "the helper diffs the two frames");
    assert.equal(h.undoSteps.length, 2, "hide + show, nothing else");
  });
}

test("nothing above or below: one save, nothing switched off or muted", async () => {
  const h = harness();
  assert.deepEqual(await h.run(), BOUNDS);
  assert.deepEqual(h.muteCalls, []);
  assert.equal(h.saved.length, 1);
  assert.equal(h.undoSteps.length, 0);
  assert.equal(h.requests[0].req.off, undefined);
});
