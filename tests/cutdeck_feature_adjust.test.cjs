const test = require("node:test");
const assert = require("node:assert/strict");
const {
  createAdjustFeature,
  loadSettings,
  saveSettings,
  DEFAULT_SETTINGS,
  SETTINGS_KEY,
} = require("../uxp/cutdeck/features/adjust.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");

function createMockStorage(initial = {}) {
  const store = new Map(Object.entries(initial));
  return {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
}

test("adjust: loadSettings loads defaults or merges saved JSON", () => {
  const emptyStorage = createMockStorage();
  assert.deepEqual(loadSettings(emptyStorage), DEFAULT_SETTINGS);

  const customStorage = createMockStorage({
    [SETTINGS_KEY]: JSON.stringify({ frames: 24, color: "Cerulean" }),
  });
  const merged = loadSettings(customStorage);
  assert.equal(merged.frames, 24);
  assert.equal(merged.color, "Cerulean");
  assert.equal(merged.clamp, false);
});

test("adjust: applySettingChange updates state and persists settings", () => {
  const storage = createMockStorage();
  const ctl = createController({
    render: () => {},
    initialState: { settings: { ...DEFAULT_SETTINGS }, audioTrack: null },
  });

  const adjust = createAdjustFeature({ ppro: {}, ctl, storage });

  adjust.applySettingChange({ frames: 30, color: "Mango", audioTrack: 2, statusText: "Settings updated" });

  assert.equal(ctl.state.settings.frames, 30);
  assert.equal(ctl.state.settings.color, "Mango");
  assert.equal(ctl.state.audioTrack, 2);
  assert.deepEqual(ctl.state.status, { text: "Settings updated", level: "ready" });

  const saved = JSON.parse(storage.getItem(SETTINGS_KEY));
  assert.equal(saved.frames, 30);
  assert.equal(saved.color, "Mango");
});

test("adjust: onAdjust invokes placeAdjustmentLayersOnTimeline and updates status", async () => {
  const ctl = createController({
    render: () => {},
    initialState: { settings: { frames: 16, clamp: false, color: "Iris" } },
  });

  let placeArgs = null;
  const fakeTimeline = {
    placeAdjustmentLayersOnTimeline: async (ppro, opts) => {
      placeArgs = opts;
      return {
        placedCount: 2,
        targetTrack: 3,
        sequenceWidth: 1920,
        sequenceHeight: 1080,
      };
    },
  };

  const adjust = createAdjustFeature({ ppro: {}, ctl, timeline: fakeTimeline });
  await adjust.onAdjust("transition");

  assert.equal(placeArgs.mode, "transition");
  assert.equal(placeArgs.frames, 16);
  assert.equal(ctl.state.status.level, "ready");
  assert.match(ctl.state.status.text, /Added 2 cut transition ALs \(16f 50\/50\) on V3/);
});

test("adjust: onApplyPreset throws if preset id is not found", async () => {
  const ctl = createController({
    render: () => {},
    initialState: { customPresets: [] },
  });

  const adjust = createAdjustFeature({ ppro: {}, ctl, timeline: {} });
  await adjust.onApplyPreset("nonexistent-id", "span");

  assert.equal(ctl.state.status.level, "error");
  assert.match(ctl.state.status.text, /This preset could not be found/);
});
