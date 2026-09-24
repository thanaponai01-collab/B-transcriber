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

const COMMANDS = ["read_sequence", "apply_cuts", "add_markers"];

const seconds = (ticks) => Number(BigInt(ticks) * 1000n / TICKS_PER_SECOND) / 1000;

function createDriver({ ppro, ctl }) {
  async function readSequence() {
    const snap = await workflow.capture(ppro);
    const c = snap.context;
    return { name: c.sequence_name, sequence_id: c.sequence_id, project_id: c.project_id,
      in_ticks: c.in_ticks, out_ticks: c.out_ticks, end_ticks: c.end_ticks,
      in_seconds: snap.inSeconds, out_seconds: snap.outSeconds, end_seconds: seconds(c.end_ticks),
      ticks_per_frame: c.ticks_per_frame, audio_track_count: c.audio_track_count,
      video_track_count: await snap.sequence.getVideoTrackCount() };
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

  const handlers = { read_sequence: readSequence, apply_cuts: applyCuts, add_markers: addMarkers };

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
function keepRegistered({ rpc, version, commands, setTimer = setTimeout }) {
  let delay = 5000;
  let timer = null;
  const later = () => {
    if (timer) return;
    timer = setTimer(() => { timer = null; attempt(); }, delay);
    delay = Math.min(delay * 2, 30000);
  };
  async function attempt() {
    try {
      await rpc({ type: "hello", version });
      await rpc({ type: "register_driver", commands });
      delay = 5000;
    } catch (_) {
      later();
    }
  }
  return { start: attempt, onClose: later };
}

module.exports = { createDriver, keepRegistered, COMMANDS };
