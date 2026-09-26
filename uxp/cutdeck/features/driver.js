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

const workflow = require("../workflow.js");
const { applyNativeCut } = require("../timeline/nativeCut.js");
const { activeProjectAndSequence, runTransaction } = require("../host/project.js");
const { TICKS_PER_SECOND, toTicks } = require("../host/ticks.js");
const { PROBES, runProbe } = require("./probes.js");
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
  alignToSelection,
  distribute,
} = require("./align.js");

const COMMANDS = [
  "read_sequence",
  "apply_cuts",
  "add_markers",
  "run_probe",
  "inspect_selection",
  "set_transform_field",
  "set_anchor",
  "align_clips",
  "distribute_clips",
];

const seconds = (ticks) => Number(BigInt(ticks) * 1000n / TICKS_PER_SECOND) / 1000;

function createDriver({ ppro, ctl, align = null, measure = null }) {
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

  /* A panel job names the sequence it analysed. A job from an XML file (MCP) doesn't, so its
     length must match instead, with the helper's own tolerance for an export's padding
     (xml_bridge.range_from_ticks: max(30 frames, 5 s)). */
  async function applyCuts({ cuts, sequence_id: sequenceId, sequence_name: sequenceName, result_name: resultName }) {
    const { project, sequence } = await activeProjectAndSequence(ppro, {
      sequenceErrorMessage: "Open the sequence to cut in Premiere first." });
    if (sequenceId) {
      if (sequence.guid.toString() !== sequenceId) throw new Error(`Open "${sequenceName}" to cut it, then try again.`);
    } else {
      const tpf = toTicks(await sequence.getTimebase());
      const frames = toTicks(await sequence.getEndTime()) / tpf;
      const fps = Number(TICKS_PER_SECOND / tpf);
      const slack = BigInt(Math.max(30, Math.floor(fps * 5)));
      const expected = BigInt(cuts.sequence_duration_frames || 0);
      if (frames > expected + slack || expected > frames + slack) {
        throw new Error(`The active sequence is ${frames} frames; the cut list was made for ${expected}. Open the analysed sequence.`);
      }
    }
    ctl.setStatus("Cutting a copy of your sequence for an outside request…", "busy");
    const r = await applyNativeCut(ppro, project, sequence, cuts, resultName);
    return { cuts: r.cuts, removed_seconds: seconds(r.removedTicks), splits: r.splits, undo_steps: r.steps,
      name: r.name, elapsed_seconds: r.elapsedSeconds };
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
      const graphic = isGraphic(item) ? await readGraphicLayers(item) : null;
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

  async function setAnchorCmd({ target }) {
    const r = await setAnchor(ppro, target, measure);
    if (align && typeof align.refresh === "function") {
      try { await align.refresh(); } catch (_) {}
    }
    return { done: r.done, skipped: r.skipped, target };
  }

  async function alignClips({ edge, to = "frame" }) {
    const r = await (to === "selection" ? alignToSelection(ppro, edge, measure) : alignToFrame(ppro, edge, measure));
    if (align && typeof align.refresh === "function") {
      try { await align.refresh(); } catch (_) {}
    }
    return { done: r.done, skipped: r.skipped, edge, to };
  }

  async function distributeClips({ kind, to = "frame" }) {
    const r = await distribute(ppro, kind, measure, to);
    if (align && typeof align.refresh === "function") {
      try { await align.refresh(); } catch (_) {}
    }
    return { done: r.done, skipped: r.skipped, kind, to };
  }

  const handlers = {
    read_sequence: readSequence,
    apply_cuts: applyCuts,
    add_markers: addMarkers,
    run_probe: runProbeCmd,
    inspect_selection: inspectSelection,
    set_transform_field: setTransformField,
    set_anchor: setAnchorCmd,
    align_clips: alignClips,
    distribute_clips: distributeClips,
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
