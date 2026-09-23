const test = require("node:test");
const assert = require("node:assert/strict");
const {
  createPresetsFeature,
  loadCustomPresets,
  FX_PRESETS_KEY,
} = require("../uxp/cutdeck/features/presets.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");

function createMockStorage(initial = {}) {
  const store = new Map(Object.entries(initial));
  return {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  };
}

test("presets: loadCustomPresets reads array or defaults to empty", () => {
  const emptyStorage = createMockStorage();
  assert.deepEqual(loadCustomPresets(emptyStorage), []);

  const populated = createMockStorage({
    [FX_PRESETS_KEY]: JSON.stringify([{ id: "fx-1", name: "Blur" }]),
  });
  assert.deepEqual(loadCustomPresets(populated), [{ id: "fx-1", name: "Blur" }]);
});

test("presets: onRemovePreset and onRenamePreset update presetStore and status", async () => {
  const ctl = createController({
    render: () => {},
    initialState: {
      customPresets: [
        { id: "fx-1", name: "Zoom In" },
        { id: "fx-2", name: "Glow" },
      ],
    },
  });

  const removedIds = [];
  const renames = [];
  const fakeStore = {
    path: "/presets",
    remove: async (id) => {
      removedIds.push(id);
      return [{ id: "fx-2", name: "Glow" }];
    },
    rename: async (id, name) => {
      renames.push({ id, name });
      return [{ id: "fx-2", name }];
    },
  };

  const presets = createPresetsFeature({ ppro: {}, ctl, presetStore: fakeStore });

  await presets.onRemovePreset("fx-1");
  assert.deepEqual(removedIds, ["fx-1"]);
  assert.deepEqual(ctl.state.customPresets, [{ id: "fx-2", name: "Glow" }]);
  assert.match(ctl.state.status.text, /Removed "Zoom In"/);

  await presets.onRenamePreset("fx-2", "Super Glow");
  assert.deepEqual(renames, [{ id: "fx-2", name: "Super Glow" }]);
  assert.deepEqual(ctl.state.customPresets, [{ id: "fx-2", name: "Super Glow" }]);
  assert.match(ctl.state.status.text, /Renamed to "Super Glow"/);
});

test("presets: onChoosePresetFolder updates folder and presets", async () => {
  const ctl = createController({ render: () => {} });
  const fakeStore = {
    path: "D:\\CutDeckPresets",
    chooseFolder: async () => ({
      path: "D:\\CutDeckPresets",
      presets: [{ id: "fx-3", name: "Vignette" }],
    }),
  };

  const presets = createPresetsFeature({ ppro: {}, ctl, presetStore: fakeStore });
  await presets.onChoosePresetFolder();

  assert.deepEqual(ctl.state.customPresets, [{ id: "fx-3", name: "Vignette" }]);
  assert.equal(ctl.state.presetFile.path, "D:\\CutDeckPresets");
  assert.match(ctl.state.status.text, /Presets now saved to D:\\CutDeckPresets/);
});

test("presets: onCapturePreset validates name", async () => {
  const ctl = createController({ render: () => {} });
  const presets = createPresetsFeature({ ppro: {}, ctl, presetStore: {} });

  await presets.onCapturePreset("");
  assert.equal(ctl.state.status.level, "error");
  assert.match(ctl.state.status.text, /Name this preset first/);
});
