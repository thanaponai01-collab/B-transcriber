const ppro = require("premierepro");
const workflow = require("./workflow.js");
const { createRpc } = require("./core/rpc.js");
const { progressText } = require("./core/progressText.js");
const probe = require("./probe.js");
const capability = require("./capabilityProbe.js");
const helperStart = require("./helperStart.js");
const panel = require("./core/panel.js");
const timeline = require("./timeline/adjustmentLayer.js");
const effects = require("./timeline/effects.js");

const KEY = "cutdeck.xml.lastJob";
const SETTINGS_KEY = "cutdeck.adj.settings";
// Custom effect presets get their OWN storage key, deliberately not folded into
// cutdeck.adj.settings: saveSettingsToStorage rewrites its entire blob on every minor setting
// change (frame count, color, ...), and a corrupt/oversized preset would otherwise silently
// wipe core settings back to DEFAULT_SETTINGS on the next load (see loadSettingsFromStorage's
// catch below). A separate key isolates both problems.
const FX_PRESETS_KEY = "cutdeck.fx.presets";

const DEFAULT_SETTINGS = {
  frames: 16,
  bin: "CutDeck AL/FX",
  color: "Iris",
  clamp: true
};

// The controller: holds the one state object, calls Premiere and the helper, hands new state
// to panel.render(). Never touches the DOM directly — see core/panel.js and issue #45.
const state = {
  sequence: null,
  tab: "adj",
  cutMode: "protected",
  audioTrack: null,
  settings: loadSettingsFromStorage(),
  customPresets: loadCustomPresets(),
  job: null,
  busy: false,
  status: { text: "Ready", level: "ready" },
};

function loadSettingsFromStorage() {
  try {
    const saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "null");
    return { ...DEFAULT_SETTINGS, ...saved };
  } catch (_) {
    return { ...DEFAULT_SETTINGS };
  }
}
function saveSettingsToStorage(s) {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
  } catch (_) {}
}

function loadCustomPresets() {
  try {
    const saved = JSON.parse(localStorage.getItem(FX_PRESETS_KEY) || "null");
    return Array.isArray(saved) ? saved : [];
  } catch (_) {
    return [];
  }
}
function saveCustomPresets(list) {
  try {
    localStorage.setItem(FX_PRESETS_KEY, JSON.stringify(list));
  } catch (_) {}
}

function lastJob() {
  try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (_) { return null; }
}
function save(job) {
  localStorage.setItem(KEY, JSON.stringify(job));
  state.job = { id: job.job_id, state: job.state };
  panel.render(state);
}
function clearJob() {
  localStorage.removeItem(KEY);
  state.job = null;
  panel.render(state);
}

function setStatus(text, level = "ready") {
  state.status = { text, level };
  panel.render(state);
}

const rpc = createRpc({
  onRetry: (attempt, total) => setStatus(`Connecting to helper… attempt ${attempt} of ${total}.`, "busy"),
});

async function ensureHelper() {
  return helperStart.ensureHelperRunning({
    rpc,
    version: workflow.VERSION,
    onStatus: (msg) => setStatus(msg, "busy"),
  });
}

async function act(fn) {
  if (state.busy) return;
  state.busy = true;
  state.status = { text: "Processing…", level: "busy" };
  panel.render(state);
  try {
    await fn();
    if (state.status.level === "busy") {
      state.status = { text: "Ready", level: "ready" };
    }
  } catch (error) {
    state.status = { text: error.message || String(error), level: "error" };
    console.error(error);
  } finally {
    state.busy = false;
    panel.render(state);
  }
}

async function doRefresh() {
  const snap = await workflow.capture(ppro);
  const count = snap.context.audio_track_count;
  state.sequence = {
    name: snap.context.sequence_name,
    inSeconds: snap.inSeconds,
    outSeconds: snap.outSeconds,
    audioTrackCount: count,
  };
  if (state.audioTrack !== null && state.audioTrack >= count) state.audioTrack = null;
  panel.render(state);
  return snap;
}

async function follow(job) {
  while (job.state === "running") {
    setStatus(progressText(job), "busy");
    await new Promise((resolve) => setTimeout(resolve, 1500));
    job = await rpc({ type: "status", job_id: job.job_id });
  }
  if (job.state === "failed") { clearJob(); setStatus(job.message, "error"); throw new Error(job.message); }
  if (job.state === "no_cuts") { clearJob(); setStatus("No cuts found inside this range. Your sequence is unchanged.", "ready"); return; }
  if (job.state !== "ready") { setStatus("Job error: " + job.state, "error"); throw new Error("Job is not ready: " + job.state); }
  const sync = job.job_type === "sync";
  setStatus(sync ? "Opening synchronized multi-cam sequence…" : "Opening your rough cut in Premiere…", "busy");
  const saved = lastJob() || {};
  await workflow.importResult(ppro, job, saved.importAttempted,
    () => save({ ...saved, ...job, importAttempted: true }));
  clearJob();
  if (sync) {
    const rep = job.report || {};
    const unsynced = rep.unsynced_groups > 0 ? ` ${rep.unsynced_groups} placed at end.` : "";
    setStatus(`Multi-cam sync complete (${rep.synced_groups || 0} angles).${unsynced}\nOpened ${job.result_name}\nSaved ${job.output_path}`, "ready");
    return;
  }
  const note = job.output_note ? `\n${job.output_note}` : "";
  setStatus(`${job.report.cuts_applied} cuts · ${(job.report.removed_ms / 1000).toFixed(1)} seconds removed.`
    + `\nOpened ${job.result_name}\nSaved ${job.output_path}${note}`, "ready");
}

// Keep sequence name up to date on UI while timeline.placeAdjustmentLayersOnTimeline runs.
function onAdjLayerSequenceName(name) {
  if (!state.sequence) return;
  state.sequence = { ...state.sequence, name };
  panel.render(state);
}

// No scaling happens — CutDeck picks whichever Adjustment Layer in CutDeck > ADJ & FX
// already matches this sequence's resolution (see timeline/adjustmentLayer.js's
// pickBestCandidate) and places it at native 100%. This just confirms which sequence it
// detected, so a wrong pick is visible immediately instead of only showing up visually.
function describeSequenceMatch(res) {
  if (!res || !res.sequenceWidth || !res.sequenceHeight) return "";
  return ` — sequence ${res.sequenceWidth}×${res.sequenceHeight}`;
}

async function doAdjust(mode) {
  const s = state.settings;
  if (mode === "transition") {
    setStatus(`Detecting cuts and placing 50/50 transitions (${s.frames}f)…`, "busy");
  } else if (mode === "per_clip") {
    setStatus("Placing separate Adjustment Layer per clip…", "busy");
  } else {
    setStatus("Spanning Adjustment Layer over selection…", "busy");
  }

  const res = await timeline.placeAdjustmentLayersOnTimeline(ppro, {
    mode,
    frames: s.frames,
    clamp: s.clamp !== false,
    color: s.color,
    onSequenceName: onAdjLayerSequenceName
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
  setStatus(msg, "ready");
}

// Each quick-effect button is its own preset, wired to place the Adjustment Layer exactly the
// way the plain Adjust card does (same mode gestures) and then apply that preset's captured
// effect to every AL it just placed — one click does both, same as the original combined
// behavior, just per-preset instead of via a shared "active effect" selector.
async function doApplyPreset(presetId, mode) {
  const preset = state.customPresets.find((p) => p.id === presetId);
  if (!preset) throw new Error("This preset could not be found — it may have been deleted.");
  const s = state.settings;

  const modeLabel = mode === "transition" ? "cut transition" : mode === "per_clip" ? "per clip" : "span";
  setStatus(`Placing AL for [${preset.name}] (${modeLabel})…`, "busy");
  const res = await timeline.placeAdjustmentLayersOnTimeline(ppro, {
    mode,
    frames: s.frames,
    clamp: s.clamp !== false,
    color: s.color,
    effectName: preset.name,
    onSequenceName: onAdjLayerSequenceName
  });

  setStatus(`Applying [${preset.name}] to ${res.placedItems.length} AL(s)…`, "busy");
  const project = await ppro.Project.getActiveProject();
  let appliedCount = 0;
  for (const item of res.placedItems) {
    await effects.applyCapturedPreset(ppro, project, item, preset);
    appliedCount++;
  }

  setStatus(`Applied [${preset.name}] to ${appliedCount} AL(s) on V${res.targetTrack}${describeSequenceMatch(res)}!`, "ready");
}

async function doCut() {
  if (lastJob()) throw new Error("Resume the previous job before starting another rough cut.");
  await ensureHelper();
  const snap = await doRefresh();
  setStatus("Preparing your sequence…", "busy");
  const job = await workflow.prepare(ppro, rpc, snap,
    { audio_track: state.audioTrack, asr: state.cutMode === "protected" }, save);
  await follow(job);
}

async function doSync() {
  if (lastJob()) throw new Error("Resume or dismiss the previous job before starting another operation.");
  await ensureHelper();
  const snap = await doRefresh();
  setStatus("Exporting sequence XML for multi-camera sync…", "busy");
  const job = await workflow.prepareSync(ppro, rpc, snap, { audio_track: state.audioTrack }, save);
  await follow(job);
}

async function doResume() {
  const saved = lastJob();
  if (!saved) return;
  await ensureHelper();
  await rpc({ type: "hello", version: workflow.VERSION });
  let job;
  try { job = await rpc({ type: "status", job_id: saved.job_id }); }
  catch (error) {
    if (error.message && error.message.startsWith("Unknown job")) clearJob();
    throw error;
  }
  if (job.state === "prepared") {
    if (!saved.exported) { clearJob(); setStatus("The previous export did not finish. Start a new rough cut.", "ready"); return; }
    job = await rpc({ type: "start", job_id: saved.job_id });
  }
  await follow(job);
}

async function doDismiss() {
  const saved = lastJob();
  clearJob();
  setStatus("Previous job dismissed. Any running analysis continues in the helper. Saved result location:\n" + (saved ? saved.output_path : ""), "ready");
}

async function handleProbe(name, payload) {
  if (name === "timing") {
    setStatus("Reading this build's marks and timebase…", "busy");
    const report = await capability.probeMarksAndTiming(ppro);
    console.log("CutDeck capability probe", JSON.stringify(report, null, 2));
    setStatus(capability.formatReport(report), "ready");
    return;
  }
  if (name === "motion") {
    setStatus("Reading the Adjustment Layer's live Motion component on this sequence…", "busy");
    const report = await capability.probeAdjustmentLayerMotion(ppro);
    console.log("CutDeck AL motion probe", JSON.stringify(report, null, 2));
    setStatus(capability.formatMotionReport(report), "ready");
    return;
  }
  if (name === "effect") {
    setStatus("Reading the selected item's real effect chain…", "busy");
    const report = await capability.probeEffectChain(ppro);
    console.log("CutDeck effect chain probe", JSON.stringify(report, null, 2));
    setStatus(capability.formatEffectChainReport(report), "ready");
    return;
  }
  if (name === "socket") {
    setStatus("Probing which socket URLs this Premiere build permits…", "busy");
    const { report, written } = await probe.run();
    setStatus([`Socket permission probe:`, ...report.results.map((r) => `${r.url} -> ${r.outcome}`),
      ``, `written: ${written}`].join(`\n`), "ready");
    return;
  }
  if (name === "copystatus") {
    const text = state.status.text;
    if (navigator.clipboard && navigator.clipboard.writeText) await navigator.clipboard.writeText(text);
    else if (require("uxp").clipboard) require("uxp").clipboard.copyText(text);
    else throw new Error("No clipboard API on this build. The full report is in the UXP Developer Tool console as JSON.");
    setStatus(text + "\n\n--- copied to clipboard ---", "ready");
    return;
  }
  if (name === "capture-preset") {
    const label = ((payload && payload.name) || "").trim();
    if (!label) throw new Error("Name this preset first (the field next to Capture), then click Capture.");

    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error("Open a Premiere project first.");
    const seq = await project.getActiveSequence();
    if (!seq) throw new Error("Open a sequence first.");
    const item = await effects.getFirstSelectedTrackItem(seq);
    if (!item) {
      throw new Error("Select the clip or Adjustment Layer whose effects you want to capture, then click Capture.");
    }

    const captured = await effects.captureEffectFromTrackItem(ppro, item);
    const id = `fx-${Date.now().toString(36)}`;
    const preset = { id, name: label, components: captured.components };
    state.customPresets = [...state.customPresets, preset];
    saveCustomPresets(state.customPresets);
    panel.render(state);

    const names = captured.components.map((c) => c.displayName || c.matchName).join(", ");
    setStatus(
      `Captured "${label}" — ${captured.components.length} effect${captured.components.length === 1 ? "" : "s"}: ${names}.`,
      "ready"
    );
    return;
  }
}

function applySettingChange(patch) {
  if (Object.prototype.hasOwnProperty.call(patch, "audioTrack")) {
    state.audioTrack = patch.audioTrack;
  }
  const settingKeys = ["frames", "bin", "color", "clamp"];
  let changedSettings = false;
  const nextSettings = { ...state.settings };
  for (const key of settingKeys) {
    if (Object.prototype.hasOwnProperty.call(patch, key)) {
      nextSettings[key] = patch[key];
      changedSettings = true;
    }
  }
  if (changedSettings) {
    state.settings = nextSettings;
    saveSettingsToStorage(state.settings);
  }
  if (patch.statusText) {
    state.status = { text: patch.statusText, level: "ready" };
  }
  panel.render(state);
}

panel.bind({
  onRefresh: () => act(async () => { await doRefresh(); setStatus("Range ready", "ready"); }),
  onCut: () => act(doCut),
  onSync: () => act(doSync),
  onResumeJob: () => act(doResume),
  onDismissJob: () => act(doDismiss),
  onTab: (name) => { state.tab = name; panel.render(state); },
  onCutMode: (mode) => { state.cutMode = mode; panel.render(state); },
  onAdjust: (mode) => act(() => doAdjust(mode)),
  onApplyPreset: (presetId, mode) => act(() => doApplyPreset(presetId, mode)),
  onSettingChange: (patch) => applySettingChange(patch),
  onProbe: (name, payload) => act(() => handleProbe(name, payload)),
});

const savedJob = lastJob();
state.job = savedJob ? { id: savedJob.job_id, state: savedJob.state } : null;
panel.render(state);

// Automatically read and display timeline marks
setTimeout(async () => {
  try {
    await doRefresh();
    setStatus("Ready", "ready");
  } catch (_) {
    setStatus("Ready", "ready");
  }
}, 50);
