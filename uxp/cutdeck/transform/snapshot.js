// transform/snapshot.js — One read-model per timeline selection (Slice 2 of
// docs/research/cutdeck-panel-responsiveness-plan.md).
//
// Reads the full Transform & Align snapshot for the active selection in parallel:
// - Frame size and pixel aspect ratio read ONCE for the sequence.
// - Track items, Motion transforms, Graphic detection, layers and anchor frame sizes
//   read concurrently across selected items via Promise.all.
// - Caches the snapshot keyed by selection signature (track:startTicks keys) so subsequent
//   reads (poll, display, edit calculations) do not re-read Premiere repeatedly.
// - Invalidation occurs after every write CutDeck makes or when a different selection
//   signature is encountered.
// Must not know: the DOM, UI panels, Rough Cut or Sync job semantics.

const trackItems = require("../host/trackItems.js");
const transformParams = require("./params.js");
const { activeProjectAndSequence } = require("../host/project.js");

let cachedSnapshot = null;
let cachedSignature = null;
let cachedSeq = null;

let itemFallbackIdMap = new WeakMap();
let nextFallbackId = 1;

async function computeItemKey(item) {
  if (!item) return null;
  try {
    const start = typeof item.getStartTime === "function" ? (await item.getStartTime()).ticks : null;
    const track = typeof item.getTrackIndex === "function" ? await item.getTrackIndex() : null;
    if (start !== null && track !== null) return `${track}:${start}`;
  } catch (_) {}
  if (typeof item === "object") {
    if (!itemFallbackIdMap.has(item)) {
      itemFallbackIdMap.set(item, `obj_${nextFallbackId++}`);
    }
    return itemFallbackIdMap.get(item);
  }
  return null;
}

// Builds a selection signature string from items, e.g. "0:1000;1:2000" or item identities.
async function getSelectionSignature(items) {
  if (!items || items.length === 0) return "";
  const keys = await Promise.all(items.map((it) => computeItemKey(it)));
  return keys.join(";");
}

function clearSnapshotCache() {
  cachedSnapshot = null;
  cachedSignature = null;
  cachedSeq = null;
}

async function readSnapshot(ppro, options = {}) {
  const { forceRefresh = false, seq: passedSeq = null } = options;
  let seq = passedSeq;
  let project = null;
  if (!seq) {
    const active = await activeProjectAndSequence(ppro, { requireProject: false, requireSequence: false });
    seq = active.sequence;
    project = active.project;
  }

  if (!seq) {
    clearSnapshotCache();
    return {
      sequence: null,
      seqFrame: null,
      seqAspect: null,
      signature: "",
      items: [],
      clips: [],
    };
  }

  const rawItems = await trackItems.getSelectedTrackItems(seq, ppro);
  if (!rawItems || rawItems.length === 0) {
    clearSnapshotCache();
    return {
      sequence: seq,
      seqFrame: await transformParams.readSequenceFrameSize(seq),
      seqAspect: await transformParams.readSequencePixelAspect(seq),
      signature: "",
      items: [],
      clips: [],
    };
  }

  const signature = await getSelectionSignature(rawItems);

  if (!forceRefresh && cachedSnapshot && cachedSeq === seq && cachedSignature === signature) {
    return cachedSnapshot;
  }

  // Read sequence geometry once
  const [seqFrame, seqAspect] = await Promise.all([
    transformParams.readSequenceFrameSize(seq),
    transformParams.readSequencePixelAspect(seq),
  ]);

  // Read each candidate item concurrently
  const clipPromises = rawItems.map(async (item) => {
    const transform = await transformParams.readTransform(item);
    if (!transform) return null;

    const [key, name, isGraphic] = await Promise.all([
      computeItemKey(item),
      trackItems.trackItemName(item, "(unnamed)"),
      transformParams.isGraphic(item),
    ]);

    const [layers, anchorFrame] = await Promise.all([
      isGraphic ? transformParams.readGraphicLayers(item) : Promise.resolve(null),
      transformParams.readAnchorFrameSize(ppro, item, seq),
    ]);

    return {
      item,
      key,
      name,
      transform,
      isGraphic,
      layers,
      anchorFrame,
    };
  });
  const firstItemNamePromise = trackItems.trackItemName(rawItems[0], "(unnamed)");

  const resolvedClips = await Promise.all(clipPromises);
  const clips = resolvedClips.filter(Boolean);
  const firstItemName = await firstItemNamePromise;

  const snapshot = {
    sequence: seq,
    seqFrame,
    seqAspect,
    signature,
    items: rawItems,
    clips,
    firstItemName,
  };

  cachedSnapshot = snapshot;
  cachedSignature = signature;
  cachedSeq = seq;

  return snapshot;
}

module.exports = {
  readSnapshot,
  clearSnapshotCache,
  getSelectionSignature,
};
