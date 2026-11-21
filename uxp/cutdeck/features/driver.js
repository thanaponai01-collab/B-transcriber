// The panel as the Premiere driver (docs/arch-design-helper-v2.md move 3): runs the helper's
// fixed commands, sent on behalf of MCP agents and scripts (`python -m cutdeck.premiere_cli`),
// with the same code the panel's own buttons use. Never runs code it was sent.
// Must not know: the DOM, the helper socket, or who asked.
//
// Adobe APIs, beyond those workflow.capture and applyNativeCut already use:
//   Markers.getMarkers(sequence) [static, Promise<Markers>] and
//   Markers.createAddMarkerAction(name, markerType, start, duration, comments)
//   (reference/adobe/api/premierepro.txt:416,420; Adobe's metadata-handler sample calls
//   getMarkers the same way). 432 markers in one transaction, one Ctrl+Z: PREMIERE_FACTS
//   "Markers" (ledger 09-24). The `comments` argument is declared but never run live.
//   EncoderManager.getManager(), .exportSequence(sequence, exportType, outputFile, presetFile)
//   and static EncoderManager.getExportFileExtension(sequence, presetFile)
//   (reference/adobe/api/premierepro.txt:327-329; Constants.ExportType.IMMEDIATELY :203;
//   docs ppro-reference/classes/encodermanager.md "Since 25.6"; Adobe's premiere-api sample
//   src/export.ts makes the same IMMEDIATELY call). Live 2026-11-20: resolves after the render,
//   file complete (PREMIERE_FACTS "EncoderManager.getManager().exportSequence").
//   Project.createSequenceWithPresetPath(name, presetPath) (reference/adobe/api/premierepro.txt:493,
//   NOT IN 26.2.1; docs ppro-reference/classes/project.md "createSequenceWithPresetPath").

const workflow = require("../workflow.js");
const { applyNativeCut } = require("../timeline/nativeCut.js");
const { buildSequence } = require("../timeline/buildSequence.js");
const { activeProjectAndSequence, activeProject, sequencesNamed, runTransaction } = require("../host/project.js");
const { TICKS_PER_SECOND } = require("../host/ticks.js");
const { PROBES, runProbe } = require("./probes.js");
const { controlHandlers } = require("../timeline/control.js");
const { getSelectedTrackItems, getTrackClipItems, trackItemName } = require("../host/trackItems.js");
const {
  readTransform,
  readSourceFrameSize,
  readSequenceFrameSize,
  readSequencePixelAspect,
  readGraphicLayers,
  isGraphic,
} = require("../transform/params.js");
const {
  setField,
  setAnchor,
  alignToFrame,
  alignToFrameAsGroup,
  alignToSelection,
  distribute,
} = require("../transform/edit.js");

const COMMANDS = [
  "read_sequence",
  "read_audio_range",
  "apply_cuts",
  "add_markers",
  "run_probe",
  "inspect_selection",
  "set_transform_field",
  "set_anchor",
  "align_clips",
  "distribute_clips",
  "export_sequence",
  "reload_panel",
  "build_sequence",
  "cut_copy",
  "create_sequence",
  "read_timeline",
  "list_project",
  "open_sequence",
  "set_playhead",
  "set_in_out",
  "select_clips",
  "edit_clips",
  "place_media",
  "list_effects",
  "add_effect",
  "set_param",
  "add_transition",
  "set_track_mute",
  "remove_markers",
  "import_files",
  "save_project",
  "export_frame",
];

const seconds = (ticks) => Number(BigInt(ticks) * 1000n / TICKS_PER_SECOND) / 1000;

function createDriver({ ppro, ctl, align = null, measure = null, queueWaitMs = 30000, teardown = null }) {
  async function readSequence() {
    const { project, sequence } = await activeProjectAndSequence(ppro, {
      sequenceErrorMessage: "Open a sequence in Premiere first." });
    let inTicks = null, outTicks = null, inSeconds = null, outSeconds = null;
    try {
      const inPt = await sequence.getInPoint();
      if (inPt && Number.isFinite(inPt.seconds) && inPt.seconds >= 0) {
        inTicks = inPt.ticks ? String(inPt.ticks) : String(inPt);
        inSeconds = inPt.seconds;
      }
    } catch (_) {}
    try {
      const outPt = await sequence.getOutPoint();
      if (outPt && Number.isFinite(outPt.seconds) && outPt.seconds >= 0) {
        outTicks = outPt.ticks ? String(outPt.ticks) : String(outPt);
        outSeconds = outPt.seconds;
      }
    } catch (_) {}
    const endPt = await sequence.getEndTime();
    const endTicks = endPt ? String(endPt.ticks ? endPt.ticks : endPt) : "0";
    const tpf = await sequence.getTimebase();
    const aCount = await sequence.getAudioTrackCount();
    const vCount = await sequence.getVideoTrackCount();
    let allSeqs = [];
    try {
      const seqs = await project.getSequences();
      allSeqs = seqs.map((s) => s.name);
    } catch (_) {}

    return {
      name: sequence.name,
      sequence_id: sequence.guid.toString(),
      project_id: project.guid.toString(),
      project_path: project.path,
      in_ticks: inTicks,
      out_ticks: outTicks,
      end_ticks: endTicks,
      in_seconds: inSeconds,
      out_seconds: outSeconds,
      end_seconds: seconds(endTicks),
      ticks_per_frame: tpf,
      audio_track_count: aCount,
      video_track_count: vCount,
      all_sequences: allSeqs,
    };
  }

  // Every supported job comes from a live sequence capture; length alone cannot identify it.
  async function applyCuts({ cuts, sequence_id: sequenceId, sequence_name: sequenceName, result_name: resultName }) {
    const { project, sequence } = await activeProjectAndSequence(ppro, {
      sequenceErrorMessage: "Open the sequence to cut in Premiere first." });
    if (!sequenceId) throw new Error("This cut list has no source sequence identity. Start a new Rough Cut.");
    if (sequence.guid.toString() !== sequenceId) throw new Error(`Open "${sequenceName}" to cut it, then try again.`);
    ctl.setStatus("Cutting a copy of your sequence for an outside request…", "busy");
    const r = await applyNativeCut(ppro, project, sequence, cuts, resultName);
    return { cuts: r.cuts, removed_seconds: seconds(r.removedTicks), splits: r.splits, undo_steps: r.steps,
      name: r.name, elapsed_seconds: r.elapsedSeconds };
  }

  /* cut_copy: copy the sequence named `sequence_name` and cut `cuts` ({ticks_per_frame,
     cuts_frames}) out of the copy with the Rough Cut engine (applyNativeCut: clone, per-item
     razor/remove/close-gap, read-back). Every synced layer, effect and disabled state of the source
     is kept; the source is not edited. The copy opens when done. */
  async function cutCopy({ sequence_name: sequenceName, cuts, result_name: resultName }) {
    const project = await activeProject(ppro);
    const matches = await sequencesNamed(project, sequenceName);
    if (matches.length !== 1) throw new Error(`Found ${matches.length} sequences named "${sequenceName}"; need exactly one.`);
    ctl.setStatus(`Cutting a copy of "${sequenceName}" for an outside request…`, "busy");
    const r = await applyNativeCut(ppro, project, matches[0], cuts, resultName);
    return { cuts: r.cuts, removed_seconds: seconds(r.removedTicks), splits: r.splits, undo_steps: r.steps,
      name: r.name, elapsed_seconds: r.elapsedSeconds };
  }

  /* create_sequence: a new empty sequence `name` from the .sqpreset `preset_path` (e.g. a 9:16
     frame no sequence in the project has yet). Refuses a name already in use: no API deletes a
     sequence. Reads back the frame size and frame duration it got. */
  async function createSequence({ name, preset_path: presetPath }) {
    const project = await activeProject(ppro);
    if ((await sequencesNamed(project, name)).length) throw new Error(`A sequence named "${name}" already exists.`);
    const sequence = await project.createSequenceWithPresetPath(name, presetPath);
    if (!sequence) throw new Error(`createSequenceWithPresetPath returned nothing for ${presetPath}`);
    const size = await sequence.getFrameSize();
    return { name: sequence.name, sequence_id: String(sequence.guid), width: size.width, height: size.height,
      ticks_per_frame: String(await sequence.getTimebase()), video_tracks: await sequence.getVideoTrackCount(),
      audio_tracks: await sequence.getAudioTrackCount() };
  }

  async function addMarkers({ markers }) {
    const { project, sequence } = await activeProjectAndSequence(ppro, {
      sequenceErrorMessage: "Open a sequence in Premiere first." });
    const owner = await ppro.Markers.getMarkers(sequence);
    // Every Action is created inside the transaction (PREMIERE_FACTS "Transactions": one made
    // outside throws "The script object is no longer valid.").
    runTransaction(project, "CutDeck: add markers", (compound) => {
      for (const m of markers) {
        const action = owner.createAddMarkerAction(m.name, "Comment", ppro.TickTime.createWithTicks(m.start_ticks),
          ppro.TickTime.createWithTicks(m.duration_ticks), m.comment);
        if (!compound.addAction(action)) throw new Error("addAction(marker) returned false");
      }
    });
    return { added: markers.length, undo_steps: 1 };
  }

  async function runProbeCmd({ probe }) {
    const entry = PROBES.find((p) => p.id === probe && !p.special);
    if (!entry) throw new Error(`Unknown probe: ${probe}`);
    const rawReport = await runProbe(entry, ppro, ctl);
    const report = JSON.parse(JSON.stringify(rawReport, (k, v) => (typeof v === "bigint" ? v.toString() : v)));
    return { probe, report };
  }

  async function inspectSelection() {
    const { sequence } = await activeProjectAndSequence(ppro, {
      sequenceErrorMessage: "Open a sequence in Premiere first." });
    const rawSelected = await getSelectedTrackItems(sequence, ppro);
    const hasSelection = Array.isArray(rawSelected) && rawSelected.length > 0;
    let selectedItems = hasSelection ? rawSelected : [];
    if (!hasSelection) {
      const vCount = typeof sequence.getVideoTrackCount === "function" ? await sequence.getVideoTrackCount() : 0;
      for (let v = 0; v < vCount; v++) {
        const trk = typeof sequence.getVideoTrack === "function" ? await sequence.getVideoTrack(v) : null;
        const trkItems = trk ? await getTrackClipItems(trk, ppro) : [];
        for (const it of trkItems) {
          selectedItems.push(it);
        }
      }
    }
    const seqFrame = await readSequenceFrameSize(sequence);
    const seqPixelAspect = await readSequencePixelAspect(sequence);

    const items = [];
    for (const item of selectedItems) {
      const name = await trackItemName(item, "unnamed");
      const transform = await readTransform(item);
      const sourceSize = await readSourceFrameSize(ppro, item);
      const graphic = (await isGraphic(item)) ? await readGraphicLayers(item) : null;
      let startTicks = null;
      let endTicks = null;
      let inTicks = null;
      let outTicks = null;
      try {
        const s = await item.getStartTime();
        startTicks = s ? String(s.ticks !== undefined ? s.ticks : s) : null;
      } catch (_) {}
      try {
        const e = await item.getEndTime();
        endTicks = e ? String(e.ticks !== undefined ? e.ticks : e) : null;
      } catch (_) {}
      try {
        const i = await item.getInPoint();
        inTicks = i ? String(i.ticks !== undefined ? i.ticks : i) : null;
      } catch (_) {}
      try {
        const o = await item.getOutPoint();
        outTicks = o ? String(o.ticks !== undefined ? o.ticks : o) : null;
      } catch (_) {}

      items.push({
        name,
        start_ticks: startTicks,
        end_ticks: endTicks,
        in_ticks: inTicks,
        out_ticks: outTicks,
        start_s: startTicks ? seconds(startTicks) : null,
        end_s: endTicks ? seconds(endTicks) : null,
        in_s: inTicks ? seconds(inTicks) : null,
        out_s: outTicks ? seconds(outTicks) : null,
        transform,
        source_size: sourceSize,
        graphic,
      });
    }

    return {
      sequence_name: sequence.name,
      sequence_frame: seqFrame,
      sequence_pixel_aspect: seqPixelAspect,
      has_selection: hasSelection,
      selected_count: items.length,
      items,
    };
  }

  async function setTransformField({ field, value }) {
    const r = await setField(ppro, field, value);
    if (align && typeof align.refresh === "function") {
      try { await align.refresh(); } catch (_) {}
    }
    return { done: r.done, skipped: r.skipped, field, value: Number(value) };
  }

  // `layer`: one text layer (0-based) of a multi-text Graphic, as the panel's Text 1 / Text 2
  // switcher; left out = the whole Graphic.
  const layerOptions = (layer) => (Number.isInteger(layer) ? { layerTarget: layer } : {});

  async function setAnchorCmd({ target, layer = null }) {
    const r = await setAnchor(ppro, target, measure, { ...layerOptions(layer), textBoxes: align ? align.textBoxes : null });
    if (align && typeof align.refresh === "function") {
      try { await align.refresh(); } catch (_) {}
    }
    return { done: r.done, skipped: r.skipped, notes: r.notes || [], target };
  }

  async function alignClips({ edge, to = "frame", layer = null }) {
    const run = to === "selection" ? alignToSelection : to === "group" ? alignToFrameAsGroup : alignToFrame;
    const r = await run(ppro, edge, measure, { ...layerOptions(layer), textBoxes: align ? align.textBoxes : null });
    if (align && typeof align.refresh === "function") {
      try { await align.refresh(); } catch (_) {}
    }
    return { done: r.done, skipped: r.skipped, notes: r.notes || [], edge, to };
  }

  async function distributeClips({ kind, to = "frame" }) {
    const r = await distribute(ppro, kind, measure, to, { textBoxes: align ? align.textBoxes : null });
    if (align && typeof align.refresh === "function") {
      try { await align.refresh(); } catch (_) {}
    }
    return { done: r.done, skipped: r.skipped, notes: r.notes || [], kind, to };
  }

  /* The ACTIVE sequence only: a project can hold several sequences with one name. The helper
     has already refused an existing output file and a missing preset. */
  /* queue "ame": Constants.ExportType.QUEUE_TO_AME (premierepro.txt:204, docs constants
     "QUEUE_TO_AME 25.6") adds the job to Media Encoder's queue; isAMEInstalled (:330); then
     startBatchEncode() (:334, docs "Since 26.3", NOT IN 26.2.1 so feature-checked; Adobe's
     premiere-api sample src/encoderManager.ts calls it the same way) starts the queue.
     Live 2026-11-20: start called 0.18 s after the export resolved returned true but AME did not
     start, so we first wait for EncoderManager.EVENT_RENDER_QUEUE (:323) via
     EventManager.addEventListener / removeEventListener (:335, :337). */
  /* sequence_name: export that sequence instead of the active one. A project can hold several
     with one name (an episode template's empty copies), so only those with content count
     (Project.getSequences :503, Sequence.getEndTime :596); anything but exactly one refuses. */
  async function namedSequence(project, name) {
    const named = await sequencesNamed(project, name);
    const withContent = [];
    for (const s of named) if ((await s.getEndTime()).seconds > 0) withContent.push(s);
    if (withContent.length !== 1) {
      throw new Error(`Found ${withContent.length} sequences named "${name}" with content (of ${named.length} with that name); need exactly 1.`);
    }
    return withContent[0];
  }

  async function exportSequence({ output_file, preset_file, queue = "premiere", sequence_name = null, start = true }) {
    const active = await activeProjectAndSequence(ppro, {
      requireSequence: !sequence_name, sequenceErrorMessage: "Open the sequence to export in Premiere first." });
    const sequence = sequence_name ? await namedSequence(active.project, sequence_name) : active.sequence;
    const extension = String(await ppro.EncoderManager.getExportFileExtension(sequence, preset_file) || "")
      .replace(/^\./, "").toLowerCase();
    if (extension && !output_file.toLowerCase().endsWith(`.${extension}`)) {
      throw new Error(`This preset writes .${extension} files; output_file must end in .${extension}`);
    }
    const manager = ppro.EncoderManager.getManager();
    if (queue === "ame" && !manager.isAMEInstalled) throw new Error("Adobe Media Encoder is not installed.");
    const type = queue === "ame" ? ppro.Constants.ExportType.QUEUE_TO_AME : ppro.Constants.ExportType.IMMEDIATELY;
    const canStart = queue === "ame" && start && typeof manager.startBatchEncode === "function";
    let onQueued = null;
    const queuedEvent = canStart ? new Promise((resolve) => {
      onQueued = () => resolve(true);
      ppro.EventManager.addEventListener(manager, ppro.EncoderManager.EVENT_RENDER_QUEUE, onQueued);
      setTimeout(() => resolve(false), queueWaitMs);
    }) : null;
    const started = Date.now();
    let resolved, queued_event = null, queue_started = null; // null: not asked or not available
    try {
      resolved = await manager.exportSequence(sequence, type, output_file, preset_file);
      if (canStart && resolved) {
        queued_event = await queuedEvent;
        queue_started = await manager.startBatchEncode();
      }
    } finally {
      if (onQueued) ppro.EventManager.removeEventListener(manager, ppro.EncoderManager.EVENT_RENDER_QUEUE, onQueued);
    }
    const [inPt, outPt] = [await sequence.getInPoint(), await sequence.getOutPoint()];
    return { sequence_name: sequence.name, sequence_id: String(sequence.guid), output_file, preset_file,
      in_seconds: inPt.seconds, out_seconds: outPt.seconds, end_seconds: (await sequence.getEndTime()).seconds,
      queue, extension, resolved, queued_event, queue_started, promise_s: (Date.now() - started) / 1000 };
  }

  const handlers = {
    read_sequence: readSequence,
    read_audio_range: async () => {
      const snapshot = await workflow.capture(ppro);
      snapshot.context.project_path = snapshot.project.path;
      return { context: snapshot.context,
        sequence: await workflow.readAudioTracks(ppro, snapshot.sequence, snapshot.context) };
    },
    apply_cuts: applyCuts,
    add_markers: addMarkers,
    run_probe: runProbeCmd,
    inspect_selection: inspectSelection,
    set_transform_field: setTransformField,
    set_anchor: setAnchorCmd,
    align_clips: alignClips,
    distribute_clips: distributeClips,
    export_sequence: exportSequence,
    cut_copy: cutCopy,
    create_sequence: createSequence,
    // General control (timeline/control.js; route map docs/PREMIERE_CONTROL_MAP.md).
    ...controlHandlers(ppro),
    build_sequence: (args) => buildSequence(ppro, args, (line) => console.log(`CutDeck build: ${line}`)),
    // The reply goes out first (300 ms). Then teardown, as the panel menu's Reload does: a reload that left CutDeck's Premiere event listeners
    // registered took Premiere down in the same second (live 2026-11-21 16:03:58, 18:00:02).
    reload_panel: async () => {
      setTimeout(() => {
        if (teardown) { try { teardown(); } catch (_) {} }
        window.location.reload();
      }, 300);
      return { reloading: true };
    },
  };

  /* One call from the helper. Refused while the panel is busy, never queued behind the user. */
  async function handle(call) {
    const run = handlers[call.command];
    if (!run) throw new Error(`The CutDeck panel has no command ${call.command}`);
    if (ctl.state.busy) throw new Error("CutDeck panel is busy with another action; try again when it finishes");
    ctl.state.busy = true;
    ctl.render();
    try {
      const result = await run(call.args || {});
      ctl.setStatus(`Done: ${call.command.replace("_", " ")} for an outside request.`, "ready");
      return result;
    } catch (error) {
      ctl.setStatus((error && error.message) || String(error), "error");
      throw error;
    } finally {
      ctl.state.busy = false;
      ctl.render();
    }
  }

  return { commands: COMMANDS, handle };
}

/* Keeps the panel registered as the driver: registers on the driver's own connection, and
   again after any drop (a helper restart, or a helper started later), backing off 5 s → 30 s. */
function keepRegistered({ rpc, version, commands, setTimer = setTimeout, clearTimer = (typeof clearTimeout === "function" ? clearTimeout : null) }) {
  let delay = 5000;
  let timer = null;
  let stopped = false;
  const later = () => {
    if (stopped || timer) return;
    timer = setTimer(() => { timer = null; attempt(); }, delay);
    delay = Math.min(delay * 2, 30000);
  };
  async function attempt() {
    if (stopped) return;
    try {
      await rpc({ type: "hello", version });
      if (stopped) return;
      await rpc({ type: "register_driver", commands });
      delay = 5000;
    } catch (_) {
      if (!stopped) later();
    }
  }
  function stop() {
    stopped = true;
    if (timer) {
      if (typeof clearTimer === "function") clearTimer(timer);
      timer = null;
    }
  }
  return { start: attempt, onClose: later, stop };
}

module.exports = { createDriver, keepRegistered, COMMANDS };
