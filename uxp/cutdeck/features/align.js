// Owns the Transform panel display state, clip transform reads, and polling loop.
// Must not know: the DOM, UI panels, Rough Cut or Sync job semantics.

const trackItems = require("../host/trackItems.js");
const transformParams = require("../transform/params.js");
const transformGeometry = require("../transform/geometry.js");
const { activeProjectAndSequence } = require("../host/project.js");
const { PROBES, runProbe } = require("./probes.js");

const transformProbe = PROBES.find((p) => p.id === "transform");

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

async function readAlignTransform(seq, ppro) {
  if (!seq) return { clipName: null, available: false, reason: "No sequence open.", fields: null };

  const items = await trackItems.getSelectedTrackItems(seq);
  if (items.length === 0) {
    return { clipName: null, available: false, reason: "Select a clip on the timeline.", fields: null };
  }
  const item = items[0];
  const clipName = (await trackItems.trackItemName(item, "(unnamed)")) + (items.length > 1 ? ` (+${items.length - 1} more selected)` : "");

  const transform = await transformParams.readTransform(item);
  if (!transform) {
    return { clipName, available: false, reason: "This item has no readable Transform.", fields: null };
  }

  const frameSize = await transformParams.readSequenceFrameSize(seq);
  const anchorFrame = await transformParams.readSourceFrameSize(ppro, item);
  const fields = {
    position: describeField(transform.position, true, frameSize),
    scale: describeField(transform.scale, false, frameSize),
    rotation: describeField(transform.rotation, false, frameSize),
    anchor: describeField(transform.anchorPoint, true, anchorFrame),
  };
  return { clipName, available: true, reason: null, fields };
}

async function readAlignState(ppro) {
  const { sequence: seq } = await activeProjectAndSequence(ppro, { requireProject: false, requireSequence: false });
  return {
    sequence: seq ? { name: seq.name || "(unnamed)" } : null,
    transform: await readAlignTransform(seq, ppro),
  };
}

// Without events the panel falls back to the old fast poll. With them there is no poll:
// a Position drag in Effect Controls fires no event and shows on the next click or Refresh.
const FAST_POLL_MS = 600;

// Subscribes `handler` to selection changes and sequence switches. EventManager and
// Constants.SequenceEvent {ACTIVATED, SELECTION_CHANGED} are in @adobe/premierepro 26.2.1
// d.ts. Live (2026-09-24): a global ACTIVATED listener fires on sequence switch, but a
// global SELECTION_CHANGED does not — so selection is attached to the active sequence and
// moved on every switch. Returns false if unavailable.
function subscribeSequenceEvents(ppro, handler) {
  const em = ppro && ppro.EventManager;
  const ev = ppro && ppro.Constants && ppro.Constants.SequenceEvent;
  if (!em || typeof em.addGlobalEventListener !== "function" || typeof em.addEventListener !== "function" || !ev) {
    return false;
  }
  let attached = null;
  const attachToActive = async () => {
    try {
      const { sequence } = await activeProjectAndSequence(ppro, { requireProject: false, requireSequence: false });
      if (sequence === attached) return;
      if (attached && typeof em.removeEventListener === "function") {
        try { em.removeEventListener(attached, ev.SELECTION_CHANGED, handler); } catch (_) {}
      }
      attached = sequence || null;
      if (attached) em.addEventListener(attached, ev.SELECTION_CHANGED, handler);
    } catch (error) {
      console.error("CutDeck: could not attach selection listener", error);
    }
  };
  try {
    em.addGlobalEventListener(ev.ACTIVATED, () => { attachToActive(); handler(); });
    attachToActive();
    return true;
  } catch (error) {
    console.error("CutDeck: sequence event subscribe failed, polling instead", error);
    return false;
  }
}

function createAlignFeature({ ppro, ctl }) {
  let alignPollTimer = null;
  let pollInFlight = false;
  let pollAgain = false;

  async function refreshAlignSequence() {
    const next = await readAlignState(ppro);
    ctl.state.sequence = next.sequence;
    ctl.state.transform = next.transform;
    ctl.render();
  }

  // Coalesces bursts (a drag-select fires many events): one read at a time, plus one
  // follow-up if more arrived meanwhile.
  async function pollAlignTransform() {
    if (ctl.state.busy) return;
    if (pollInFlight) { pollAgain = true; return; }
    pollInFlight = true;
    try {
      do {
        pollAgain = false;
        const next = await readAlignState(ppro);
        ctl.state.sequence = next.sequence;
        ctl.state.transform = next.transform;
        ctl.render();
      } while (pollAgain);
    } catch (error) {
      console.error("CutDeck: transform poll failed", error);
    } finally {
      pollInFlight = false;
    }
  }

  let started = false;
  function startAlignPolling() {
    if (started) return;
    started = true;
    if (!subscribeSequenceEvents(ppro, () => { pollAlignTransform(); })) {
      alignPollTimer = setInterval(pollAlignTransform, FAST_POLL_MS);
    }
  }

  return {
    onRefresh: () => ctl.act(refreshAlignSequence),
    onProbe: (_name) => ctl.act(async () => {
      await refreshAlignSequence();
      await runProbe(transformProbe, ppro, ctl);
    }),
    refresh: refreshAlignSequence,
    startPolling: startAlignPolling,
    describeField,
    readAlignTransform: (seq) => readAlignTransform(seq, ppro),
    readAlignState: () => readAlignState(ppro),
  };
}

module.exports = {
  createAlignFeature,
  subscribeSequenceEvents,
  describeField,
  readAlignTransform,
  readAlignState,
};
