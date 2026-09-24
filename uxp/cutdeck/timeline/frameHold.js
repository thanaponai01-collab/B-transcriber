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

// Locates the imported frame item across the project with retries for asynchronous indexing,
// checking the Frame Holds bin, the project root bin, and any sub-bins.
// If found outside the Frame Holds bin, moves it into Frame Holds via transaction.
async function locateAndOrganizeImportedHoldItem(project, rawHoldBin, folderBin, fileName, fullPath, ppro) {
  const baseName = fileName.replace(/\.[^.]+$/, "");
  const tsMatch = fileName.match(/CutDeck_Hold_(\d+)/);
  const timestampStr = tsMatch ? tsMatch[1] : "";

  function matchesItem(it) {
    if (!it || it.type === 2) return false;
    const n = it.name || "";
    if (n === fileName || n === baseName) return true;
    if (timestampStr && n.includes(timestampStr)) return true;
    if (n.startsWith("CutDeck_Hold_") && n.includes(baseName)) return true;
    return false;
  }

  async function getBinItems(bin) {
    if (!bin) return [];
    if (typeof bin.getItems === "function") {
      try { return (await bin.getItems()) || []; } catch (_) {}
    }
    const b = asBinLike(bin);
    if (b && typeof b.getItems === "function") {
      try { return (await b.getItems()) || []; } catch (_) {}
    }
    return [];
  }

  async function searchFolderRecursive(bin) {
    const items = await getBinItems(bin);
    for (const it of items) {
      if (matchesItem(it)) return { item: it, parent: bin };
      if (it.type === 2) {
        const found = await searchFolderRecursive(it);
        if (found) return found;
      }
    }
    return null;
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  let located = null;
  // Retry loop: up to 6 attempts (0ms, 60ms, 120ms, 180ms, 240ms, 300ms) for async import indexing
  for (let attempt = 0; attempt < 6; attempt++) {
    if (attempt > 0) {
      await sleep(60);
    }

    // 1. Check inside CutDeck > Frame Holds bin directly
    const holdItems = await getBinItems(folderBin);
    const inHold = holdItems.find(matchesItem);
    if (inHold) {
      located = { item: inHold, parent: folderBin, inHoldBin: true };
      break;
    }

    // 2. Check rootItem directly (common Premiere fallback if targetBin was bypassed)
    let root = null;
    try { root = await project.getRootItem(); } catch (_) {}
    if (root) {
      const rootItems = await getBinItems(root);
      const inRoot = rootItems.find(matchesItem);
      if (inRoot) {
        located = { item: inRoot, parent: root, inHoldBin: false };
        break;
      }

      // 3. Search anywhere in project
      const anyMatch = await searchFolderRecursive(root);
      if (anyMatch) {
        const isAlreadyInHold = (anyMatch.parent === folderBin || anyMatch.parent === rawHoldBin || (anyMatch.parent && anyMatch.parent.name === FRAME_HOLD_BIN_NAME));
        located = { item: anyMatch.item, parent: anyMatch.parent, inHoldBin: isAlreadyInHold };
        break;
      }
    }
  }

  if (!located || !located.item) {
    return null;
  }

  // If found outside CutDeck > Frame Holds bin, move it in
  if (!located.inHoldBin && folderBin) {
    try {
      let moveTarget = located.item;
      if (ppro && ppro.ProjectItem && typeof ppro.ProjectItem.cast === "function") {
        try {
          const casted = ppro.ProjectItem.cast(moveTarget);
          if (casted) moveTarget = casted;
        } catch (_) {}
      }

      let sourceBin = located.parent;
      if (!sourceBin && typeof moveTarget.getParentBin === "function") {
        try { sourceBin = moveTarget.getParentBin(); } catch (_) {}
      }
      const sourceFolder = asBinLike(sourceBin);

      runTransaction(project, "CutDeck: move Frame Hold into bin", (compound) => {
        let moveAction = null;
        if (sourceFolder && typeof sourceFolder.createMoveItemAction === "function") {
          try { moveAction = sourceFolder.createMoveItemAction(moveTarget, folderBin); } catch (_) {}
        }
        if (!moveAction && typeof folderBin.createMoveItemAction === "function") {
          try { moveAction = folderBin.createMoveItemAction(moveTarget, folderBin); } catch (_) {}
        }
        if (moveAction) compound.addAction(moveAction);
      });
      console.log(`CutDeck: moved "${fileName}" into CutDeck > ${FRAME_HOLD_BIN_NAME}`);
    } catch (moveErr) {
      console.warn("CutDeck: could not move item to Frame Holds bin (will place on timeline anyway):", moveErr);
    }
  }

  return located.item;
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

  const rawHoldBin = await getOrCreateFrameHoldBin(project);
  const folderBin = asBinLike(rawHoldBin);

  // Cast target bin to ProjectItem if supported by Premiere Pro UXP
  let targetBinProjectItem = rawHoldBin;
  if (ppro.ProjectItem && typeof ppro.ProjectItem.cast === "function") {
    try {
      const casted = ppro.ProjectItem.cast(rawHoldBin);
      if (casted) targetBinProjectItem = casted;
    } catch (_) {}
  }

  const imported = await project.importFiles([fullPath], true, targetBinProjectItem, false);
  console.log(`CutDeck FrameHold: importFiles(${fullPath}) returned`, imported);

  // Locate imported item with retry loop and auto-move fallback
  const holdItem = await locateAndOrganizeImportedHoldItem(project, rawHoldBin, folderBin, fileName, fullPath, ppro);
  if (!holdItem) {
    throw new Error(`Exported frame "${fileName}" was imported but could not be located in project.`);
  }

  let clipItem = holdItem;
  if (typeof holdItem.getProjectItem === "function") {
    try {
      const p = await holdItem.getProjectItem();
      if (p) clipItem = p;
    } catch (_) {}
  }
  let placeItem = clipItem;
  if (ppro.ProjectItem && typeof ppro.ProjectItem.cast === "function") {
    try {
      const casted = ppro.ProjectItem.cast(clipItem);
      if (casted) placeItem = casted;
    } catch (_) {}
  }

  // Set In/Out duration in its own transaction (Rule: P2 marks committed before overwrite)
  let clipProjectItem = clipItem;
  if (ppro.ClipProjectItem && typeof ppro.ClipProjectItem.cast === "function") {
    try {
      const casted = ppro.ClipProjectItem.cast(clipItem);
      if (casted) clipProjectItem = casted;
    } catch (_) {}
  }
  if (clipProjectItem && typeof clipProjectItem.createSetInOutPointsAction === "function") {
    try {
      runTransaction(project, "CutDeck: Set Frame Hold Duration", (compound) => {
        const inOut = clipProjectItem.createSetInOutPointsAction(tickTime(0n), tickTime(holdDurationTicks));
        if (inOut) compound.addAction(inOut);
      });
    } catch (e) {
      console.warn("CutDeck: createSetInOutPointsAction warning:", e);
    }
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

  // Ensure placed clip duration on sequence matches holdEndTicks if supported
  try {
    const trackCount = typeof seq.getVideoTrackCount === "function" ? await seq.getVideoTrackCount() : 0;
    if (targetTrack < trackCount) {
      const track = await seq.getVideoTrack(targetTrack);
      const trackItems = await getTrackClipItems(track, ppro);
      for (const ti of trackItems || []) {
        const sTime = typeof ti.getStartTime === "function" ? await ti.getStartTime() : ti.startTime;
        if (toTicksOr(sTime, -1n) === holdStartTicks) {
          const eTime = typeof ti.getEndTime === "function" ? await ti.getEndTime() : ti.endTime;
          const currentEnd = toTicksOr(eTime, 0n);
          if (currentEnd !== holdEndTicks && typeof ti.createSetEndAction === "function") {
            runTransaction(project, "CutDeck: Adjust Frame Hold End", (comp) => {
              const setEnd = ti.createSetEndAction(tickTime(holdEndTicks));
              if (setEnd) comp.addAction(setEnd);
            });
          }
          break;
        }
      }
    }
  } catch (_) {}

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
  locateAndOrganizeImportedHoldItem,
  FRAME_HOLD_BIN_NAME,
};
