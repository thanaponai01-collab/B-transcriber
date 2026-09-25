const { toTicksOr, makeTickTime } = require("../host/ticks.js");
const {
  CUTDECK_BIN_NAME,
  runTransaction,
  activeProjectAndSequence,
} = require("../host/project.js");
const {
  getTrackClipItems,
  getTrackClipItemsOrThrow,
  getSelectedVideoClips,
  trackItemName,
} = require("../host/trackItems.js");
const {
  assignPlacementLanes,
  resolveTopLayer,
  planPlacements,
} = require("./alPlacement.js");
const {
  ADJ_BIN_NAME,
  getOrCreateAdjBin,
  flattenImportWrappers,
  detectResolutionFromMetadata,
  pickBestCandidate,
  findAdjustmentLayerItem,
  findColorMatteItem,
  writeTempFile,
  createAdjustmentLayerForSequence,
  createColorMatteForSequence,
} = require("./alLibrary.js");

// Premiere timeline manipulation for CutDeck adjustment-layer placement — no DOM.
// Owned by uxp/cutdeck/main.js via placeAdjustmentLayersOnTimeline(); see issue #47, #56.

// Label color index mapping for Premiere Pro clips
function getLabelIndex(colorName) {
  const map = {
    "violet": 0, "iris": 1, "caribbean": 2, "lavender": 3,
    "cerulean": 4, "forest": 5, "rose": 6, "mango": 7,
    "purple": 8, "blue": 9, "teal": 10, "magenta": 11,
    "tan": 12, "green": 13, "brown": 14, "yellow": 15
  };
  if (!colorName) return 1;
  const key = String(colorName).toLowerCase();
  return map[key] !== undefined ? map[key] : 1;
}

// Reads one video track's clip spans. Throws if the track can't be read — the caller
// decides whether that means "occupied" or "abort" (see getTrackClipItemsOrThrow).
async function readTrackSpans(seq, trackIndex, ppro) {
  const track = await seq.getVideoTrack(trackIndex);
  const items = await getTrackClipItemsOrThrow(track, ppro);
  const spans = await Promise.all(items.map(async (it) => {
    try {
      const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
      const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
      return { start: toTicksOr(sTime, 0n), end: toTicksOr(eTime, 0n), it };
    } catch (_) {
      return null;
    }
  }));
  return spans.filter(Boolean);
}

function firstOverlap(spans, startTicks, endTicks) {
  return spans.find((sp) => sp.end > startTicks && sp.start < endTicks) || null;
}

// Picks a video track index for every placement. Every track is read ONCE (an unreadable
// one counts as occupied); lanes and the per-placement gate are decided on that snapshot;
// then each chosen track is re-read right before the caller writes, and any change aborts.
// Throws rather than risk overwriting footage.
async function pickPlacementTracks(ppro, seq, placements) {
  if (placements.length === 0) return [];
  const trackCount = await seq.getVideoTrackCount();
  const trackPromises = [];
  for (let v = 0; v < trackCount; v++) {
    trackPromises.push(
      readTrackSpans(seq, v, ppro).catch((e) => {
        // Could not verify V(v+1) is empty — treat it as occupied rather than risk
        // overwriting real clips we failed to see.
        console.log(`pickPlacementTracks: could not read V${v + 1} items, assuming occupied:`, e);
        return null;
      })
    );
  }
  const snapshot = await Promise.all(trackPromises);
  // Tracks past the end don't exist yet — nothing to collide with.
  const isClear = (v, start, end) => v >= trackCount || (snapshot[v] !== null && !firstOverlap(snapshot[v], start, end));

  // Pick one track per LANE (see assignPlacementLanes), clear across the union of every
  // placement's span in that lane, not per-placement. This project can have real
  // footage on tracks above V1 partway through the timeline (confirmed: a real
  // clip sits on V2 mid-timeline in this project) — picking per placement
  // means a placement over that stretch gets bumped to a higher track while
  // others elsewhere don't, fragmenting one batch across many tracks for no
  // reason. A track clear of the union is clear for every placement in the lane.
  //
  // Lanes matter because transition mode (Shift+Click) centers each AL on its
  // own cut independently: cuts closer together than the requested frame width
  // produce ALs whose spans genuinely overlap each other. Placements were
  // previously always forced onto ONE shared track for the whole batch — two
  // overlapping ones landed on the same track and each createOverwriteItemAction
  // silently clipped the one placed just before it (confirmed 2026-09-22: tight
  // cuts produced overwritten/fragmented ALs instead of stacking). Lanes are
  // mutually non-overlapping by construction (assignPlacementLanes), so giving
  // each lane its own track — strictly above the previous lane's — guarantees
  // overlapping transitions always stack onto separate tracks instead of
  // colliding, without needing to re-detect the collision after the fact.
  const laneOf = assignPlacementLanes(placements);
  const laneCount = Math.max(...laneOf) + 1;
  const laneTracks = new Array(laneCount).fill(1);
  let floorTrack = 1;
  for (let lane = 0; lane < laneCount; lane++) {
    let unionStart = null;
    let unionEnd = null;
    placements.forEach((p, i) => {
      if (laneOf[i] !== lane) return;
      if (unionStart === null || p.startTicks < unionStart) unionStart = p.startTicks;
      if (unionEnd === null || p.endTicks > unionEnd) unionEnd = p.endTicks;
    });
    // Start above the highest track with anything in range (or unreadable), so a lane
    // never lands under footage, then step past any track that still isn't clear.
    let highestOccupied = 0;
    for (let v = 0; v < trackCount; v++) {
      if (!isClear(v, unionStart, unionEnd)) highestOccupied = v;
    }
    let laneTrack = Math.max(floorTrack, highestOccupied + 1);
    while (!isClear(laneTrack, unionStart, unionEnd)) laneTrack++;
    laneTracks[lane] = laneTrack;
    // Next lane must stack strictly above this one: lanes exist specifically
    // because their placements overlap each other in time, so two lanes must
    // never share a track.
    floorTrack = laneTrack + 1;
  }

  // Hard gate, for every placement BEFORE anything is committed: the exact span must be
  // clear on its lane's track, and must not overlap another placement already claimed
  // for that track in this run (they all land in one transaction, so the sequence is not
  // re-read in between). Normally the lane's track is already clear.
  const claimed = [];
  const targets = [];
  for (let pIdx = 0; pIdx < placements.length; pIdx++) {
    const p = placements[pIdx];
    let targetTrack = laneTracks[laneOf[pIdx]];
    let guard = 0;
    while (guard < 32) {
      const collides = claimed.some((c) => c.track === targetTrack && c.start < p.endTicks && p.startTicks < c.end);
      if (isClear(targetTrack, p.startTicks, p.endTicks) && !collides) break;
      targetTrack++;
      guard++;
    }
    if (guard >= 32) {
      throw new Error(`Could not find a clear track for "${p.name}" after checking 32 candidates — aborting.`);
    }
    claimed.push({ track: targetTrack, start: p.startTicks, end: p.endTicks });
    targets.push(targetTrack);
  }

  // Last-line defense, right before the caller writes: re-read each chosen track with the
  // strict lookup and re-check every placement on it. The timeline can change during the
  // awaits above; if it did, abort instead of trusting the snapshot.
  for (const t of new Set(targets)) {
    if (t >= trackCount) continue;
    let spans;
    try {
      spans = await readTrackSpans(seq, t, ppro);
    } catch (e) {
      throw new Error(
        `Could not verify V${t + 1} is empty before placing — ` +
        `aborting rather than risk overwriting real footage. (${e && e.message ? e.message : e})`
      );
    }
    for (let pIdx = 0; pIdx < placements.length; pIdx++) {
      if (targets[pIdx] !== t) continue;
      const p = placements[pIdx];
      const hit = firstOverlap(spans, p.startTicks, p.endTicks);
      if (hit) {
        throw new Error(
          `V${t + 1} changed while placing: "${await trackItemName(hit.it, "?")}" now overlaps "${p.name}" — ` +
          `aborting, nothing was placed. Try again.`
        );
      }
    }
  }
  return targets;
}

// Robust UXP timeline placement routine (supporting Adjustment Layers, Color Mattes, multi-clip cut transitions and separate clip spans)
async function placeMediaOnTimeline(ppro, options = {}) {
  const t0 = Date.now();
  // Per-phase timing: each mark records the ms spent since the previous one.
  const phases = {};
  let tLast = t0;
  const mark = (name) => { const now = Date.now(); phases[name] = now - tLast; tLast = now; };
  const { project, sequence: seq } = await activeProjectAndSequence(ppro, {
    sequenceErrorMessage: "Open a sequence in Premiere first.",
  });

  if (seq.name && typeof options.onSequenceName === "function") {
    options.onSequenceName(seq.name);
  }

  let sequenceWidth = null;
  let sequenceHeight = null;
  try {
    if (typeof seq.getSettings === "function") {
      const st = await seq.getSettings();
      const rect = st && typeof st.getVideoFrameRect === "function" ? await st.getVideoFrameRect() : null;
      if (rect && rect.width && rect.height) {
        sequenceWidth = rect.width;
        sequenceHeight = rect.height;
      }
    }
  } catch (_) {}

  const tpfStr = await seq.getTimebase();
  const tpf = toTicksOr(tpfStr, 10594584000n);

  let ctiTicks = 0n;
  try {
    const cti = await seq.getPlayerPosition();
    ctiTicks = toTicksOr(cti, 0n);
  } catch (_) {
    ctiTicks = 0n;
  }

  const frames = BigInt(options.frames || 16);
  const clamp = options.clamp !== undefined ? options.clamp : true;
  const effectName = options.effectName || "";
  const mode = options.mode || "span";
  const isMatte = options.mediaType === "matte";
  const layerTitle = isMatte ? "Color Matte" : "Adjustment Layer";

  // Check if user has clips selected on timeline
  mark('setup');
  const selectedClips = await getSelectedVideoClips(ppro, seq);
  const rawClipsWithTimes = [];
  for (const sc of selectedClips) {
    try {
      const it = sc.item;
      const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
      const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
      const sTicks = toTicksOr(sTime, 0n);
      const eTicks = toTicksOr(eTime, 0n);
      if (eTicks > sTicks) {
        rawClipsWithTimes.push({ track: sc.track, startTicks: sTicks, endTicks: eTicks });
      }
    } catch (_) {}
  }

  const clipsWithTimes = resolveTopLayer(rawClipsWithTimes);

  let inTicks = 0n;
  let outTicks = 0n;
  if (clipsWithTimes.length === 0) {
    try {
      const inPoint = await seq.getInPoint();
      const outPoint = await seq.getOutPoint();
      inTicks = toTicksOr(inPoint, 0n);
      outTicks = toTicksOr(outPoint, 0n);
    } catch (_) {}
  }

  mark('select');
  const placements = planPlacements({
    mode,
    spans: clipsWithTimes,
    frames,
    tpf,
    cti: ctiTicks,
    clamp,
    effectName,
    inPoint: inTicks,
    outPoint: outTicks,
  });

  const tickTime = makeTickTime(ppro);
  if (!tickTime) throw new Error("Could not initialize Premiere TickTime constructor.");

  let mediaItem = isMatte
    ? await findColorMatteItem(project, seq, ppro)
    : await findAdjustmentLayerItem(project, seq, ppro);

  let createdItemName = null;
  if (!mediaItem) {
    if (!sequenceWidth || !sequenceHeight) {
      throw new Error(
        `No ${layerTitle} found, and this sequence's frame size couldn't be read to create one. ` +
        `Create one by hand: File > New Item > ${layerTitle}, then drag it into Project panel > CutDeck > ADJ & FX.`
      );
    }
    const tpfNumber = Number(tpf);
    mediaItem = isMatte
      ? await createColorMatteForSequence(project, sequenceWidth, sequenceHeight, Number.isSafeInteger(tpfNumber) ? tpfNumber : null)
      : await createAdjustmentLayerForSequence(project, sequenceWidth, sequenceHeight, Number.isSafeInteger(tpfNumber) ? tpfNumber : null);
    createdItemName = mediaItem.name;
  }

  let clipItem = mediaItem;
  if (typeof mediaItem.getProjectItem === "function") {
    clipItem = await mediaItem.getProjectItem();
  }
  // createOverwriteItemAction rejects a ClipProjectItem.cast(...) object ("Invalid
  // parameter", TODO_LEDGER.md native rough-cut run 1) — place the plain item. The cast
  // is kept only for the ClipProjectItem-only calls (in/out marks, color label).
  const placeItem = clipItem;
  if (ppro.ClipProjectItem && typeof ppro.ClipProjectItem.cast === "function") {
    try {
      const casted = ppro.ClipProjectItem.cast(clipItem);
      if (casted) clipItem = casted;
    } catch (_) {}
  }

  const targetTracksSet = new Set();
  const placedItems = [];
  let placedCount = 0;

  mark('plan');
  if (!ppro.SequenceEditor || typeof ppro.SequenceEditor.getEditor !== "function") {
    throw new Error("SequenceEditor is not supported in this Premiere build.");
  }
  const freshProject = await ppro.Project.getActiveProject();
  const freshSeq = await freshProject.getActiveSequence();
  const targets = await pickPlacementTracks(ppro, freshSeq, placements);

  // Undo steps: per distinct length, one "set length" step, then one step placing every
  // layer of that length. The length (the item's In/Out marks) must be its OWN transaction,
  // committed before the overwrite is built (TODO_LEDGER.md P2).
  mark('gate');
  const groups = new Map();
  placements.forEach((p, i) => {
    const d = p.endTicks - p.startTicks;
    if (!groups.has(d)) groups.set(d, []);
    groups.get(d).push(i);
  });

  const trackCountBefore = await freshSeq.getVideoTrackCount();
  const renumber = new Map();
  for (const idxs of groups.values()) {
    for (const i of [...idxs].sort((x, y) => targets[x] - targets[y])) {
      const t = targets[i];
      if (t >= trackCountBefore && !renumber.has(t)) renumber.set(t, trackCountBefore + renumber.size);
    }
  }
  for (let i = 0; i < targets.length; i++) {
    if (renumber.has(targets[i])) targets[i] = renumber.get(targets[i]);
  }
  targetTracksSet.clear();
  for (const t of targets) targetTracksSet.add(t + 1);

  const editor = await ppro.SequenceEditor.getEditor(freshSeq);
  const placeAll = (label, idxs) => runTransaction(freshProject, label, (compound) => {
    if (!placeItem) throw new Error(`No ${layerTitle} item was available to place.`);
    for (const i of idxs) {
      const tStart = tickTime(placements[i].startTicks);
      const track = Number(targets[i]);
      let action = null;
      let lastErr = null;
      for (const fn of [
        () => editor.createOverwriteItemAction(placeItem, tStart, track, -1),
        () => editor.createOverwriteItemAction(placeItem, tStart, track, 0),
      ]) {
        try {
          action = fn();
          if (action) break;
        } catch (e) {
          lastErr = e;
        }
      }
      if (!action) {
        const name = placeItem?.name || mediaItem?.name || "unknown";
        throw new Error(`Could not place: ${lastErr ? (lastErr.message || String(lastErr)) : "Invalid parameter"}. (Item: "${name}", V-Track: V${track + 1})`);
      }
      if (!compound.addAction(action)) {
        throw new Error("addAction returned false");
      }
    }
  });

  let colorPending = true;
  let trackCount = trackCountBefore;
  for (const [durTicks, idxs] of groups) {
    try {
      if (!clipItem || typeof clipItem.createSetInOutPointsAction !== "function") {
        throw new Error(`the ${layerTitle} item has no In/Out call`);
      }
      runTransaction(freshProject, `CutDeck: Set ${layerTitle} Length`, (compound) => {
        const inOut = clipItem.createSetInOutPointsAction(tickTime(0n), tickTime(durTicks));
        if (!inOut || !compound.addAction(inOut)) throw new Error("In/Out action was rejected");
        if (colorPending && typeof clipItem.createSetColorLabelAction === "function") {
          const colorAction = clipItem.createSetColorLabelAction(getLabelIndex(options.color));
          if (colorAction) compound.addAction(colorAction);
        }
      });
      colorPending = false;
    } catch (e) {
      throw new Error(
        `Could not set the ${layerTitle} length — stopped before placing this batch, so no footage ` +
        `was overwritten. (${e && e.message ? e.message : e})`
      );
    }

    // One placement per new track, in track order, each its own transaction.
    const rest = [];
    for (const i of [...idxs].sort((a, b) => targets[a] - targets[b])) {
      if (targets[i] === trackCount) {
        placeAll(`CutDeck: Place ${layerTitle} (new track)`, [i]);
        trackCount++;
      } else {
        rest.push(i);
      }
    }
    if (rest.length) placeAll(`CutDeck: Place ${rest.length} ${layerTitle}(s)`, rest);
  }

  mark('commit');
  // Verify every placement and read back its length.
  // RAM & Efficiency Optimization: Pre-read each unique target track ONCE in parallel instead of
  // re-reading the entire track list inside the N placements loop (O(N) instead of O(N^2)).
  const seqAfter = await freshProject.getActiveSequence();
  const uniqueTargetTracks = Array.from(new Set(targets));
  const trackCache = new Map();
  await Promise.all(uniqueTargetTracks.map(async (t) => {
    try {
      const targetTrackObj = await seqAfter.getVideoTrack(Number(t));
      const trackItems = targetTrackObj ? await getTrackClipItems(targetTrackObj, ppro) : [];
      const spans = await Promise.all((trackItems || []).map(async (it) => {
        try {
          const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
          const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
          return { it, sTicks: toTicksOr(sTime, 0n), eTicks: toTicksOr(eTime, null) };
        } catch (_) {
          return null;
        }
      }));
      trackCache.set(t, spans.filter(Boolean));
    } catch (e) {
      console.log(`CutDeck: could not cache items for V${t + 1}:`, e);
      trackCache.set(t, []);
    }
  }));

  for (let pIdx = 0; pIdx < placements.length; pIdx++) {
    const p = placements[pIdx];
    const targetTrack = targets[pIdx];
    let verified = false;
    let lengthErr = null;
    const itemsOnTrack = trackCache.get(targetTrack) || [];
    for (const itemData of itemsOnTrack) {
      const diff = itemData.sTicks > p.startTicks ? (itemData.sTicks - p.startTicks) : (p.startTicks - itemData.sTicks);
      if (diff <= (tpf * 2n)) {
        if (itemData.eTicks !== null && itemData.eTicks > p.endTicks + tpf) {
          lengthErr = new Error(
            `The ${layerTitle} on V${targetTrack + 1} came out longer than asked and may ` +
            `cover footage past its range. Undo this placement (Edit > Undo History) and check ` +
            `the timeline. (end ${itemData.eTicks} vs ${p.endTicks} ticks)`
          );
        }
        if (itemData.eTicks === null) console.log(`${layerTitle} length unreadable on V` + (targetTrack + 1));
        verified = true;
        placedItems.push(itemData.it);
        break;
      }
    }
    if (lengthErr) throw lengthErr;

    if (!verified) {
      throw new Error(
        `Placed ${layerTitle}s but could not find the one for V${targetTrack + 1} afterward — ` +
        `the edit may have landed on the wrong track. Undo this placement (Edit > Undo History) ` +
        `and check the timeline before placing more.`
      );
    }

    placedCount++;
  }

  // Release cache map to reclaim memory immediately
  trackCache.clear();

  mark('verify');
  console.log(`CutDeck: placed ${placedCount} ${layerTitle}(s) in ${Date.now() - t0} ms`, phases);
  return {
    success: true,
    placedCount,
    targetTrack: Array.from(targetTracksSet).join(", "),
    frames: Number(frames),
    mode,
    mediaType: isMatte ? "matte" : "adj",
    cutCount: mode === "transition" ? placedCount : 0,
    selectedCount: clipsWithTimes.length,
    sequenceWidth,
    sequenceHeight,
    createdAdjustmentLayer: isMatte ? null : createdItemName,
    createdColorMatte: isMatte ? createdItemName : null,
    placedItems
  };
}

function placeAdjustmentLayersOnTimeline(ppro, options = {}) {
  return placeMediaOnTimeline(ppro, { ...options, mediaType: "adj" });
}

function placeColorMattesOnTimeline(ppro, options = {}) {
  return placeMediaOnTimeline(ppro, { ...options, mediaType: "matte" });
}

module.exports = {
  placeAdjustmentLayersOnTimeline,
  placeColorMattesOnTimeline,
  placeMediaOnTimeline,
  findAdjustmentLayerItem,
  findColorMatteItem,
  getOrCreateAdjBin,
  pickBestCandidate,
  detectResolutionFromMetadata,
  createAdjustmentLayerForSequence,
  createColorMatteForSequence,
  flattenImportWrappers,
  writeTempFile,
  // Exported for timeline/effects.js: the robust (never-throws) getTrackItems lookup, reused
  // rather than re-guessed — see that module's getSelectedTrackItems.
  getTrackClipItems,
  resolveTopLayer,
  planPlacements,
  assignPlacementLanes,
  pickPlacementTracks,
  getLabelIndex,
  CUTDECK_BIN_NAME,
  ADJ_BIN_NAME,
};
