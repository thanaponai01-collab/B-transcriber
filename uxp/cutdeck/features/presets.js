// Owns custom preset loading, creation (capture), folder linking, renaming, and removal.
// Must not know: the DOM, UI panels, Adjustment Layer placement math.

const { activeProjectAndSequence } = require("../host/project.js");
const effects = require("../timeline/effects.js");
const { CACHE_KEY: FX_PRESETS_KEY } = require("../presetStore.js");

function loadCustomPresets(storage) {
  if (!storage) return [];
  try {
    const saved = JSON.parse(storage.getItem(FX_PRESETS_KEY) || "null");
    return Array.isArray(saved) ? saved : [];
  } catch (_) {
    return [];
  }
}

function createPresetsFeature({
  ppro,
  ctl,
  presetStore,
  storage = typeof localStorage !== "undefined" ? localStorage : null,
}) {
  async function editPresets(op) {
    ctl.state.customPresets = await op;
    ctl.state.presetFile = { path: presetStore ? presetStore.path : null, error: null };
  }

  async function loadPresets() {
    if (!presetStore) return;
    const res = await presetStore.load();
    ctl.state.customPresets = res.presets;
    ctl.state.presetFile = { path: res.path, error: res.error };
    if (res.error) ctl.setStatus(`Presets: ${res.error}`, "error");
    else ctl.render();
  }

  async function doChoosePresetFolder() {
    if (!presetStore) return;
    const res = await presetStore.chooseFolder();
    if (!res) return;
    ctl.state.customPresets = res.presets;
    ctl.state.presetFile = { path: res.path, error: null };
    ctl.setStatus(`Presets now saved to ${res.path}. Choose the same synced folder on your other machines to share them.`, "ready");
  }

  async function doRemovePreset(presetId) {
    const customPresets = ctl.state.customPresets || [];
    const preset = customPresets.find((p) => p.id === presetId);
    if (presetStore) await editPresets(presetStore.remove(presetId));
    ctl.setStatus(preset ? `Removed "${preset.name}".` : "Removed.", "ready");
  }

  async function doRenamePreset(presetId, name) {
    const customPresets = ctl.state.customPresets || [];
    if (!customPresets.some((p) => p.id === presetId)) return;
    if (presetStore) await editPresets(presetStore.rename(presetId, name));
    ctl.setStatus(`Renamed to "${name}".`, "ready");
  }

  async function doCapturePreset(nameOrPayload) {
    const label = ((typeof nameOrPayload === "string" ? nameOrPayload : (nameOrPayload && nameOrPayload.name)) || "").trim();
    if (!label) throw new Error("Name this preset first (the field next to Capture), then click Capture.");

    const { sequence: seq } = await activeProjectAndSequence(ppro);
    const item = await effects.getFirstSelectedTrackItem(seq);
    if (!item) {
      throw new Error("Select the clip or Adjustment Layer whose effects you want to capture, then click Capture.");
    }

    const captured = await effects.captureEffectFromTrackItem(ppro, item);
    console.log("CutDeck captured preset:", JSON.stringify(captured, null, 2));
    const id = `fx-${Date.now().toString(36)}`;
    const preset = { id, name: label, components: captured.components };
    if (presetStore) await editPresets(presetStore.add(preset));
    ctl.render();

    const names = captured.components.map((c) => c.displayName || c.matchName).join(", ");
    const animatedNote = captured.animatedCount
      ? ` ${captured.animatedCount} keyframed param${captured.animatedCount === 1 ? "" : "s"} included.`
      : "";
    ctl.setStatus(
      `Captured "${label}" — ${captured.components.length} effect${captured.components.length === 1 ? "" : "s"}: ${names}.${animatedNote}`,
      "ready"
    );
  }

  return {
    onCapturePreset: (name) => ctl.act(() => doCapturePreset(name)),
    onRemovePreset: (presetId) => ctl.act(() => doRemovePreset(presetId)),
    onRenamePreset: (presetId, name) => ctl.act(() => doRenamePreset(presetId, name)),
    onChoosePresetFolder: () => ctl.act(doChoosePresetFolder),
    loadPresets,
    doCapturePreset,
    doRemovePreset,
    doRenamePreset,
    doChoosePresetFolder,
  };
}

module.exports = {
  createPresetsFeature,
  loadCustomPresets,
  FX_PRESETS_KEY,
};
