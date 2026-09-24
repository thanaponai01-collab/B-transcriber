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
  writeTempFile,
  createAdjustmentLayerForSequence,
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

// Robust UXP helper to determine collision-free track using Smart Stacking
async function findSmartStackTrack(seq, startTicks, endTicks, minTrack = 1, ppro) {
  const trackCount = await seq.getVideoTrackCount();
  let highestOccupied = 0;
  for (let v = 0; v < trackCount; v++) {
    const track = await seq.getVideoTrack(v);
    let items;
    try {
      items = await getTrackClipItemsOrThrow(track, ppro);
    } catch (e) {
      // Could not verify V(v+1) is actually empty — assume it's occupied rather than
      // risk overwriting real clips we failed to see (see getTrackClipItemsOrThrow).
      console.log(`findSmartStackTrack: could not read V${v + 1} items, assuming occupied:`, e);
      if (v > highestOccupied) highestOccupied = v;
      continue;
    }
    if (items && items.length > 0) {
      for (const it of items) {
        const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
        const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
        const itIn = toTicksOr(sTime, 0n);
        const itOut = toTicksOr(eTime, 0n);
        if (itOut > startTicks && itIn < endTicks) {
          console.log(`findSmartStackTrack: V${v + 1} collides with query [${startTicks},${endTicks}) — ` +
            `item "${await trackItemName(it, "?")}" is [${itIn},${itOut})`);
          if (v > highestOccupied) highestOccupied = v;
          break;
        }
      }
    }
  }

  let candidate = Math.max(minTrack, highestOccupied + 1);

  // Refine past any occupied track using the exact intended span, same as the scan
  // above. (Previously padded to a 5s "safety window" to cover the placed clip's
  // untrimmed default duration — that's now confirmed unnecessary: the caller's own
  // hard gate + the In/Out marks reliably land each placement at its exact span before
  // the next one is ever checked, so padding here only fragmented adjacent short
  // clips onto separate tracks instead of letting them share one.)
  while (candidate < trackCount) {
    const track = await seq.getVideoTrack(candidate);
    let items;
    let trackHasCollision = false;
    try {
      items = await getTrackClipItemsOrThrow(track, ppro);
    } catch (e) {
      console.log(`findSmartStackTrack: could not read V${candidate + 1} items during safety scan, assuming occupied:`, e);
      candidate++;
      continue;
    }
    if (items && items.length > 0) {
      for (const it of items) {
        const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
        const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
        const itIn = toTicksOr(sTime, 0n);
        const itOut = toTicksOr(eTime, 0n);
        if (itOut > startTicks && itIn < endTicks) {
          console.log(`findSmartStackTrack: V${candidate + 1} collides with query [${startTicks},${endTicks}) during refine — ` +
            `item "${await trackItemName(it, "?")}" is [${itIn},${itOut})`);
          trackHasCollision = true;
          break;
        }
      }
    }
    if (!trackHasCollision) {
      break;
    }
    candidate++;
  }
  return candidate;
}

// Last-line defense, called immediately before the destructive action: re-reads the
// exact target track/span with the strict (throw-on-unreadable) item lookup, right
// before we commit to overwriting it. findSmartStackTrack's picks have been wrong in
// practice, so this does not trust that result — it verifies it, one more time, with
// nothing able to happen in between.
async function isTrackRangeClear(seq, trackIndex, startTicks, endTicks, ppro) {
  const trackCount = await seq.getVideoTrackCount();
  if (trackIndex >= trackCount) return true; // track doesn't exist yet — nothing to collide with
  const track = await seq.getVideoTrack(trackIndex);
  const items = await getTrackClipItemsOrThrow(track, ppro);
  for (const it of items) {
    const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
    const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
    const itIn = toTicksOr(sTime, 0n);
    const itOut = toTicksOr(eTime, 0n);
    if (itOut > startTicks && itIn < endTicks) {
      console.log(`isTrackRangeClear: V${trackIndex + 1} collides with query [${startTicks},${endTicks}) — ` +
        `item "${await trackItemName(it, "?")}" is [${itIn},${itOut})`);
      return false;
    }
  }
  return true;
}

// Robust UXP timeline placement routine (supporting multi-clip cut transitions and separate clip spans)
async function placeAdjustmentLayersOnTimeline(ppro, options = {}) {
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

  let alItem = await findAdjustmentLayerItem(project, seq, ppro);
  let createdAdjustmentLayer = null;
  if (!alItem) {
    if (!sequenceWidth || !sequenceHeight) {
      throw new Error(
        "No Adjustment Layer found, and this sequence's frame size couldn't be read to create one. " +
        "Create one by hand: File > New Item > Adjustment Layer, then drag it into Project panel > CutDeck > ADJ & FX."
      );
    }
    const tpfNumber = Number(tpf);
    alItem = await createAdjustmentLayerForSequence(
      project, sequenceWidth, sequenceHeight, Number.isSafeInteger(tpfNumber) ? tpfNumber : null);
    createdAdjustmentLayer = alItem.name;
  }

  let clipItem = alItem;
  if (typeof alItem.getProjectItem === "function") {
    clipItem = await alItem.getProjectItem();
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

  // Pick one track per LANE (see assignPlacementLanes), clear across every
  // placement's span in that lane, not per-placement. This project can have real
  // footage on tracks above V1 partway through the timeline (confirmed: a real
  // clip sits on V2 mid-timeline in this project) — recomputing per placement
  // means a placement over that stretch gets bumped to a higher track while
  // others elsewhere don't, fragmenting one batch across many tracks for no
  // reason. Scanning the union of a lane's planned spans finds a track
  // guaranteed clear of whatever real content exists anywhere in that range, and
  // every placement in that lane shares it.
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
  mark('plan');
  const laneOf = assignPlacementLanes(placements);
  const laneCount = placements.length > 0 ? Math.max(...laneOf) + 1 : 0;
  const laneTracks = new Array(laneCount).fill(1);

  if (placements.length > 0) {
    const batchProject = await ppro.Project.getActiveProject();
    const batchSeq = await batchProject.getActiveSequence();

    let floorTrack = 1;
    for (let lane = 0; lane < laneCount; lane++) {
      const laneIdxs = [];
      for (let i = 0; i < placements.length; i++) {
        if (laneOf[i] === lane) laneIdxs.push(i);
      }
      let unionStart = placements[laneIdxs[0]].startTicks;
      let unionEnd = placements[laneIdxs[0]].endTicks;
      for (const i of laneIdxs) {
        if (placements[i].startTicks < unionStart) unionStart = placements[i].startTicks;
        if (placements[i].endTicks > unionEnd) unionEnd = placements[i].endTicks;
      }
      let laneTrack = await findSmartStackTrack(batchSeq, unionStart, unionEnd, floorTrack, ppro);

      // The union scan is a starting guess. Verify it against every individual
      // placement's own exact span in this lane before placing anything — keep
      // bumping and re-checking the whole lane until one track clears all of
      // them, so the lane always lands on a single track instead of splitting
      // when one placement's own narrow span still collides with something the
      // union-level check didn't isolate precisely enough.
      let laneGuard = 0;
      outer:
      while (laneGuard < 32) {
        for (const i of laneIdxs) {
          const p = placements[i];
          let clear;
          try {
            clear = await isTrackRangeClear(batchSeq, laneTrack, p.startTicks, p.endTicks, ppro);
          } catch (e) {
            throw new Error(
              `Could not verify V${laneTrack + 1} is empty for a group of overlapping cut transitions — ` +
              `aborting rather than risk overwriting real footage. (${e && e.message ? e.message : e})`
            );
          }
          if (!clear) {
            laneTrack++;
            laneGuard++;
            continue outer;
          }
        }
        break; // every placement in this lane cleared this track
      }
      if (laneGuard >= 32) {
        throw new Error("Could not find a track clear for a group of overlapping cut transitions after checking 32 candidates — aborting.");
      }

      laneTracks[lane] = laneTrack;
      // Next lane must stack strictly above this one: lanes exist specifically
      // because their placements overlap each other in time, so two lanes must
      // never be allowed to share a track regardless of what findSmartStackTrack
      // would otherwise pick.
      floorTrack = laneTrack + 1;
    }
  }

  if (!ppro.SequenceEditor || typeof ppro.SequenceEditor.getEditor !== "function") {
    throw new Error("SequenceEditor is not supported in this Premiere build.");
  }
  const freshProject = await ppro.Project.getActiveProject();
  const freshSeq = await freshProject.getActiveSequence();

  mark('laneScan');
  // Hard gate, for every placement BEFORE anything is committed: the exact span must be
  // clear on its lane's track, and must not overlap another placement already claimed
  // for that track in this run (they all land in one transaction below, so the sequence
  // is not re-read in between). Normally the lane's track is already clear — it only
  // walks further if content showed up that the lane scan didn't isolate.
  const claimed = [];
  const targets = [];
  for (let pIdx = 0; pIdx < placements.length; pIdx++) {
    const p = placements[pIdx];
    let targetTrack = laneTracks[laneOf[pIdx]];
    let guard = 0;
    while (guard < 32) {
      let clear;
      try {
        clear = await isTrackRangeClear(freshSeq, targetTrack, p.startTicks, p.endTicks, ppro);
      } catch (e) {
        throw new Error(
          `Could not verify V${targetTrack + 1} is empty before placing "${p.name}" — ` +
          `aborting rather than risk overwriting real footage. (${e && e.message ? e.message : e})`
        );
      }
      const collides = claimed.some((c) => c.track === targetTrack && c.start < p.endTicks && p.startTicks < c.end);
      if (clear && !collides) break;
      targetTrack++;
      guard++;
    }
    if (guard >= 32) {
      throw new Error(`Could not find a clear track for "${p.name}" after checking 32 candidates — aborting.`);
    }
    claimed.push({ track: targetTrack, start: p.startTicks, end: p.endTicks });
    targets.push(targetTrack);
    targetTracksSet.add(targetTrack + 1);
  }

  // Undo steps: per distinct AL length, one "set length" step, then one step placing every
  // AL of that length. The length (the AL item's In/Out marks) must be its OWN transaction,
  // committed before the overwrite is built — in one compound the overwrite still reads the
  // old marks (TODO_LEDGER.md P2; confirmed 2026-09-21 it destroyed real footage). So
  // "every cut" mode (one length) is 2 Ctrl+Z, plus 1 per new track it has to create;
  // span / per-clip add 2 per distinct length.
  mark('gate');
  const groups = new Map();
  placements.forEach((p, i) => {
    const d = p.endTicks - p.startTicks;
    if (!groups.has(d)) groups.set(d, []);
    groups.get(d).push(i);
  });
  // Premiere has no add-track call: a track is created only by placing onto the index
  // equal to the current track count, one track at a time. Several placements onto
  // not-yet-existing tracks in ONE transaction failed live (2026-09-24: "could not find
  // the one for V10"). So renumber new tracks to follow on from the last existing one,
  // create each with its own single placement, then batch everything else.
  const trackCountBefore = await freshSeq.getVideoTrackCount();
  // Numbers are handed out in the order the commit loop below reaches them, so every
  // new track is exactly the current track count when its first placement lands.
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
    if (!placeItem) throw new Error("No Adjustment Layer item was available to place.");
    for (const i of idxs) {
      const tStart = tickTime(placements[i].startTicks);
      const track = Number(targets[i]);
      // Overwrite only: an index equal to the track count creates the track (proven by
      // the Sync probe). No ripple insert — it would shift clips after tStart.
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
        const name = placeItem?.name || alItem?.name || "unknown";
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
    // The length must land before placing: an overwrite with the old marks can run past the
    // range checked clear and overwrite footage (TODO_LEDGER.md P2). So refuse, don't skip.
    try {
      if (!clipItem || typeof clipItem.createSetInOutPointsAction !== "function") {
        throw new Error("the Adjustment Layer item has no In/Out call");
      }
      runTransaction(freshProject, "CutDeck: Set Adjustment Layer Length", (compound) => {
        const inOut = clipItem.createSetInOutPointsAction(tickTime(0n), tickTime(durTicks));
        if (!inOut || !compound.addAction(inOut)) throw new Error("In/Out action was rejected");
        // The color label is on the same shared project item — ride along once per run.
        if (colorPending && typeof clipItem.createSetColorLabelAction === "function") {
          const colorAction = clipItem.createSetColorLabelAction(getLabelIndex(options.color));
          if (colorAction) compound.addAction(colorAction);
        }
      });
      colorPending = false;
    } catch (e) {
      throw new Error(
        `Could not set the Adjustment Layer length — stopped before placing this batch, so no footage ` +
        `was overwritten. (${e && e.message ? e.message : e})`
      );
    }

    // One placement per new track, in track order, each its own transaction.
    const rest = [];
    for (const i of [...idxs].sort((a, b) => targets[a] - targets[b])) {
      if (targets[i] === trackCount) {
        placeAll("CutDeck: Place Adjustment Layer (new track)", [i]);
        trackCount++;
      } else {
        rest.push(i);
      }
    }
    if (rest.length) placeAll(`CutDeck: Place ${rest.length} Adjustment Layer(s)`, rest);
  }

  mark('commit');
  // Verify every placement and read back its length. No trim step: the In/Out marks
  // already set the exact length, and TrackItem.createSetEndAction throws "script object
  // is no longer valid" (TODO_LEDGER.md native rough-cut run 1).
  const seqAfter = await freshProject.getActiveSequence();
  for (let pIdx = 0; pIdx < placements.length; pIdx++) {
    const p = placements[pIdx];
    const targetTrack = targets[pIdx];
    let verified = false;
    let lengthErr = null;
    try {
      const targetTrackObj = await seqAfter.getVideoTrack(Number(targetTrack));
      const trackItems = targetTrackObj ? await getTrackClipItems(targetTrackObj, ppro) : [];
      for (const it of trackItems || []) {
        const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
        const sTicks = toTicksOr(sTime, 0n);
        const diff = sTicks > p.startTicks ? (sTicks - p.startTicks) : (p.startTicks - sTicks);
        if (diff <= (tpf * 2n)) {
          let actualEndTicks = null;
          try {
            const eTimeAfter = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
            actualEndTicks = toTicksOr(eTimeAfter, null);
          } catch (_) {}
          if (actualEndTicks !== null && actualEndTicks > p.endTicks + tpf) {
            lengthErr = new Error(
              `The Adjustment Layer on V${targetTrack + 1} came out longer than asked and may ` +
              `cover footage past its range. Undo this placement (Edit > Undo History) and check ` +
              `the timeline. (end ${actualEndTicks} vs ${p.endTicks} ticks)`
            );
          }
          if (actualEndTicks === null) console.log("Adjustment Layer length unreadable on V" + (targetTrack + 1));
          verified = true;
          placedItems.push(it);
          break;
        }
      }
    } catch (err) {
      console.log("Adjustment Layer placement check failed:", err);
    }
    if (lengthErr) throw lengthErr;

    if (!verified) {
      throw new Error(
        `Placed Adjustment Layers but could not find the one for V${targetTrack + 1} afterward — ` +
        `the edit may have landed on the wrong track. Undo this placement (Edit > Undo History) ` +
        `and check the timeline before placing more.`
      );
    }

    placedCount++;
  }

  mark('verify');
  console.log(`CutDeck: placed ${placedCount} Adjustment Layer(s) in ${Date.now() - t0} ms`, phases);
  return {
    success: true,
    placedCount,
    targetTrack: Array.from(targetTracksSet).join(", "),
    frames: Number(frames),
    mode,
    cutCount: mode === "transition" ? placedCount : 0,
    selectedCount: clipsWithTimes.length,
    sequenceWidth,
    sequenceHeight,
    createdAdjustmentLayer,
    placedItems
  };
}

module.exports = {
  placeAdjustmentLayersOnTimeline,
  findAdjustmentLayerItem,
  getOrCreateAdjBin,
  pickBestCandidate,
  detectResolutionFromMetadata,
  createAdjustmentLayerForSequence,
  flattenImportWrappers,
  writeTempFile,
  // Exported for timeline/effects.js: the robust (never-throws) getTrackItems lookup, reused
  // rather than re-guessed — see that module's getSelectedTrackItems.
  getTrackClipItems,
  resolveTopLayer,
  planPlacements,
  assignPlacementLanes,
  findSmartStackTrack,
  isTrackRangeClear,
  getLabelIndex,
  CUTDECK_BIN_NAME,
  ADJ_BIN_NAME,
};
