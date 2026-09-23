// Owns the Transform panel display state, clip transform reads, and polling loop.
// Must not know: the DOM, UI panels, Rough Cut or Sync job semantics.

const trackItems = require("../host/trackItems.js");
const transformParams = require("../transform/params.js");
const transformGeometry = require("../transform/geometry.js");
const { activeProjectAndSequence } = require("../host/project.js");
const capability = require("../capabilityProbe.js");

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
  const clipName = (item.name || "(unnamed)") + (items.length > 1 ? ` (+${items.length - 1} more selected)` : "");

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

function createAlignFeature({ ppro, ctl }) {
  let alignPollTimer = null;

  async function refreshAlignSequence() {
    const next = await readAlignState(ppro);
    ctl.state.sequence = next.sequence;
    ctl.state.transform = next.transform;
    ctl.render();
  }

  async function pollAlignTransform() {
    if (ctl.state.busy) return;
    try {
      const next = await readAlignState(ppro);
      ctl.state.sequence = next.sequence;
      ctl.state.transform = next.transform;
      ctl.render();
    } catch (error) {
      console.error("CutDeck: transform poll failed", error);
    }
  }

  function startAlignPolling() {
    if (alignPollTimer) return;
    alignPollTimer = setInterval(pollAlignTransform, 600);
  }

  return {
    onRefresh: () => ctl.act(refreshAlignSequence),
    onProbe: (_name) => ctl.act(async () => {
      await refreshAlignSequence();
      ctl.setStatus("Reading this clip's real Motion/Transform params, units and source dimensions…", "busy");
      const report = await capability.probeTransformParams(ppro);
      console.log("CutDeck transform params probe", JSON.stringify(report, null, 2));
      ctl.setStatus(capability.formatTransformReport(report), "ready");
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
  describeField,
  readAlignTransform,
  readAlignState,
};
