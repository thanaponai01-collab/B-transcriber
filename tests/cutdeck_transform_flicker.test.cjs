/* Tests verifying that the Transform panel does not flicker, disable/enable clips on the timeline,
   or thrash the host with redundant component chain reads. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fake = require("./fakes/premiere.cjs");
const { measureDrawnBounds, getCachedBounds, setCachedBounds } = require("../uxp/cutdeck/transform/frameBounds.js");

const WAIT = { timeoutMs: 200, intervalMs: 1 };

test("measureDrawnBounds isolates via track muting without disabling clip on timeline", async () => {
  const { project, undoSteps } = fake.createProject();
  let disabledCalls = [];
  let disabledState = false;
  const item = {
    isDisabled: () => Promise.resolve(disabledState),
    getStartTime: () => Promise.resolve(fake.tickTime(10)),
    getEndTime: () => Promise.resolve(fake.tickTime(100)),
    getTrackIndex: () => Promise.resolve(1), // on track 1 (footage on track 0)
    createSetDisabledAction: (d) => {
      disabledCalls.push(d);
      return fake.action(() => { disabledState = d; });
    },
  };

  let track0Muted = false;
  let track1Muted = false;
  const track0 = {
    isMuted: () => Promise.resolve(track0Muted),
    setMute: (m) => { track0Muted = m; return Promise.resolve(true); },
    getTrackItems: () => Promise.resolve([{
      isDisabled: () => Promise.resolve(false),
      getStartTime: () => Promise.resolve(fake.tickTime(0)),
      getEndTime: () => Promise.resolve(fake.tickTime(200)),
    }]),
  };
  const track1 = {
    isMuted: () => Promise.resolve(track1Muted),
    setMute: (m) => { track1Muted = m; return Promise.resolve(true); },
    getTrackItems: () => Promise.resolve([item]),
  };

  const seq = {
    getPlayerPosition: () => Promise.resolve(fake.tickTime(50)),
    getVideoTrackCount: () => Promise.resolve(2),
    getVideoTrack: (t) => Promise.resolve(t === 0 ? track0 : track1),
  };

  const written = [];
  const ppro = {
    Exporter: {
      exportSequenceFrame: (s, t, name) => {
        written.push(name);
        return Promise.resolve(true);
      },
    },
  };
  const getEntry = (n) => Promise.resolve({
    getMetadata: () => Promise.resolve({ size: 99 }),
    delete: () => Promise.resolve(true),
  });
  const uxp = { storage: { localFileSystem: { getTemporaryFolder: () => Promise.resolve({ nativePath: "C:\\Temp\\PluginData", getEntry }) } } };
  const requests = [];
  const rpc = (req) => {
    requests.push(req);
    return Promise.resolve({ bounds: { left: 11, top: 904, right: 429, bottom: 991 } });
  };

  const res = await measureDrawnBounds({ ppro, project, seq, item, frame: { width: 1920, height: 1080 }, rpc, uxp, wait: WAIT, keepDisabled: true });

  assert.equal(disabledCalls.length, 0, `Expected 0 calls to createSetDisabledAction, but got: ${JSON.stringify(disabledCalls)}`);
  assert.equal(undoSteps.length, 0, `Expected 0 undo steps burned for measurement, but got: ${JSON.stringify(undoSteps)}`);
  assert.equal(written.length, 1, `Expected only 1 frame export (single frame), but got ${written.length}`);
  assert.equal(track0Muted, false, "Track 0 must be restored to unmuted");
});

test("getCachedBounds retains cached bounds across floating point precision variations", () => {
  const item = {};
  setCachedBounds(item, { left: 10, top: 20, right: 100, bottom: 200 }, 100, 0, "0:100", { x: 0.27910, y: 0.50000 });

  // Floating point precision difference of 0.0002 (~0.3px in 1080p) between written and readback
  const cached = getCachedBounds(item, 100, 0, "0:100", { x: 0.27930, y: 0.50000 });
  assert.notEqual(cached, null, "Bounds cache should hit even with minor subpixel precision difference");
});

test("readAlignTransform inspects component chain only once per item", async () => {
  const { readAlignTransform } = require("../uxp/cutdeck/features/align.js");
  let chainCalls = 0;
  const item = {
    getName: async () => "Title",
    getIsSelected: async () => true,
    getProjectItem: async () => null,
    getComponentChain: async () => {
      chainCalls++;
      return {
        getComponentCount: () => 3,
        getComponentAtIndex: (i) => ({
          getMatchName: async () => ["AE.ADBE Motion", "AE.ADBE Graphic Group", "AE.ADBE Text"][i],
          getParam: (p) => ({
            getStartValue: async () => ({ value: { value: p === 2 ? [0.2, 0.3] : (p === 8 ? [0.2, 0.3] : 100) } }),
            isTimeVarying: async () => false,
          }),
        }),
      };
    },
  };
  const seq = {
    getSelection: async () => ({ getTrackItems: async () => [item] }),
    getSettings: async () => ({ getVideoFrameRect: async () => ({ width: 1920, height: 1080 }) }),
  };
  const ppro = {
    Metadata: { getProjectColumnsMetadata: async () => "[]" },
  };

  const state = await readAlignTransform(seq, ppro);
  assert.equal(state.available, true);
  assert.ok(chainCalls <= 1, `getComponentChain called ${chainCalls} times for a single item! Must be <= 1 for efficiency`);
});
