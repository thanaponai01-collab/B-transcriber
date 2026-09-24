// CutDeck Add Frame Hold — places a freeze frame on the track above the playhead
// while leaving the underlying clip completely untouched for its full duration.
// Designed for the workflow: "1 clip 5s, pick 2s, add frame hold -> hold frame up 1 layer, clip stays 5s".

const { toTicksOr, makeTickTime, TICKS_PER_SECOND } = require("../host/ticks.js");
const {
  CUTDECK_BIN_NAME,
  runTransaction,
  activeProjectAndSequence,
  getOrCreateBin,
  asBinLike,
} = require("../host/project.js");
const {
  getTrackClipItems,
  getTrackClipItemsOrThrow,
  getSelectedVideoClips,
  trackItemName,
} = require("../host/trackItems.js");

const FRAME_HOLD_BIN_NAME = "Frame Holds";

async function getOrCreateFrameHoldBin(project) {
  return getOrCreateBin(project, [CUTDECK_BIN_NAME, FRAME_HOLD_BIN_NAME]);
}

// Finds the video clip at or spanning ctiTicks
async function findClipAtPlayhead(ppro, seq, ctiTicks) {
  // 1. If clips are selected, prioritize selected video clips
  try {
    const selected = await getSelectedVideoClips(ppro, seq);
    if (selected && selected.length > 0) {
      for (const sc of selected) {
        const it = sc.item;
        const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
        const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
        const sTicks = toTicksOr(sTime, 0n);
        const eTicks = toTicksOr(eTime, 0n);
        if (sTicks <= ctiTicks && ctiTicks < eTicks) {
          return { item: it, track: sc.track, startTicks: sTicks, endTicks: eTicks };
        }
      }
      // If selected clip doesn't span CTI, use the first selected clip
      const first = selected[0];
      const sTime = typeof first.item.getStartTime === "function" ? await first.item.getStartTime() : first.item.startTime;
      const eTime = typeof first.item.getEndTime === "function" ? await first.item.getEndTime() : first.item.endTime;
      return {
        item: first.item,
        track: first.track,
        startTicks: toTicksOr(sTime, 0n),
        endTicks: toTicksOr(eTime, 0n),
      };
    }
  } catch (_) {}

  // 2. Scan video tracks from highest to lowest to find the visible clip under CTI
  const trackCount = typeof seq.getVideoTrackCount === "function" ? await seq.getVideoTrackCount() : 0;
  for (let v = trackCount - 1; v >= 0; v--) {
    try {
      const track = await seq.getVideoTrack(v);
      const items = await getTrackClipItems(track, ppro);
      for (const it of items || []) {
        if (!it) continue;
        if (typeof it.isAdjustmentLayer === "function") {
          try { if (await it.isAdjustmentLayer()) continue; } catch (_) {}
        }
        const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
        const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
        const sTicks = toTicksOr(sTime, 0n);
        const eTicks = toTicksOr(eTime, 0n);
        if (sTicks <= ctiTicks && ctiTicks < eTicks) {
          return { item: it, track: v, startTicks: sTicks, endTicks: eTicks };
        }
      }
    } catch (_) {}
  }

  return null;
}

// Checks if a track span is clear of other clips
async function isTrackSpanClear(seq, trackIndex, startTicks, endTicks, ppro) {
  try {
    const trackCount = await seq.getVideoTrackCount();
    if (trackIndex >= trackCount) return true; // Beyond current track count creates track, so clear
    const track = await seq.getVideoTrack(trackIndex);
    const items = await getTrackClipItemsOrThrow(track, ppro);
    for (const it of items || []) {
      const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
      const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
      const s = toTicksOr(sTime, 0n);
      const e = toTicksOr(eTime, 0n);
      if (e > startTicks && s < endTicks) return false;
    }
    return true;
  } catch (_) {
    return false;
  }
}

// Adds a frame hold 1 layer above the clip under the playhead
async function addFrameHold(ppro, options = {}) {
  const t0 = Date.now();
  const { project, sequence: seq } = await activeProjectAndSequence(ppro, {
    sequenceErrorMessage: "Open a sequence in Premiere first.",
  });

  const tpfStr = await seq.getTimebase();
  const tpf = toTicksOr(tpfStr, 10594584000n);

  let ctiTicks = 0n;
  let ctiTime = null;
  try {
    ctiTime = await seq.getPlayerPosition();
    ctiTicks = toTicksOr(ctiTime, 0n);
  } catch (_) {
    throw new Error("Could not read playhead position.");
  }

  // Find clip at playhead
  const clip = await findClipAtPlayhead(ppro, seq, ctiTicks);
  if (!clip) {
    throw new Error("No video clip found at the playhead. Place the playhead over a clip to freeze.");
  }

  const clipName = await trackItemName(clip.item, "Clip");

  // Determine hold start & duration
  const holdStartTicks = ctiTicks;
  let holdDurationTicks = clip.endTicks > ctiTicks ? (clip.endTicks - ctiTicks) : (tpf * 48n);
  if (holdDurationTicks <= 0n) holdDurationTicks = tpf * 48n; // fallback at least ~2 seconds
  const holdEndTicks = holdStartTicks + holdDurationTicks;

  // Determine target track: up 1 layer from the clip's track
  const sourceTrack = clip.track >= 0 ? clip.track : 0;
  let targetTrack = sourceTrack + 1;
  let guard = 0;
  while (guard < 32) {
    const clear = await isTrackSpanClear(seq, targetTrack, holdStartTicks, holdEndTicks, ppro);
    if (clear) break;
    targetTrack++;
    guard++;
  }
  if (guard >= 32) {
    throw new Error("Could not find a clear track for the frame hold above the clip.");
  }

  // Determine sequence frame size
  let width = 1920;
  let height = 1080;
  try {
    if (typeof seq.getSettings === "function") {
      const st = await seq.getSettings();
      const rect = st && typeof st.getVideoFrameRect === "function" ? await st.getVideoFrameRect() : null;
      if (rect && rect.width && rect.height) {
        width = Math.round(rect.width);
        height = Math.round(rect.height);
      }
    }
  } catch (_) {}

  // Export frame via Exporter.exportSequenceFrame
  if (!ppro.Exporter || typeof ppro.Exporter.exportSequenceFrame !== "function") {
    throw new Error("Exporter.exportSequenceFrame is not supported in this Premiere build.");
  }

  const uxp = require("uxp");
  const tempFolder = await uxp.storage.localFileSystem.getTemporaryFolder();
  const folderPath = tempFolder.nativePath;
  const fileName = `CutDeck_Hold_${Date.now()}.png`;

  const tickTime = makeTickTime(ppro);
  if (!tickTime) throw new Error("Could not initialize Premiere TickTime constructor.");

  const exported = await ppro.Exporter.exportSequenceFrame(
    seq,
    ctiTime,
    fileName,
    folderPath,
    width,
    height
  );
  if (!exported) {
    throw new Error("Premiere failed to export frame at playhead.");
  }

  // Import into CutDeck > Frame Holds bin
  const sep = folderPath.includes("\\") ? "\\" : "/";
  const fullPath = folderPath.endsWith(sep) ? (folderPath + fileName) : (folderPath + sep + fileName);

  const holdBin = asBinLike(await getOrCreateFrameHoldBin(project));
  const imported = await project.importFiles([fullPath], true, holdBin, false);
  console.log(`CutDeck FrameHold: importFiles(${fullPath}) returned`, imported);

  // Locate imported item in bin
  const baseName = fileName.replace(/\.png$/i, "");
  const items = (await holdBin.getItems()) || [];
  const holdItem = items.find((it) => it.type !== 2 && (it.name === fileName || it.name === baseName));
  if (!holdItem) {
    throw new Error(`Exported frame "${fileName}" was imported but could not be located in CutDeck > ${FRAME_HOLD_BIN_NAME}.`);
  }

  let clipItem = holdItem;
  if (typeof holdItem.getProjectItem === "function") {
    clipItem = await holdItem.getProjectItem();
  }
  const placeItem = clipItem;
  if (ppro.ClipProjectItem && typeof ppro.ClipProjectItem.cast === "function") {
    try {
      const casted = ppro.ClipProjectItem.cast(clipItem);
      if (casted) clipItem = casted;
    } catch (_) {}
  }

  // Set In/Out duration in its own transaction (Rule: P2 marks committed before overwrite)
  if (clipItem && typeof clipItem.createSetInOutPointsAction === "function") {
    runTransaction(project, "CutDeck: Set Frame Hold Duration", (compound) => {
      const inOut = clipItem.createSetInOutPointsAction(tickTime(0n), tickTime(holdDurationTicks));
      if (inOut) compound.addAction(inOut);
    });
  }

  // Place on target track (up 1 layer)
  if (!ppro.SequenceEditor || typeof ppro.SequenceEditor.getEditor !== "function") {
    throw new Error("SequenceEditor is not supported in this Premiere build.");
  }
  const editor = await ppro.SequenceEditor.getEditor(seq);

  runTransaction(project, "CutDeck: Place Frame Hold", (compound) => {
    let action = null;
    let lastErr = null;
    for (const fn of [
      () => editor.createOverwriteItemAction(placeItem, tickTime(holdStartTicks), targetTrack, -1),
      () => editor.createOverwriteItemAction(placeItem, tickTime(holdStartTicks), targetTrack, 0),
    ]) {
      try {
        action = fn();
        if (action) break;
      } catch (e) {
        lastErr = e;
      }
    }
    if (!action) {
      throw new Error(`Could not place frame hold on V${targetTrack + 1}: ${lastErr ? (lastErr.message || String(lastErr)) : "Action rejected"}`);
    }
    if (!compound.addAction(action)) {
      throw new Error("addAction(place frame hold) returned false");
    }
  });

  const holdSecs = (Number(holdDurationTicks) / Number(TICKS_PER_SECOND)).toFixed(1);
  console.log(`CutDeck: placed Frame Hold on V${targetTrack + 1} (${holdSecs}s) in ${Date.now() - t0} ms`);

  return {
    success: true,
    clipName,
    sourceTrack: sourceTrack + 1,
    targetTrack: targetTrack + 1,
    holdDurationTicks,
    holdSecs,
  };
}

module.exports = {
  addFrameHold,
  findClipAtPlayhead,
  getOrCreateFrameHoldBin,
  FRAME_HOLD_BIN_NAME,
};
