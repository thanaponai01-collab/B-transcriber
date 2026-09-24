// Owns Adjustment Layer placement gestures, settings storage, and custom preset application.
// Must not know: the DOM, UI panels, Rough Cut or Sync job semantics.

const SETTINGS_KEY = "cutdeck.adj.settings";

const DEFAULT_SETTINGS = {
  frames: 16,
  bin: "CutDeck AL/FX",
  color: "Iris",
  // Default OFF (2026-09-22): transitions always get the full requested 50/50
  // width now that overlapping ones auto-stack onto separate tracks (see
  // timeline/adjustmentLayer.js's lane assignment) instead of overwriting each
  // other — confirmed working on real tight cuts. Clamping to fit a short clip
  // is still available as an opt-in for anyone who'd rather shrink than stack.
  clamp: false,
};

let defaultTimeline;
function getTimeline() {
  if (!defaultTimeline) defaultTimeline = require("../timeline/adjustmentLayer.js");
  return defaultTimeline;
}

let defaultEffects;
function getEffects() {
  if (!defaultEffects) defaultEffects = require("../timeline/effects.js");
  return defaultEffects;
}

function loadSettings(storage) {
  if (!storage) return { ...DEFAULT_SETTINGS };
  try {
    const saved = JSON.parse(storage.getItem(SETTINGS_KEY) || "null");
    return { ...DEFAULT_SETTINGS, ...saved };
  } catch (_) {
    return { ...DEFAULT_SETTINGS };
  }
}

function saveSettings(storage, s) {
  if (!storage) return;
  try {
    storage.setItem(SETTINGS_KEY, JSON.stringify(s));
  } catch (_) {}
}

function describeSequenceMatch(res) {
  if (!res || !res.sequenceWidth || !res.sequenceHeight) return "";
  const created = res.createdAdjustmentLayer
    ? ` (created "${res.createdAdjustmentLayer}" in CutDeck > ADJ & FX)`
    : res.createdColorMatte
      ? ` (created "${res.createdColorMatte}" in CutDeck > ADJ & FX)`
      : "";
  return ` — sequence ${res.sequenceWidth}×${res.sequenceHeight}${created}`;
}

let defaultFrameHold;
function getFrameHold() {
  if (!defaultFrameHold) defaultFrameHold = require("../timeline/frameHold.js");
  return defaultFrameHold;
}

function createAdjustFeature({
  ppro,
  ctl,
  storage = typeof localStorage !== "undefined" ? localStorage : null,
  timeline,
  effects,
  frameHold,
}) {
  function getTl() {
    return timeline || getTimeline();
  }
  function getFx() {
    return effects || getEffects();
  }
  function getFh() {
    return frameHold || getFrameHold();
  }

  function onAdjLayerSequenceName(name) {
    if (!ctl.state.sequence) return;
    ctl.state.sequence = { ...ctl.state.sequence, name };
    ctl.render();
  }

  async function doAdjust(mode) {
    const s = ctl.state.settings || DEFAULT_SETTINGS;
    if (mode === "transition") {
      ctl.setStatus(`Detecting cuts and placing 50/50 transitions (${s.frames}f)…`, "busy");
    } else if (mode === "per_clip") {
      ctl.setStatus("Placing separate Adjustment Layer per clip…", "busy");
    } else {
      ctl.setStatus("Spanning Adjustment Layer over selection…", "busy");
    }

    const res = await getTl().placeAdjustmentLayersOnTimeline(ppro, {
      mode,
      frames: s.frames,
      clamp: s.clamp !== false,
      color: s.color,
      onSequenceName: onAdjLayerSequenceName,
    });

    const seqNote = describeSequenceMatch(res);
    let msg = "";
    if (mode === "transition") {
      msg = res.placedCount > 1
        ? `Added ${res.placedCount} cut transition ALs (${s.frames}f 50/50) on V${res.targetTrack}${seqNote}!`
        : `Placed 50/50 cut transition (${res.frames}f) on V${res.targetTrack}${seqNote}!`;
    } else if (mode === "per_clip") {
      msg = res.placedCount > 1
        ? `Added ${res.placedCount} separate Adjustment Layers (1 per clip) on V${res.targetTrack}${seqNote}!`
        : `Fitted Adjustment Layer over clip on V${res.targetTrack}${seqNote}!`;
    } else {
      msg = res.selectedCount > 1
        ? `Spanned ${res.selectedCount} selected clips with 1 Adjustment Layer on V${res.targetTrack}${seqNote}!`
        : `Fitted Adjustment Layer on V${res.targetTrack}${seqNote}!`;
    }
    ctl.setStatus(msg, "ready");
  }

  async function doColorMatte(mode) {
    const s = ctl.state.settings || DEFAULT_SETTINGS;
    if (mode === "transition") {
      ctl.setStatus(`Detecting cuts and placing 50/50 Color Mattes (${s.frames}f)…`, "busy");
    } else if (mode === "per_clip") {
      ctl.setStatus("Placing separate Color Matte per clip…", "busy");
    } else {
      ctl.setStatus("Spanning Color Matte over selection…", "busy");
    }

    const res = await getTl().placeColorMattesOnTimeline(ppro, {
      mode,
      frames: s.frames,
      clamp: s.clamp !== false,
      color: s.color,
      onSequenceName: onAdjLayerSequenceName,
    });

    const seqNote = describeSequenceMatch(res);
    let msg = "";
    if (mode === "transition") {
      msg = res.placedCount > 1
        ? `Added ${res.placedCount} cut transition Color Mattes (${s.frames}f 50/50) on V${res.targetTrack}${seqNote}!`
        : `Placed 50/50 cut transition Color Matte (${res.frames}f) on V${res.targetTrack}${seqNote}!`;
    } else if (mode === "per_clip") {
      msg = res.placedCount > 1
        ? `Added ${res.placedCount} separate Color Mattes (1 per clip) on V${res.targetTrack}${seqNote}!`
        : `Fitted Color Matte over clip on V${res.targetTrack}${seqNote}!`;
    } else {
      msg = res.selectedCount > 1
        ? `Spanned ${res.selectedCount} selected clips with 1 Color Matte on V${res.targetTrack}${seqNote}!`
        : `Fitted Color Matte on V${res.targetTrack}${seqNote}!`;
    }
    ctl.setStatus(msg, "ready");
  }

  async function doAddFrameHold() {
    ctl.setStatus("Adding Frame Hold at playhead…", "busy");
    const res = await getFh().addFrameHold(ppro);
    ctl.setStatus(`Placed Frame Hold on V${res.targetTrack} (${res.holdSecs}s hold, original clip untouched)!`, "ready");
  }

  async function doApplyPreset(presetId, mode) {
    const customPresets = ctl.state.customPresets || [];
    const preset = customPresets.find((p) => p.id === presetId);
    if (!preset) throw new Error("This preset could not be found — it may have been deleted.");
    const s = ctl.state.settings || DEFAULT_SETTINGS;

    const modeLabel = mode === "transition" ? "cut transition" : mode === "per_clip" ? "per clip" : "span";
    ctl.setStatus(`Placing AL for [${preset.name}] (${modeLabel})…`, "busy");
    const res = await getTl().placeAdjustmentLayersOnTimeline(ppro, {
      mode,
      frames: s.frames,
      clamp: s.clamp !== false,
      color: s.color,
      effectName: preset.name,
      onSequenceName: onAdjLayerSequenceName,
    });

    ctl.setStatus(`Applying [${preset.name}] to ${res.placedItems.length} AL(s)…`, "busy");
    const project = await ppro.Project.getActiveProject();
    // One transaction per phase across every AL: at most 5 Ctrl+Z, not 5 per AL.
    const { warnings } = await getFx().applyCapturedPresetToAll(ppro, project, res.placedItems, preset);
    const appliedCount = res.placedItems.length;

    const done = `Applied [${preset.name}] to ${appliedCount} AL(s) on V${res.targetTrack}${describeSequenceMatch(res)}`;
    if (warnings.length) {
      ctl.setStatus(`${done}, but ${warnings.length} thing(s) didn't land as captured:\n${warnings.slice(0, 6).join("\n")}`, "error");
    } else {
      ctl.setStatus(`${done}!`, "ready");
    }
  }

  function applySettingChange(patch) {
    if (!patch || typeof patch !== "object") return;
    if (Object.prototype.hasOwnProperty.call(patch, "audioTrack")) {
      ctl.state.audioTrack = patch.audioTrack;
    }
    const settingKeys = ["frames", "bin", "color", "clamp"];
    let changedSettings = false;
    const nextSettings = { ...(ctl.state.settings || DEFAULT_SETTINGS) };
    for (const key of settingKeys) {
      if (Object.prototype.hasOwnProperty.call(patch, key)) {
        nextSettings[key] = patch[key];
        changedSettings = true;
      }
    }
    if (changedSettings) {
      ctl.state.settings = nextSettings;
      saveSettings(storage, ctl.state.settings);
    }
    if (patch.statusText) {
      ctl.state.status = { text: patch.statusText, level: "ready" };
    }
    ctl.render();
  }

  return {
    onAdjust: (mode) => ctl.act(() => doAdjust(mode)),
    onColorMatte: (mode) => ctl.act(() => doColorMatte(mode)),
    onAddFrameHold: () => ctl.act(() => doAddFrameHold()),
    onApplyPreset: (presetId, mode) => ctl.act(() => doApplyPreset(presetId, mode)),
    onSettingChange: (patch) => applySettingChange(patch),
    doAdjust,
    doColorMatte,
    doAddFrameHold,
    doApplyPreset,
    applySettingChange,
  };
}

module.exports = {
  createAdjustFeature,
  loadSettings,
  saveSettings,
  DEFAULT_SETTINGS,
  SETTINGS_KEY,
};
