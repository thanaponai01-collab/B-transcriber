const ppro = require("premierepro");

// Premiere timeline manipulation for CutDeck adjustment-layer placement — no DOM.
// Owned by uxp/cutdeck/main.js via placeAdjustmentLayersOnTimeline(); see issue #47.

// Find adjustment layer in project panel or active timeline, matching active sequence dimensions and fps
async function findAdjustmentLayerItem(project, seq) {
  if (!project || typeof project.getRootItem !== "function") return null;
  const root = await project.getRootItem();
  if (!root) return null;

  let targetWidth = null;
  let targetHeight = null;
  try {
    if (seq && typeof seq.getSettings === "function") {
      const st = await seq.getSettings();
      if (st && st.videoFrameWidth && st.videoFrameHeight) {
        targetWidth = st.videoFrameWidth;
        targetHeight = st.videoFrameHeight;
      }
    }
  } catch (_) {}

  // 1. First priority: If active sequence already has an Adjustment Layer on any video track,
  // that project item is already calibrated to this sequence's exact dimensions and fps!
  if (seq && typeof seq.getVideoTrackCount === "function") {
    try {
      const vCount = await seq.getVideoTrackCount();
      for (let v = 0; v < vCount; v++) {
        const track = await seq.getVideoTrack(v);
        if (track && typeof track.getTrackItems === "function") {
          const clipType = ppro.Constants && ppro.Constants.TrackItemType ? ppro.Constants.TrackItemType.CLIP : undefined;
          const items = await track.getTrackItems(clipType, false);
          if (items && items.length > 0) {
            for (const it of items) {
              if (it.name && (it.name.toLowerCase().indexOf("adjustment") !== -1 || it.name.toLowerCase().indexOf("adj") !== -1)) {
                if (typeof it.getProjectItem === "function") {
                  const pi = await it.getProjectItem();
                  if (pi && pi.type !== 2) return pi;
                }
              }
            }
          }
        }
      }
    } catch (_) {}
  }

  // 2. Search project bins
  async function getFolderChildren(folder) {
    if (typeof folder.getItems === "function") {
      try { return await folder.getItems(); } catch (_) {}
    }
    if (ppro.BinProjectItem && typeof ppro.BinProjectItem.cast === "function") {
      try {
        const bin = ppro.BinProjectItem.cast(folder);
        if (bin && typeof bin.getItems === "function") {
          return await bin.getItems();
        }
      } catch (_) {}
    }
    return [];
  }

  const allCandidates = [];

  async function search(folder) {
    const items = await getFolderChildren(folder);
    if (!items || !items.length) return;

    for (const it of items) {
      // In Premiere Pro UXP, it.type === 2 is a BIN (Folder)
      const isBin = it.type === 2 || typeof it.getItems === "function" ||
        (ppro.BinProjectItem && typeof ppro.BinProjectItem.cast === "function" && ppro.BinProjectItem.cast(it) !== null);

      if (isBin) {
        // Recurse into the bin (e.g. "07. Adjustment Layer") — NEVER return the bin itself!
        await search(it);
        continue;
      }

      // Must be a clip item (type !== 2) whose name contains adjustment
      if (it.type !== 2 && it.name) {
        const lower = it.name.toLowerCase();
        if (
          lower.indexOf("adjustment layer") !== -1 ||
          lower.indexOf("adjustment") !== -1 ||
          lower.indexOf("adj_") === 0 ||
          lower.indexOf("al_") === 0
        ) {
          allCandidates.push(it);
        }
      }
    }
  }

  await search(root);

  if (allCandidates.length > 0) {
    // If targetWidth and targetHeight are known (e.g. 3840x2160, 1080x1920 vertical),
    // prioritize candidates whose name reflects the sequence resolution
    if (targetWidth && targetHeight) {
      const dimStr1 = `${targetWidth}x${targetHeight}`.toLowerCase();
      const dimStr2 = `${targetWidth}`.toLowerCase();
      for (const cand of allCandidates) {
        const cLower = cand.name.toLowerCase();
        if (cLower.indexOf(dimStr1) !== -1 || (cLower.indexOf(dimStr2) !== -1 && cLower.indexOf(`${targetHeight}`) !== -1)) {
          return cand;
        }
      }
    }
    // Also check if candidate name mentions sequence name
    if (seq && seq.name) {
      const sName = seq.name.toLowerCase();
      for (const cand of allCandidates) {
        if (cand.name.toLowerCase().indexOf(sName) !== -1) {
          return cand;
        }
      }
    }
    // Return first candidate
    return allCandidates[0];
  }

  return null;
}

// Exact tick converter handling TickTime objects, decimal strings, numbers, and BigInt
function toBigIntTicks(val) {
  if (val === null || val === undefined) return 0n;
  if (typeof val === "bigint") return val;
  if (typeof val === "object") {
    if (val.ticks !== undefined) return toBigIntTicks(val.ticks);
    if (typeof val.getSeconds === "function") {
      return BigInt(Math.round(val.getSeconds() * 254016000000));
    }
    if (typeof val.seconds === "number") {
      return BigInt(Math.round(val.seconds * 254016000000));
    }
  }
  const s = String(val).trim();
  if (!s) return 0n;
  const intPart = s.split(".")[0];
  try {
    return BigInt(intPart);
  } catch (_) {
    const n = parseFloat(s);
    if (!isNaN(n)) return BigInt(Math.round(n));
    return 0n;
  }
}

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

// Exact TickTime maker
function makeTickTimeFn(ppro) {
  const TickTime = ppro.TickTime;
  if (!TickTime) return null;
  const names = ["createWithTicks", "createWithTickcount", "createWithTickCount"];
  for (const n of names) {
    if (typeof TickTime[n] === "function") {
      return (val) => TickTime[n](val.toString());
    }
  }
  if (typeof TickTime.createWithSeconds === "function") {
    return (val) => TickTime.createWithSeconds(Number(val) / 254016000000);
  }
  return (val) => new TickTime(Number(val) / 254016000000);
}

// Safe helper to get clip track items (never throws if Constants or arguments differ)
async function getTrackClipItems(track) {
  if (!track || typeof track.getTrackItems !== "function") return [];
  const clipType = (ppro.Constants && ppro.Constants.TrackItemType && ppro.Constants.TrackItemType.CLIP !== undefined)
    ? ppro.Constants.TrackItemType.CLIP
    : 1;
  try {
    const items = await track.getTrackItems(clipType, false);
    if (items && Array.isArray(items)) return items;
  } catch (_) {}
  try {
    const items = await track.getTrackItems(1, false);
    if (items && Array.isArray(items)) return items;
  } catch (_) {}
  try {
    const items = await track.getTrackItems();
    if (items && Array.isArray(items)) return items;
  } catch (_) {}
  return [];
}

// Helper to read selected VIDEO clips on active sequence (strictly ignoring audio clips and adjustment layers)
async function getSelectedTimelineClips(seq) {
  let rawItems = [];
  try {
    if (typeof seq.getSelection === "function") {
      const sel = await seq.getSelection();
      if (sel) {
        if (typeof sel.getTrackItems === "function") {
          const items = await sel.getTrackItems();
          if (items && items.length > 0) rawItems = items;
        } else if (Array.isArray(sel)) {
          rawItems = sel;
        } else if (Array.isArray(sel.items)) {
          rawItems = sel.items;
        }
      }
    }
  } catch (e) {
    console.log("seq.getSelection() check:", e);
  }

  // Fallback: search video tracks for selected clips
  if (rawItems.length === 0) {
    try {
      const trackCount = await seq.getVideoTrackCount();
      for (let v = 0; v < trackCount; v++) {
        const track = await seq.getVideoTrack(v);
        const items = await getTrackClipItems(track);
        if (items && items.length > 0) {
          for (const it of items) {
            let isSel = false;
            if (typeof it.isSelected === "function") {
              try { isSel = await it.isSelected(); } catch (_) {}
            } else if (it.isSelected !== undefined) {
              isSel = !!it.isSelected;
            } else if (it.selected !== undefined) {
              isSel = !!it.selected;
            }
            if (isSel) rawItems.push(it);
          }
        }
      }
    } catch (e) {
      console.log("fallback track scan failed:", e);
    }
  }

  if (!rawItems || rawItems.length === 0) return [];

  // Filter: ONLY include Video clips (exclude Audio clips and Adjustment Layers!)
  // In Premiere, linked selection selects Audio clips which may span longer cuts than Video!
  const videoClips = [];
  const videoItemsSet = new Set();

  try {
    const trackCount = await seq.getVideoTrackCount();
    for (let v = 0; v < trackCount; v++) {
      const track = await seq.getVideoTrack(v);
      const vItems = await getTrackClipItems(track);
      if (vItems) {
        for (const vi of vItems) {
          videoItemsSet.add(vi);
        }
      }
    }
  } catch (_) {}

  for (const it of rawItems) {
    if (!it) continue;

    // 1. Ignore Adjustment Layers themselves
    const name = it.name ? it.name.toLowerCase() : "";
    if (name.includes("adjustment") || name.startsWith("adj_")) {
      continue;
    }

    // 2. Check explicit mediaType
    if (it.mediaType === "Audio" || it.mediaType === 2 || it.mediaType === "AUDIO") {
      continue;
    }
    if (ppro.AudioClipTrackItem && it instanceof ppro.AudioClipTrackItem) {
      continue;
    }

    // 3. Verify item belongs to a Video Track (if videoItemsSet was populated)
    if (videoItemsSet.size > 0 && !videoItemsSet.has(it)) {
      continue; // Audio clip on A1/A2, ignore!
    }

    videoClips.push(it);
  }

  return videoClips;
}

// Robust UXP helper to determine collision-free track using Smart Stacking
async function findSmartStackTrack(seq, startTicks, endTicks, minTrack = 1) {
  const trackCount = await seq.getVideoTrackCount();
  let highestOccupied = 0;
  for (let v = 0; v < trackCount; v++) {
    const track = await seq.getVideoTrack(v);
    const items = await getTrackClipItems(track);
    if (items && items.length > 0) {
      for (const it of items) {
        const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
        const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
        const itIn = toBigIntTicks(sTime);
        const itOut = toBigIntTicks(eTime);
        if (itOut > startTicks && itIn < endTicks) {
          if (v > highestOccupied) highestOccupied = v;
          break;
        }
      }
    }
  }

  let candidate = Math.max(minTrack, highestOccupied + 1);
  const fiveSecondsTicks = 254016000000n * 5n;
  const durationTicks = endTicks - startTicks;
  const safetyEndTicks = startTicks + (durationTicks > fiveSecondsTicks ? durationTicks : fiveSecondsTicks);

  while (candidate < trackCount) {
    const track = await seq.getVideoTrack(candidate);
    const items = await getTrackClipItems(track);
    let trackHasCollision = false;
    if (items && items.length > 0) {
      for (const it of items) {
        const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
        const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
        const itIn = toBigIntTicks(sTime);
        const itOut = toBigIntTicks(eTime);
        if (itOut > startTicks && itIn < safetyEndTicks) {
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

// Robust UXP timeline placement routine (supporting multi-clip cut transitions and separate clip spans)
async function placeAdjustmentLayersOnTimeline(ppro, options = {}) {
  const project = await ppro.Project.getActiveProject();
  if (!project) throw new Error("Open a Premiere project first.");
  const seq = await project.getActiveSequence();
  if (!seq) throw new Error("Open a sequence in Premiere first.");

  if (seq.name && typeof options.onSequenceName === "function") {
    options.onSequenceName(seq.name);
  }

  const tpfStr = await seq.getTimebase();
  const tpf = toBigIntTicks(tpfStr) || 10594584000n;

  let ctiTicks = 0n;
  try {
    const cti = await seq.getPlayerPosition();
    ctiTicks = toBigIntTicks(cti);
  } catch (_) {
    ctiTicks = 0n;
  }

  const frames = BigInt(options.frames || 16);
  const clamp = options.clamp !== undefined ? options.clamp : true;
  const effectName = options.effectName || "";
  const mode = options.mode || "span";

  // Check if user has clips selected on timeline
  const selectedClips = await getSelectedTimelineClips(seq);
  const clipsWithTimes = [];
  for (const it of selectedClips) {
    try {
      const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
      const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
      const sTicks = toBigIntTicks(sTime);
      const eTicks = toBigIntTicks(eTime);
      if (eTicks > sTicks) {
        clipsWithTimes.push({ item: it, startTicks: sTicks, endTicks: eTicks });
      }
    } catch (_) {}
  }
  clipsWithTimes.sort((a, b) => (a.startTicks < b.startTicks ? -1 : a.startTicks > b.startTicks ? 1 : 0));

  const placements = [];

  if (mode === "transition") {
    // -------------------------------------------------------------
    // TRANSITION MODE (Shift+Click): 50/50 centered on cuts
    // -------------------------------------------------------------
    const halfFrames = frames / 2n;
    const halfTicks = halfFrames * tpf;

    if (clipsWithTimes.length >= 2) {
      // Find internal cuts between adjacent selected clips
      for (let i = 0; i < clipsWithTimes.length - 1; i++) {
        const cLeft = clipsWithTimes[i];
        const cRight = clipsWithTimes[i + 1];

        // Sequential clips within 2 frames tolerance of a clean cut seam
        const diff = cRight.startTicks > cLeft.endTicks
          ? (cRight.startTicks - cLeft.endTicks)
          : (cLeft.endTicks - cRight.startTicks);

        if (diff <= (tpf * 2n)) {
          const cutTick = cLeft.endTicks;
          let curHalfLeft = halfTicks;
          let curHalfRight = halfTicks;

          if (clamp) {
            const durLeft = cLeft.endTicks - cLeft.startTicks;
            const durRight = cRight.endTicks - cRight.startTicks;
            const maxHalfLeft = (durLeft * 45n) / 100n;
            const maxHalfRight = (durRight * 45n) / 100n;
            if (curHalfLeft > maxHalfLeft) curHalfLeft = maxHalfLeft;
            if (curHalfRight > maxHalfRight) curHalfRight = maxHalfRight;
          }

          const sT = cutTick > curHalfLeft ? (cutTick - curHalfLeft) : 0n;
          const eT = cutTick + curHalfRight;
          placements.push({
            startTicks: sT,
            endTicks: eT,
            name: effectName ? `ADJ_${effectName}_${frames}f` : `ADJ_Cut_${frames}f`
          });
        }
      }
    }

    // Fallback: If no internal cuts found (e.g. 0-1 clip selected, or clips separated), place at CTI
    if (placements.length === 0) {
      const sT = ctiTicks > halfTicks ? (ctiTicks - halfTicks) : 0n;
      const eT = sT + (frames * tpf);
      placements.push({
        startTicks: sT,
        endTicks: eT,
        name: effectName ? `ADJ_${effectName}_${frames}f` : `ADJ_Cut_${frames}f`
      });
    }
  } else if (mode === "per_clip") {
    // -------------------------------------------------------------
    // PER-CLIP MODE (Ctrl+Click): Dedicated AL per selected clip
    // -------------------------------------------------------------
    if (clipsWithTimes.length > 0) {
      for (let i = 0; i < clipsWithTimes.length; i++) {
        const cl = clipsWithTimes[i];
        placements.push({
          startTicks: cl.startTicks,
          endTicks: cl.endTicks,
          name: effectName
            ? `ADJ_${effectName}`
            : (clipsWithTimes.length === 1 ? "ADJ_Fit" : `ADJ_Clip_${i + 1}`)
        });
      }
    } else {
      // If nothing selected, check In/Out or playhead
      let inTicks = 0n;
      let outTicks = 0n;
      try {
        const inPoint = await seq.getInPoint();
        const outPoint = await seq.getOutPoint();
        inTicks = toBigIntTicks(inPoint);
        outTicks = toBigIntTicks(outPoint);
      } catch (_) {}

      if (outTicks > inTicks && inTicks >= 0n) {
        placements.push({
          startTicks: inTicks,
          endTicks: outTicks,
          name: effectName ? `ADJ_${effectName}` : "ADJ_InOut"
        });
      } else {
        const half = (frames / 2n) * tpf;
        const sT = ctiTicks > half ? ctiTicks - half : 0n;
        const eT = sT + (frames * tpf);
        placements.push({
          startTicks: sT,
          endTicks: eT,
          name: effectName ? `ADJ_${effectName}_${frames}f` : `ADJ_${frames}f`
        });
      }
    }
  } else {
    // -------------------------------------------------------------
    // SPAN MODE (Normal Click): Spans the full selection
    // -------------------------------------------------------------
    if (clipsWithTimes.length > 0) {
      let minStart = clipsWithTimes[0].startTicks;
      let maxEnd = clipsWithTimes[0].endTicks;
      for (const cl of clipsWithTimes) {
        if (cl.startTicks < minStart) minStart = cl.startTicks;
        if (cl.endTicks > maxEnd) maxEnd = cl.endTicks;
      }
      placements.push({
        startTicks: minStart,
        endTicks: maxEnd,
        name: effectName
          ? `ADJ_${effectName}`
          : (clipsWithTimes.length === 1 ? "ADJ_Fit" : "ADJ_Span")
      });
    } else {
      // If nothing selected, check In/Out or playhead
      let inTicks = 0n;
      let outTicks = 0n;
      try {
        const inPoint = await seq.getInPoint();
        const outPoint = await seq.getOutPoint();
        inTicks = toBigIntTicks(inPoint);
        outTicks = toBigIntTicks(outPoint);
      } catch (_) {}

      if (outTicks > inTicks && inTicks >= 0n) {
        placements.push({
          startTicks: inTicks,
          endTicks: outTicks,
          name: effectName ? `ADJ_${effectName}` : "ADJ_InOut"
        });
      } else {
        const half = (frames / 2n) * tpf;
        const sT = ctiTicks > half ? ctiTicks - half : 0n;
        const eT = sT + (frames * tpf);
        placements.push({
          startTicks: sT,
          endTicks: eT,
          name: effectName ? `ADJ_${effectName}_${frames}f` : `ADJ_${frames}f`
        });
      }
    }
  }

  const tickTime = makeTickTimeFn(ppro);
  if (!tickTime) throw new Error("Could not initialize Premiere TickTime constructor.");

  const alItem = await findAdjustmentLayerItem(project, seq);
  if (!alItem) {
    throw new Error("No Adjustment Layer clip found in project or timeline. (Note: create one via File > New > Adjustment Layer)");
  }

  let clipItem = alItem;
  if (typeof alItem.getProjectItem === "function") {
    clipItem = await alItem.getProjectItem();
  }
  if (ppro.ClipProjectItem && typeof ppro.ClipProjectItem.cast === "function") {
    try {
      const casted = ppro.ClipProjectItem.cast(clipItem);
      if (casted) clipItem = casted;
    } catch (_) {}
  }

  // Ensure Adjustment Layer matches active sequence dimensions and aspect ratio
  try {
    if (clipItem && typeof clipItem.setScaleToFrameSize === "function") {
      clipItem.setScaleToFrameSize();
    }
  } catch (_) {}

  let placedCount = 0;
  const targetTracksSet = new Set();

  for (const p of placements) {
    const freshProject = await ppro.Project.getActiveProject();
    const freshSeq = await freshProject.getActiveSequence();
    const trackCountNow = await freshSeq.getVideoTrackCount();
    const targetTrack = await findSmartStackTrack(freshSeq, p.startTicks, p.endTicks, 1);
    targetTracksSet.add(targetTrack + 1);

    if (!ppro.SequenceEditor || typeof ppro.SequenceEditor.getEditor !== "function") {
      throw new Error("SequenceEditor is not supported in this Premiere build.");
    }
    const editor = await ppro.SequenceEditor.getEditor(freshSeq);
    const tStart = tickTime(p.startTicks);
    const durTicks = p.endTicks - p.startTicks;

    let ok = false;
    let thrown = null;

    const run = () => {
      try {
        ok = freshProject.executeTransaction((compound) => {
          let action = null;
          let lastErr = null;

          if (clipItem) {
            if (typeof clipItem.createSetInOutPointsAction === "function") {
              try {
                const inOut = clipItem.createSetInOutPointsAction(tickTime(0n), tickTime(durTicks));
                if (inOut) compound.addAction(inOut);
              } catch (_) {}
            }

            const attempts = [];
            if (targetTrack >= trackCountNow) {
              attempts.push(() => editor.createInsertProjectItemAction(clipItem, tStart, Number(targetTrack), -1, false));
              attempts.push(() => editor.createOverwriteItemAction(clipItem, tStart, Number(targetTrack), -1));
            } else {
              attempts.push(() => editor.createOverwriteItemAction(clipItem, tStart, Number(targetTrack), -1));
              attempts.push(() => editor.createInsertProjectItemAction(clipItem, tStart, Number(targetTrack), -1, false));
            }
            attempts.push(() => editor.createOverwriteItemAction(clipItem, tStart, Number(targetTrack), 0));
            attempts.push(() => editor.createOverwriteItemAction(alItem, tStart, Number(targetTrack), -1));

            for (const fn of attempts) {
              try {
                action = fn();
                if (action) break;
              } catch (e) {
                lastErr = e;
              }
            }
          }

          if (!action) {
            const name = clipItem?.name || alItem?.name || "unknown";
            const type = clipItem?.type !== undefined ? clipItem.type : "unknown";
            throw new Error(`Could not place: ${lastErr ? (lastErr.message || String(lastErr)) : "Invalid parameter"}. (Item: "${name}", Type: ${type}, V-Track: V${targetTrack + 1})`);
          }

          if (!compound.addAction(action)) {
            throw new Error("addAction returned false");
          }
        }, "CutDeck: Place Adjustment Layer");
      } catch (e) {
        thrown = e;
      }
    };

    if (typeof freshProject.lockedAccess === "function") {
      freshProject.lockedAccess(run);
    } else {
      run();
    }

    if (!ok && thrown) throw thrown;

    // Step 2: Trim the placed Adjustment Layer to exact duration (so it is NEVER 5 seconds!)
    try {
      const freshSeq2 = await freshProject.getActiveSequence();
      const targetTrackObj = await freshSeq2.getVideoTrack(Number(targetTrack));
      if (targetTrackObj) {
        const trackItems = await getTrackClipItems(targetTrackObj);
        if (trackItems && trackItems.length > 0) {
          for (const it of trackItems) {
            const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
            const sTicks = toBigIntTicks(sTime);
            const diff = sTicks > p.startTicks ? (sTicks - p.startTicks) : (p.startTicks - sTicks);
            if (diff <= (tpf * 2n)) {
              const trimRun = () => {
                freshProject.executeTransaction((compound) => {
                  if (typeof it.createSetEndAction === "function") {
                    compound.addAction(it.createSetEndAction(tickTime(p.endTicks)));
                  }
                }, "CutDeck: Trim Adjustment Layer Duration");
              };
              if (typeof freshProject.lockedAccess === "function") {
                freshProject.lockedAccess(trimRun);
              } else {
                trimRun();
              }

              // Set label color and name
              try {
                if (typeof it.setColorLabel === "function") {
                  await it.setColorLabel(getLabelIndex(options.color));
                }
              } catch (_) {}
              try {
                if (typeof it.setName === "function") {
                  await it.setName(p.name);
                }
              } catch (_) {}
              try {
                if (typeof it.setScaleToFrameSize === "function") {
                  await it.setScaleToFrameSize();
                } else if (typeof it.scaleToFrameSize === "function") {
                  await it.scaleToFrameSize();
                }
              } catch (_) {}
              break;
            }
          }
        }
      }
    } catch (err) {
      console.log("Trimming duration failed:", err);
    }

    placedCount++;
  }

  return {
    success: true,
    placedCount,
    targetTrack: Array.from(targetTracksSet).join(", "),
    frames: Number(frames),
    mode,
    cutCount: mode === "transition" ? placedCount : 0,
    selectedCount: clipsWithTimes.length
  };
}

module.exports = { placeAdjustmentLayersOnTimeline };
