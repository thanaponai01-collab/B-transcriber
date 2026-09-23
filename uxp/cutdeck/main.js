const ppro = require("premierepro");
const workflow = require("./workflow.js");
const { createRpc } = require("./core/rpc.js");
const { progressText } = require("./core/progressText.js");
const probe = require("./probe.js");
const capability = require("./capabilityProbe.js");
const helperStart = require("./helperStart.js");
const panel = require("./core/panel.js");
const alignPanel = require("./core/alignPanel.js");
const timeline = require("./timeline/adjustmentLayer.js");
const effects = require("./timeline/effects.js");
const componentAccess = require("./timeline/componentAccess.js");
const transformParams = require("./transform/params.js");
const transformGeometry = require("./transform/geometry.js");
const { createPresetStore, CACHE_KEY: FX_PRESETS_KEY } = require("./presetStore.js");

const KEY = "cutdeck.xml.lastJob";
const SETTINGS_KEY = "cutdeck.adj.settings";
// Custom effect presets get their OWN storage key (FX_PRESETS_KEY, owned by presetStore.js),
// deliberately not folded into cutdeck.adj.settings: saveSettingsToStorage rewrites its entire
// blob on every minor setting change (frame count, color, ...), and a corrupt/oversized preset
// would otherwise silently wipe core settings back to DEFAULT_SETTINGS on the next load (see
// loadSettingsFromStorage's catch below). A separate key isolates both problems. With a preset
// folder linked, that key is only a cache of the folder's per-preset files — every edit goes
// through presetStore.add / rename / remove.
const presetStore = createPresetStore({
  localFileSystem: require("uxp").storage.localFileSystem,
  storage: localStorage,
});

const DEFAULT_SETTINGS = {
  frames: 16,
  bin: "CutDeck AL/FX",
  color: "Iris",
  // Default OFF (2026-09-22): transitions always get the full requested 50/50
  // width now that overlapping ones auto-stack onto separate tracks (see
  // timeline/adjustmentLayer.js's lane assignment) instead of overwriting each
  // other — confirmed working on real tight cuts. Clamping to fit a short clip
  // is still available as an opt-in for anyone who'd rather shrink than stack.
  clamp: false
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
  // Where presets are saved: { path: null | folder native path, error: null | message }.
  presetFile: { path: null, error: null },
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

// First paint only, from the cache — loadPresets() at startup replaces it with the linked
// folder's file when one is set.
function loadCustomPresets() {
  try {
    const saved = JSON.parse(localStorage.getItem(FX_PRESETS_KEY) || "null");
    return Array.isArray(saved) ? saved : [];
  } catch (_) {
    return [];
  }
}
async function loadPresets() {
  const res = await presetStore.load();
  state.customPresets = res.presets;
  state.presetFile = { path: res.path, error: res.error };
  if (res.error) setStatus(`Presets: ${res.error}`, "error");
  else panel.render(state);
}

async function editPresets(op) {
  state.customPresets = await op;
  state.presetFile = { path: presetStore.path, error: null };
}

async function doChoosePresetFolder() {
  const res = await presetStore.chooseFolder();
  if (!res) return;
  state.customPresets = res.presets;
  state.presetFile = { path: res.path, error: null };
  setStatus(`Presets now saved to ${res.path}. Choose the same synced folder on your other machines to share them.`, "ready");
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
  const warnings = [];
  for (const item of res.placedItems) {
    const applied = await effects.applyCapturedPreset(ppro, project, item, preset);
    warnings.push(...applied.warnings);
    appliedCount++;
  }

  const done = `Applied [${preset.name}] to ${appliedCount} AL(s) on V${res.targetTrack}${describeSequenceMatch(res)}`;
  if (warnings.length) {
    setStatus(`${done}, but ${warnings.length} thing(s) didn't land as captured:\n${warnings.slice(0, 6).join("\n")}`, "error");
  } else {
    setStatus(`${done}!`, "ready");
  }
}

// No Premiere call, but a file write when a preset folder is linked — so these run through
// act() like everything else that can fail.
async function doRemovePreset(presetId) {
  const preset = state.customPresets.find((p) => p.id === presetId);
  await editPresets(presetStore.remove(presetId));
  setStatus(preset ? `Removed "${preset.name}".` : "Removed.", "ready");
}

async function doRenamePreset(presetId, name) {
  if (!state.customPresets.some((p) => p.id === presetId)) return;
  await editPresets(presetStore.rename(presetId, name));
  setStatus(`Renamed to "${name}".`, "ready");
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
  if (name === "keyframe") {
    setStatus("Reading the selected clip's keyframes against the playhead…", "busy");
    const report = await capability.probeKeyframeTiming(ppro);
    console.log("CutDeck keyframe timing probe", JSON.stringify(report, null, 2));
    setStatus(capability.formatKeyframeReport(report), "ready");
    return;
  }
  if (name === "transform") {
    setStatus("Reading the selected clip's real Motion/Transform params, units and source dimensions…", "busy");
    const report = await capability.probeTransformParams(ppro);
    console.log("CutDeck transform params probe", JSON.stringify(report, null, 2));
    setStatus(capability.formatTransformReport(report), "ready");
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
    console.log("CutDeck captured preset:", JSON.stringify(captured, null, 2));
    const id = `fx-${Date.now().toString(36)}`;
    const preset = { id, name: label, components: captured.components };
    await editPresets(presetStore.add(preset));
    panel.render(state);

    const names = captured.components.map((c) => c.displayName || c.matchName).join(", ");
    const animatedNote = captured.animatedCount
      ? ` ${captured.animatedCount} keyframed param${captured.animatedCount === 1 ? "" : "s"} included.`
      : "";
    setStatus(
      `Captured "${label}" — ${captured.components.length} effect${captured.components.length === 1 ? "" : "s"}: ${names}.${animatedNote}`,
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
  onRemovePreset: (presetId) => act(() => doRemovePreset(presetId)),
  onRenamePreset: (presetId, name) => act(() => doRenamePreset(presetId, name)),
  onChoosePresetFolder: () => act(doChoosePresetFolder),
  onSettingChange: (patch) => applySettingChange(patch),
  onProbe: (name, payload) => act(() => handleProbe(name, payload)),
});

// --- second panel: Transform & Align (manifest entrypoint cutdeck.align.panel) -------------
//
// Premiere gives a plugin ONE main HTML document however many panel entrypoints it declares —
// there is no per-entrypoint "main" field. So the transform panel is a container inside
// index.html that entrypoints.setup()'s show() hook moves into the root Premiere creates for
// it. See core/alignPanel.js's header.
//
// Its own small state, deliberately not folded into `state`: the two panels are separate
// surfaces with separate status lines, and sharing one would mean every Cut & Sync status
// message also overwrote whatever the transform panel was showing. Keeping them apart also
// means this whole block can be reverted without touching a single existing render call.
const alignState = { sequence: null, transform: null, busy: false, status: { text: "Ready", level: "ready" } };

function renderAlign() {
  alignPanel.render(alignState);
}
function setAlignStatus(text, level = "ready") {
  alignState.status = { text, level };
  renderAlign();
}

// --- Phase 1: read-only Position/Scale/Rotation/Anchor Point display -----------------------
//
// Turns transform/params.js's raw per-field reads into the shape core/alignPanel.js renders.
// Position is normalized to the SEQUENCE frame and Anchor Point to the clip's SOURCE frame
// (transform-panel-plan.md Part 1a), so each needs transform/geometry.js's pixel conversion
// against its own frame; Scale and Rotation are
// already the numbers Effect Controls displays. An animated param (isTimeVarying === true) is
// reported as `animated: true` with no value — the plan requires it be skipped with a visible
// explanation, never silently shown as a possibly-wrong static number.
function describeField(entry, isPoint, frameSize) {
  if (!entry) return { known: false };
  if (entry.isTimeVarying) return { known: true, animated: true };
  if (isPoint) {
    const px = frameSize
      ? transformGeometry.normalizedToFramePixels(entry.value, frameSize.width, frameSize.height)
      : null;
    return px ? { known: true, animated: false, x: px.x, y: px.y } : { known: false };
  }
  return typeof entry.value === "number" ? { known: true, animated: false, value: entry.value } : { known: false };
}

// Reads the currently selected track item's Motion component and returns the display-ready
// shape core/alignPanel.js's renderTransform expects. `seq` may be null (no sequence open).
// Never throws — every failure path (no sequence, nothing selected, no readable Transform)
// returns `{ available: false, reason }` instead, per Phase 1's Definition of Done: a clip
// with no readable Transform shows "unavailable", not zeros.
async function readAlignTransform(seq) {
  if (!seq) return { clipName: null, available: false, reason: "No sequence open.", fields: null };

  const items = await componentAccess.getSelectedTrackItems(seq);
  if (items.length === 0) {
    return { clipName: null, available: false, reason: "Select a clip on the timeline.", fields: null };
  }
  const item = items[0];
  const clipName = (item.name || "(unnamed)") + (items.length > 1 ? ` (+${items.length - 1} more selected)` : "");

  const transform = await transformParams.readTransform(item);
  if (!transform) {
    return { clipName, available: false, reason: "This item has no readable Transform.", fields: null };
  }

  const frameSize = await transformParams.readSequenceFrameSize(seq);
  // Anchor Point is converted against the SOURCE frame, never the sequence frame as a
  // fallback — that would print a confidently wrong number on any clip whose source differs
  // from the sequence. Pixel aspect is deliberately NOT applied: a live run on a 1280x720 clip
  // interpreted as 2.0 PAR stored an Effect Controls anchor of 100,200 as [100/1280, 200/720],
  // so the anchor is in the source's stored pixels whatever its aspect (plan Part 1a).
  const anchorFrame = await transformParams.readSourceFrameSize(ppro, item);
  const fields = {
    position: describeField(transform.position, true, frameSize),
    scale: describeField(transform.scale, false, frameSize),
    rotation: describeField(transform.rotation, false, frameSize),
    anchor: describeField(transform.anchorPoint, true, anchorFrame),
  };
  return { clipName, available: true, reason: null, fields };
}

async function readAlignState() {
  const project = await ppro.Project.getActiveProject();
  const seq = project ? await project.getActiveSequence() : null;
  return {
    sequence: seq ? { name: seq.name || "(unnamed)" } : null,
    transform: await readAlignTransform(seq),
  };
}

// Same act() shape as the main panel's: one job at a time, errors land in the status line.
async function actAlign(fn) {
  if (alignState.busy) return;
  alignState.busy = true;
  alignState.status = { text: "Processing…", level: "busy" };
  renderAlign();
  try {
    await fn();
    if (alignState.status.level === "busy") alignState.status = { text: "Ready", level: "ready" };
  } catch (error) {
    alignState.status = { text: error.message || String(error), level: "error" };
    console.error(error);
  } finally {
    alignState.busy = false;
    renderAlign();
  }
}

async function refreshAlignSequence() {
  const next = await readAlignState();
  alignState.sequence = next.sequence;
  alignState.transform = next.transform;
  renderAlign();
}

// Keeps the transform display "live" (phase table: "Read-only display... live") the way Effect
// Controls itself does, without a selection-changed event to hook — Adobe's UXP declarations
// expose none for Premiere. Unlike refreshAlignSequence (wrapped in actAlign for the explicit
// "Click to refresh" action), this never touches alignState.busy/status: a poll tick must not
// flicker the busy spinner or disable controls every 600ms, and a poll error (e.g. no project
// open, which is normal steady state) must not spam the status line — it's logged and skipped.
let alignPollTimer = null;
async function pollAlignTransform() {
  if (alignState.busy) return;
  try {
    const next = await readAlignState();
    alignState.sequence = next.sequence;
    alignState.transform = next.transform;
    renderAlign();
  } catch (error) {
    console.error("CutDeck: transform poll failed", error);
  }
}
function startAlignPolling() {
  if (alignPollTimer) return;
  alignPollTimer = setInterval(pollAlignTransform, 600);
}

alignPanel.bind({
  onRefresh: () => actAlign(refreshAlignSequence),
  onProbe: (name) => actAlign(async () => {
    await refreshAlignSequence();
    setAlignStatus("Reading this clip's real Motion/Transform params, units and source dimensions…", "busy");
    const report = await capability.probeTransformParams(ppro);
    console.log("CutDeck transform params probe", JSON.stringify(report, null, 2));
    setAlignStatus(capability.formatTransformReport(report), "ready");
  }),
});

// Registering panels is what makes the SECOND entrypoint work; the first keeps its existing
// behavior because its content is already static in the document and its show() hook does
// nothing. Guarded, and placed after the main panel is fully bound and rendered, so that a
// build where entrypoints.setup() is absent or throws still gets a fully working Cut & Sync
// panel — the shipped tool must not regress to add a new one.
//
// No hide()/destroy() hooks: Adobe documents both as "not working as expected yet" in
// Premiere, so depending on them would be depending on something known broken. The container
// simply stays where show() put it.
try {
  const { entrypoints } = require("uxp");
  entrypoints.setup({
    panels: {
      "cutdeck.panel": {
        show() {},
      },
      "cutdeck.align.panel": {
        show(rootNode) {
          if (!alignPanel.mount(rootNode)) {
            console.error("CutDeck: could not mount #view-transform into the transform panel root.");
            return;
          }
          renderAlign();
          refreshAlignSequence().catch((error) => {
            setAlignStatus(error.message || String(error), "error");
          });
          startAlignPolling();
        },
      },
    },
  });
} catch (error) {
  // The Cut & Sync panel is unaffected — it is already bound and rendered above.
  console.error("CutDeck: entrypoints.setup() failed; the Transform panel will not open.", error);
}

const savedJob = lastJob();
state.job = savedJob ? { id: savedJob.job_id, state: savedJob.state } : null;
panel.render(state);

// Load presets from the linked folder, then automatically read and display timeline marks.
// A preset-folder problem must outlive the "Ready" that the mark refresh would otherwise
// paint straight over it.
setTimeout(async () => {
  await loadPresets();
  try {
    await doRefresh();
  } catch (_) { /* no sequence open yet — the refresh icon retries */ }
  if (state.presetFile.error) setStatus(`Presets: ${state.presetFile.error}`, "error");
  else setStatus("Ready", "ready");
}, 50);
