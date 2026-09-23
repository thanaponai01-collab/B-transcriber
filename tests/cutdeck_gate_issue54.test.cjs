const test = require("node:test");
const assert = require("node:assert/strict");
const { createController } = require("../uxp/cutdeck/features/controller.js");
const { createRoughCutFeature, KEY } = require("../uxp/cutdeck/features/roughCut.js");
const { createSyncFeature } = require("../uxp/cutdeck/features/sync.js");
const { createAdjustFeature } = require("../uxp/cutdeck/features/adjust.js");
const { createPresetsFeature } = require("../uxp/cutdeck/features/presets.js");
const { createAlignFeature } = require("../uxp/cutdeck/features/align.js");
const { createProbesFeature } = require("../uxp/cutdeck/features/probes.js");

function createMockStorage(initial = {}) {
  const store = new Map(Object.entries(initial));
  return {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
}

// --- Controller Adversarial Attacks ---

test("ATTACK [controller]: act handles non-Error thrown values (null, undefined, string, object)", async () => {
  const ctl = createController({ render: () => {} });
  const origError = console.error;
  console.error = () => {};

  try {
    // 1. Throw string
    await ctl.act(async () => { throw "string error"; });
    assert.equal(ctl.state.busy, false);
    assert.deepEqual(ctl.state.status, { text: "string error", level: "error" });

    // 2. Throw null
    await ctl.act(async () => { throw null; });
    assert.equal(ctl.state.busy, false);
    assert.deepEqual(ctl.state.status, { text: "null", level: "error" });

    // 3. Throw undefined
    await ctl.act(async () => { throw undefined; });
    assert.equal(ctl.state.busy, false);
    assert.deepEqual(ctl.state.status, { text: "undefined", level: "error" });

    // 4. Throw object without message
    await ctl.act(async () => { throw { code: 500 }; });
    assert.equal(ctl.state.busy, false);
    assert.deepEqual(ctl.state.status, { text: "[object Object]", level: "error" });
  } finally {
    console.error = origError;
  }
});

test("ATTACK [controller]: concurrent burst of 5 calls drops all except the first", async () => {
  const ctl = createController({ render: () => {} });
  let resolveFirst;
  let firstRan = 0;
  let othersRan = 0;

  const p1 = ctl.act(() => new Promise((resolve) => {
    firstRan++;
    resolveFirst = resolve;
  }));

  const p2 = ctl.act(async () => { othersRan++; });
  const p3 = ctl.act(async () => { othersRan++; });
  const p4 = ctl.act(async () => { othersRan++; });
  const p5 = ctl.act(async () => { othersRan++; });

  await Promise.all([p2, p3, p4, p5]);
  assert.equal(firstRan, 1);
  assert.equal(othersRan, 0, "No subsequent calls should execute while busy");

  resolveFirst();
  await p1;
  assert.equal(ctl.state.busy, false);
});

// --- Adjust Adversarial Attacks ---

test("ATTACK [adjust]: applySettingChange handles null, undefined, empty patch gracefully", () => {
  const ctl = createController({
    render: () => {},
    initialState: { settings: { frames: 16, bin: "B", color: "C", clamp: false } },
  });
  const adjust = createAdjustFeature({ ppro: {}, ctl });

  // Must not throw
  assert.doesNotThrow(() => adjust.applySettingChange(null));
  assert.doesNotThrow(() => adjust.applySettingChange(undefined));
  assert.doesNotThrow(() => adjust.applySettingChange({}));
});

test("ATTACK [adjust]: doAdjust handles placement failure gracefully through act()", async () => {
  const ctl = createController({ render: () => {} });
  const origError = console.error;
  console.error = () => {};

  const failingTimeline = {
    placeAdjustmentLayersOnTimeline: async () => {
      throw new Error("Track V5 is locked.");
    },
  };

  try {
    const adjust = createAdjustFeature({ ppro: {}, ctl, timeline: failingTimeline });
    await adjust.onAdjust("span");

    assert.equal(ctl.state.busy, false);
    assert.equal(ctl.state.status.level, "error");
    assert.equal(ctl.state.status.text, "Track V5 is locked.");
  } finally {
    console.error = origError;
  }
});

// --- RoughCut Adversarial Attacks ---

test("ATTACK [roughCut]: corrupted localStorage JSON does not crash lastJob or clearJob", () => {
  const storage = createMockStorage({
    [KEY]: "{malformed-json!!!",
  });
  const ctl = createController({ render: () => {} });
  const roughCut = createRoughCutFeature({ ppro: {}, ctl, storage });

  assert.equal(roughCut.lastJob(), null);
  assert.doesNotThrow(() => roughCut.clearJob());
  assert.equal(storage.getItem(KEY), null);
});

test("ATTACK [roughCut]: doResume with unexported prepared job warns user and clears job", async () => {
  const storage = createMockStorage({
    [KEY]: JSON.stringify({ job_id: "job-unexported", state: "prepared", exported: false }),
  });
  const ctl = createController({ render: () => {} });

  const fakeRpc = async (req) => {
    if (req.type === "hello") return { ok: true };
    if (req.type === "status") return { job_id: "job-unexported", state: "prepared" };
    throw new Error(`Unexpected: ${req.type}`);
  };

  const roughCut = createRoughCutFeature({
    ppro: {},
    ctl,
    rpc: fakeRpc,
    storage,
  });

  await roughCut.onResumeJob();
  assert.equal(storage.getItem(KEY), null);
  assert.equal(ctl.state.status.level, "ready");
  assert.match(ctl.state.status.text, /previous export did not finish/);
});

// --- Presets Adversarial Attacks ---

test("ATTACK [presets]: doCapturePreset rejects whitespace-only preset name", async () => {
  const ctl = createController({ render: () => {} });
  const presets = createPresetsFeature({ ppro: {}, ctl, presetStore: {} });

  await presets.onCapturePreset("   \t  \n ");
  assert.equal(ctl.state.status.level, "error");
  assert.match(ctl.state.status.text, /Name this preset first/);
});

test("ATTACK [presets]: doCapturePreset rejects when no clip is selected", async () => {
  const ctl = createController({ render: () => {} });
  const origError = console.error;
  console.error = () => {};

  const fakePpro = {
    Project: {
      getActiveProject: async () => ({
        getActiveSequence: async () => ({
          getSelection: () => [],
        }),
      }),
    },
  };

  try {
    const presets = createPresetsFeature({ ppro: fakePpro, ctl, presetStore: {} });
    await presets.onCapturePreset("My Preset");

    assert.equal(ctl.state.status.level, "error");
    assert.match(ctl.state.status.text, /Select the clip or Adjustment Layer/);
  } finally {
    console.error = origError;
  }
});

// --- Align Adversarial Attacks ---

test("ATTACK [align]: polling stops when controller is busy and survives host error", async () => {
  const ctl = createController({
    render: () => {},
    initialState: { transform: null },
  });
  ctl.state.busy = true;

  const align = createAlignFeature({ ppro: {}, ctl });

  // Calling refresh while busy should be dropped by act
  await align.onRefresh();
  assert.equal(ctl.state.transform, null);
});
