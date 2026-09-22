const ppro = require("premierepro");

// Premiere timeline manipulation for CutDeck adjustment-layer placement — no DOM.
// Owned by uxp/cutdeck/main.js via placeAdjustmentLayersOnTimeline(); see issue #47.

// Same top-level bin workflow.js's getOrCreateCutDeckBin creates/reuses for Cut/Sync
// results — deliberately the SAME name, so this is one shared folder tree in the Project
// panel, not a second one. ADJ_BIN_NAME is the canonical, unambiguous home for the
// Adjustment Layer: dropping it there means CutDeck finds it instantly on any sequence,
// with no name-guessing required.
const CUTDECK_BIN_NAME = "CutDeck";
const ADJ_BIN_NAME = "ADJ & FX";

// Resolves a folder-like item's createBinAction/getItems, casting to FolderItem when
// the plain methods aren't directly present — same fallback getFolderChildren uses below.
function asBinLike(item) {
  if (!item) return null;
  if (typeof item.createBinAction === "function" && typeof item.getItems === "function") return item;
  if (ppro.FolderItem && typeof ppro.FolderItem.cast === "function") {
    try {
      const cast = ppro.FolderItem.cast(item);
      if (cast) return cast;
    } catch (_) {}
  }
  return item;
}

// Finds (or creates once) a named child bin directly under `parent`. Same pattern as
// workflow.js's getOrCreateCutDeckBin (issue #18: executeTransaction must be wrapped in
// project.lockedAccess — called bare, references fetched just beforehand throw "The script
// object is no longer valid").
async function getOrCreateChildBin(project, parent, name) {
  const parentBin = asBinLike(parent);
  const existingItems = (await parentBin.getItems()) || [];
  const existing = existingItems.find((item) => item.name === name);
  if (existing) return existing;

  let ok = false;
  const run = () => {
    ok = project.executeTransaction((compound) => {
      if (!compound.addAction(parentBin.createBinAction(name, false))) {
        throw new Error("addAction(createBin) returned false");
      }
    }, `Create ${name} bin`);
  };
  if (typeof project.lockedAccess === "function") project.lockedAccess(run); else run();
  if (!ok) throw new Error(`Could not create the "${name}" bin in this project.`);

  const afterItems = (await parentBin.getItems()) || [];
  const created = afterItems.find((item) => item.name === name);
  if (!created) throw new Error(`"${name}" bin was created but could not be found afterward.`);
  return created;
}

// Finds (or creates once) Project panel > CutDeck > ADJ & FX.
async function getOrCreateAdjBin(project) {
  const root = await project.getRootItem();
  const cutdeckBin = await getOrCreateChildBin(project, root, CUTDECK_BIN_NAME);
  return getOrCreateChildBin(project, cutdeckBin, ADJ_BIN_NAME);
}

// Best-effort resolution auto-detection, tried before any naming convention. Premiere
// stores an item's own computed frame size in its internal "Column.Intrinsic.VideoInfo"
// project metadata field — the same data behind the Project panel's "Video Info" column, so
// it should exist even for a synthetic item like an Adjustment Layer, not just real media.
// Adobe's own community documents this field as unreliable ("works only half the time" —
// not every item populates it), so this is strictly a bonus: any failure (missing field,
// parse error, a build without ppro.Metadata or require("uxp").xmp) returns null and the
// caller falls through to name matching, unchanged.
async function detectResolutionFromMetadata(projectItem) {
  try {
    if (!projectItem || !ppro.Metadata || typeof ppro.Metadata.getProjectMetadata !== "function") return null;
    const xmpStr = await ppro.Metadata.getProjectMetadata(projectItem);
    if (!xmpStr) return null;
    const uxpXmp = require("uxp").xmp;
    if (!uxpXmp || typeof uxpXmp.XMPMeta !== "function") return null;
    const xmp = new uxpXmp.XMPMeta(xmpStr);
    const prop = xmp.getProperty(
      "http://ns.adobe.com/premierePrivateProjectMetaData/1.0/",
      "Column.Intrinsic.VideoInfo"
    );
    const raw = prop && prop.value ? String(prop.value) : "";
    if (!raw) return null;
    // Observed format is space-separated with the numbers at either end (e.g.
    // "1920 x 1080" per the field's own documented example) — pull every number out and
    // take the first/last rather than assume exact token positions.
    const numbers = raw.match(/\d+/g);
    if (!numbers || numbers.length < 2) return null;
    const width = parseInt(numbers[0], 10);
    const height = parseInt(numbers[numbers.length - 1], 10);
    if (!width || !height) return null;
    return { width, height };
  } catch (_) {
    return null;
  }
}

// Picks the right Adjustment Layer when more than one sits in the same folder. Tries
// Premiere's own metadata first (exact match, no naming needed when it works); falls back to
// matching by name (e.g. "1920x1080", "AL 1080x1920") when metadata isn't available — so a
// same-size placement needs no scaling at all either way, Scale stays the proven-working 100%.
async function pickBestCandidate(candidates, targetWidth, targetHeight, seq) {
  if (!candidates || candidates.length === 0) return null;
  if (targetWidth && targetHeight) {
    for (const cand of candidates) {
      const detected = await detectResolutionFromMetadata(cand);
      if (detected && detected.width === targetWidth && detected.height === targetHeight) {
        return cand;
      }
    }
    // Width must appear BEFORE height with a short separator ("x", "×", "-", " ", or
    // nothing) between them — a plain "does this substring appear anywhere" check (the
    // original version of this) matched "1920x1080" against a 1080x1920 target too, since
    // both numbers are present, just transposed. Order matters.
    const pattern = new RegExp(`${targetWidth}\\D{0,3}${targetHeight}`);
    for (const cand of candidates) {
      if (pattern.test(cand.name || "")) return cand;
    }
  }
  if (seq && seq.name) {
    const sName = seq.name.toLowerCase();
    for (const cand of candidates) {
      if ((cand.name || "").toLowerCase().indexOf(sName) !== -1) return cand;
    }
  }
  return candidates[0];
}

// Find adjustment layer in project panel or active timeline, matching active sequence dimensions and fps
async function findAdjustmentLayerItem(project, seq) {
  if (!project || typeof project.getRootItem !== "function") return null;
  const root = await project.getRootItem();
  if (!root) return null;

  let targetWidth = null;
  let targetHeight = null;
  try {
    if (seq && typeof seq.getSettings === "function") {
      // SequenceSettings has no plain videoFrameWidth/videoFrameHeight fields (confirmed
      // against the official class reference) — it's getVideoFrameRect(): RectF, and RectF
      // is the plain {width, height} struct.
      const st = await seq.getSettings();
      const rect = st && typeof st.getVideoFrameRect === "function" ? await st.getVideoFrameRect() : null;
      if (rect && rect.width && rect.height) {
        targetWidth = rect.width;
        targetHeight = rect.height;
      }
    }
  } catch (_) {}

  // Removed: a step that trusted whatever Adjustment Layer was already sitting on the
  // active sequence's timeline, on the assumption it must already be the right one for that
  // sequence. Proven wrong (2026-09-22): once either AL lands on a sequence once — including
  // by mistake — this made CutDeck reuse that exact instance forever on that sequence,
  // completely bypassing the resolution-aware pick below. That pick (metadata, then name) is
  // now the only path — always re-evaluated, so it can't get stuck on a stale placement.

  // Canonical home: Project panel > CutDeck > ADJ & FX. Ensured to exist (created if
  // missing) so there is always one unambiguous, always-findable place for the Adjustment
  // Layer(s) — no depending on it already being on some other sequence's timeline. One AL in
  // here just works. Several (one per resolution you actually use — e.g. "1920x1080",
  // "1080x1920") get matched to the active sequence by name — see pickBestCandidate.
  try {
    const adjBin = await getOrCreateAdjBin(project);
    const items = (await asBinLike(adjBin).getItems()) || [];
    const candidates = items.filter((it) => it.type !== 2 && it.name);
    const picked = await pickBestCandidate(candidates, targetWidth, targetHeight, seq);
    if (picked) return picked;
  } catch (_) {}

  // Legacy fallback: search the whole project (an AL named/placed before ADJ & FX existed)
  async function getFolderChildren(folder) {
    if (typeof folder.getItems === "function") {
      try { return await folder.getItems(); } catch (_) {}
    }
    if (ppro.FolderItem && typeof ppro.FolderItem.cast === "function") {
      try {
        const bin = ppro.FolderItem.cast(folder);
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
        (ppro.FolderItem && typeof ppro.FolderItem.cast === "function" && ppro.FolderItem.cast(it) !== null);

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

  return await pickBestCandidate(allCandidates, targetWidth, targetHeight, seq);
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
  try {
    return await getTrackClipItemsOrThrow(track);
  } catch (_) {
    return [];
  }
}

// Same lookup, but rethrows the last error instead of masking "couldn't read this
// track" as "this track is empty" — callers that use the result to avoid colliding
// with existing clips (findSmartStackTrack) must be able to tell the difference,
// since treating an unreadable track as empty risks overwriting real footage on it.
async function getTrackClipItemsOrThrow(track) {
  if (!track || typeof track.getTrackItems !== "function") return [];
  const clipType = (ppro.Constants && ppro.Constants.TrackItemType && ppro.Constants.TrackItemType.CLIP !== undefined)
    ? ppro.Constants.TrackItemType.CLIP
    : 1;
  let lastErr = null;
  try {
    const items = await track.getTrackItems(clipType, false);
    if (items && Array.isArray(items)) return items;
  } catch (e) { lastErr = e; }
  try {
    const items = await track.getTrackItems(1, false);
    if (items && Array.isArray(items)) return items;
  } catch (e) { lastErr = e; }
  try {
    const items = await track.getTrackItems();
    if (items && Array.isArray(items)) return items;
  } catch (e) { lastErr = e; }
  throw lastErr || new Error("getTrackItems returned no usable result");
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
  // Also record which video track each item lives on — callers need to tell V1 (the
  // canvas real footage lives on) apart from a duplicate clip sitting on a higher track.
  const videoClips = [];
  const videoItemsTrackMap = new Map();

  try {
    const trackCount = await seq.getVideoTrackCount();
    for (let v = 0; v < trackCount; v++) {
      const track = await seq.getVideoTrack(v);
      const vItems = await getTrackClipItems(track);
      if (vItems) {
        for (const vi of vItems) {
          videoItemsTrackMap.set(vi, v);
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

    // 3. Verify item belongs to a Video Track (if videoItemsTrackMap was populated)
    if (videoItemsTrackMap.size > 0 && !videoItemsTrackMap.has(it)) {
      continue; // Audio clip on A1/A2, ignore!
    }

    videoClips.push({ item: it, track: videoItemsTrackMap.has(it) ? videoItemsTrackMap.get(it) : -1 });
  }

  return videoClips;
}

// Robust UXP helper to determine collision-free track using Smart Stacking
async function findSmartStackTrack(seq, startTicks, endTicks, minTrack = 1) {
  const trackCount = await seq.getVideoTrackCount();
  let highestOccupied = 0;
  for (let v = 0; v < trackCount; v++) {
    const track = await seq.getVideoTrack(v);
    let items;
    try {
      items = await getTrackClipItemsOrThrow(track);
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
        const itIn = toBigIntTicks(sTime);
        const itOut = toBigIntTicks(eTime);
        if (itOut > startTicks && itIn < endTicks) {
          console.log(`findSmartStackTrack: V${v + 1} collides with query [${startTicks},${endTicks}) — ` +
            `item "${it.name || "?"}" is [${itIn},${itOut})`);
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
  // hard gate + Step 2 trim reliably lands each placement at its exact span before
  // the next one is ever checked, so padding here only fragmented adjacent short
  // clips onto separate tracks instead of letting them share one.)
  while (candidate < trackCount) {
    const track = await seq.getVideoTrack(candidate);
    let items;
    let trackHasCollision = false;
    try {
      items = await getTrackClipItemsOrThrow(track);
    } catch (e) {
      console.log(`findSmartStackTrack: could not read V${candidate + 1} items during safety scan, assuming occupied:`, e);
      candidate++;
      continue;
    }
    if (items && items.length > 0) {
      for (const it of items) {
        const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
        const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
        const itIn = toBigIntTicks(sTime);
        const itOut = toBigIntTicks(eTime);
        if (itOut > startTicks && itIn < endTicks) {
          console.log(`findSmartStackTrack: V${candidate + 1} collides with query [${startTicks},${endTicks}) during refine — ` +
            `item "${it.name || "?"}" is [${itIn},${itOut})`);
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
async function isTrackRangeClear(seq, trackIndex, startTicks, endTicks) {
  const trackCount = await seq.getVideoTrackCount();
  if (trackIndex >= trackCount) return true; // track doesn't exist yet — nothing to collide with
  const track = await seq.getVideoTrack(trackIndex);
  const items = await getTrackClipItemsOrThrow(track);
  for (const it of items) {
    const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
    const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
    const itIn = toBigIntTicks(sTime);
    const itOut = toBigIntTicks(eTime);
    if (itOut > startTicks && itIn < endTicks) {
      console.log(`isTrackRangeClear: V${trackIndex + 1} collides with query [${startTicks},${endTicks}) — ` +
        `item "${it.name || "?"}" is [${itIn},${itOut})`);
      return false;
    }
  }
  return true;
}

// Groups planned placements into "lanes" so any two that overlap in time never end up in
// the same lane — classic interval-scheduling greedy assignment (sort by start, drop each
// into the first lane whose last-placed end is already <= this start, else open a new lane).
// Needed because transition mode (Shift+Click) centers each AL independently on its own cut:
// when cuts sit closer together than the requested frame width, neighboring ALs' spans can
// genuinely overlap, and placements within one lane never do, by construction.
function assignPlacementLanes(placements) {
  const order = placements.map((_, idx) => idx).sort((a, b) => {
    const pa = placements[a], pb = placements[b];
    if (pa.startTicks < pb.startTicks) return -1;
    if (pa.startTicks > pb.startTicks) return 1;
    return a - b;
  });
  const laneEnds = [];
  const laneOf = new Array(placements.length).fill(0);
  for (const idx of order) {
    const p = placements[idx];
    let lane = laneEnds.findIndex((end) => end <= p.startTicks);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(p.endTicks);
    } else {
      laneEnds[lane] = p.endTicks;
    }
    laneOf[idx] = lane;
  }
  return laneOf;
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

  // Scaling was tried and removed (2026-09-22): createSetScaleToFrameSizeAction() proved to
  // have no visible effect, and there's no API to read a project item's native pixel
  // dimensions to compute a scale manually either (confirmed against ProjectItem/
  // ClipProjectItem/Media/FootageInterpretation — none expose width/height). The workflow
  // now avoids needing scale at all: keep one Adjustment Layer per resolution you use in
  // Project panel > CutDeck > ADJ & FX, and findAdjustmentLayerItem picks the one that
  // already matches this sequence exactly, so it's placed at native 100% — see
  // pickBestCandidate. sequenceWidth/sequenceHeight are still read here purely to report
  // what CutDeck detected, for the status line.
  let sequenceWidth = null;
  let sequenceHeight = null;
  try {
    // SequenceSettings has no plain videoFrameWidth/videoFrameHeight fields (confirmed
    // against the official class reference) — it's getVideoFrameRect(): RectF, and RectF
    // is the plain {width, height} struct.
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
  const rawClipsWithTimes = [];
  for (const sc of selectedClips) {
    try {
      const it = sc.item;
      const sTime = typeof it.getStartTime === "function" ? await it.getStartTime() : it.startTime;
      const eTime = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
      const sTicks = toBigIntTicks(sTime);
      const eTicks = toBigIntTicks(eTime);
      if (eTicks > sTicks) {
        rawClipsWithTimes.push({ track: sc.track, startTicks: sTicks, endTicks: eTicks });
      }
    } catch (_) {}
  }

  // Cover every selected clip's own span, any track — not just V1 (confirmed
  // 2026-09-21: the user wants AL over a region where only V2/V3 have a selected
  // clip and V1 has nothing there too).
  //
  // Where more than one selected clip covers the same stretch, only the TOPMOST
  // track's clip should drive it — a lower clip hidden underneath a higher one
  // must not introduce its own split point there (confirmed 2026-09-21: a V2 clip
  // straddling the real boundary between a V4 clip and a V3 clip fragmented what
  // should have been 2 clean AL segments into 4 — "it like spot the V2 that is
  // under both V3, V4 ... i want it to spot only top layer"). So this is a
  // layering resolve, not a plain interval union: assign each breakpoint-bounded
  // sub-interval to whichever covering clip has the highest track, tagged with that
  // clip's identity, then merge adjacent sub-intervals that resolve to the SAME
  // clip. A boundary between two DIFFERENT top clips (even same track, different
  // clip) still survives — this only removes splits contributed by a clip that
  // never actually wins the region it overlaps.
  const taggedClips = rawClipsWithTimes.map((cl, idx) => ({ ...cl, idx }));
  const breakpoints = [];
  for (const cl of taggedClips) {
    breakpoints.push(cl.startTicks, cl.endTicks);
  }
  breakpoints.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const uniqueBreakpoints = breakpoints.filter((b, idx) => idx === 0 || b !== breakpoints[idx - 1]);

  const clipsWithTimes = [];
  for (let i = 0; i < uniqueBreakpoints.length - 1; i++) {
    const segStart = uniqueBreakpoints[i];
    const segEnd = uniqueBreakpoints[i + 1];
    const covering = taggedClips.filter((cl) => cl.startTicks <= segStart && cl.endTicks >= segEnd);
    if (covering.length === 0) continue; // real gap between separate, non-touching selections

    let winner = covering[0];
    for (const cl of covering) {
      if (cl.track > winner.track) winner = cl;
    }

    const last = clipsWithTimes[clipsWithTimes.length - 1];
    if (last && last.winnerIdx === winner.idx && last.endTicks === segStart) {
      last.endTicks = segEnd;
    } else {
      clipsWithTimes.push({ startTicks: segStart, endTicks: segEnd, winnerIdx: winner.idx });
    }
  }

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
    throw new Error(
      "No Adjustment Layer found yet — Premiere's scripting API has no way to create one from a script " +
      "(confirmed against the official UXP Project class reference: no createAdjustmentLayer method exists), " +
      "but I've made a spot for it: Project panel > CutDeck > ADJ & FX. Create an Adjustment Layer manually " +
      "(File > New Item > Adjustment Layer) at your sequence's resolution and drag it into that folder. If you " +
      "only ever use one resolution, one AL is enough. If you switch between resolutions, create one per " +
      "resolution and name each one after its size (e.g. \"1920x1080\", \"1080x1920\") — CutDeck matches the " +
      "right one to whichever sequence is active automatically."
    );
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

  let placedCount = 0;
  const targetTracksSet = new Set();
  // Every actually-placed track item, in placement order — lets a caller (see main.js's
  // doEffect) apply a real Premiere effect to each one after placement, instead of only
  // knowing a count happened.
  const placedItems = [];

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
      let laneTrack = await findSmartStackTrack(batchSeq, unionStart, unionEnd, floorTrack);

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
            clear = await isTrackRangeClear(batchSeq, laneTrack, p.startTicks, p.endTicks);
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

  for (let pIdx = 0; pIdx < placements.length; pIdx++) {
    const p = placements[pIdx];
    const freshProject = await ppro.Project.getActiveProject();
    const freshSeq = await freshProject.getActiveSequence();
    const durTicks = p.endTicks - p.startTicks;
    let targetTrack = laneTracks[laneOf[pIdx]];

    // Hard gate: re-verify the exact intended span is actually clear immediately
    // before committing. Log evidence (2026-09-21) confirms Step 2's trim always
    // lands exactly (trimHeld/trimOk true, actualEndTicks === requestedEndTicks every
    // time) — there's no readback race to guard against here. This should normally
    // find the lane's track already clear (it was clear across the whole lane's
    // union span) — it only walks further if genuinely new content showed up.
    let guard = 0;
    while (guard < 32) {
      let clear;
      try {
        clear = await isTrackRangeClear(freshSeq, targetTrack, p.startTicks, p.endTicks);
      } catch (e) {
        throw new Error(
          `Could not verify V${targetTrack + 1} is empty before placing "${p.name}" — ` +
          `aborting rather than risk overwriting real footage. (${e && e.message ? e.message : e})`
        );
      }
      if (clear) break;
      targetTrack++;
      guard++;
    }
    if (guard >= 32) {
      throw new Error(`Could not find a clear track for "${p.name}" after checking 32 candidates — aborting.`);
    }

    const trackCountNow = await freshSeq.getVideoTrackCount();
    targetTracksSet.add(targetTrack + 1);

    if (!ppro.SequenceEditor || typeof ppro.SequenceEditor.getEditor !== "function") {
      throw new Error("SequenceEditor is not supported in this Premiere build.");
    }
    const editor = await ppro.SequenceEditor.getEditor(freshSeq);
    const tStart = tickTime(p.startTicks);

    // Commit the source Adjustment Layer's in/out points as their OWN transaction,
    // strictly before the overwrite below is even constructed — not queued into the
    // same compound as the overwrite (the previous approach). See issue #25 (retired
    // assemble route): a shared ClipProjectItem's setInOut can resolve
    // against a stale value when paired with another action in one transaction: "Fall
    // back to one transaction per span." Confirmed 2026-09-21 the same-transaction
    // pairing is unsafe in practice — the overwrite read the item's STALE (much
    // longer) length and destroyed real footage on the target track that Step 2's
    // later trim can't undo (a trim only shrinks the AL clip; it doesn't restore what
    // the overwrite already erased).
    if (clipItem && typeof clipItem.createSetInOutPointsAction === "function") {
      const setDuration = () => {
        try {
          freshProject.executeTransaction((compound) => {
            const inOut = clipItem.createSetInOutPointsAction(tickTime(0n), tickTime(durTicks));
            if (inOut) compound.addAction(inOut);
          }, "CutDeck: Set Adjustment Layer Duration");
        } catch (_) {}
      };
      if (typeof freshProject.lockedAccess === "function") {
        freshProject.lockedAccess(setDuration);
      } else {
        setDuration();
      }
    }

    let ok = false;
    let thrown = null;

    const run = () => {
      try {
        ok = freshProject.executeTransaction((compound) => {
          let action = null;
          let lastErr = null;

          if (clipItem) {
            const attempts = [];
            if (targetTrack >= trackCountNow) {
              attempts.push(() => editor.createInsertProjectItemAction(clipItem, tStart, Number(targetTrack), -1, false));
              attempts.push(() => editor.createOverwriteItemAction(clipItem, tStart, Number(targetTrack), -1));
            } else {
              attempts.push(() => editor.createOverwriteItemAction(clipItem, tStart, Number(targetTrack), -1));
              attempts.push(() => editor.createInsertProjectItemAction(clipItem, tStart, Number(targetTrack), -1, false));
            }
            attempts.push(() => editor.createOverwriteItemAction(clipItem, tStart, Number(targetTrack), 0));
            // clipItem is alItem after ClipProjectItem.cast() — that cast has been
            // observed to make Premiere reject the placement with "Invalid parameter"
            // in cases where the pre-cast item works fine. Fall back to it.
            if (alItem && alItem !== clipItem) {
              attempts.push(() => editor.createOverwriteItemAction(alItem, tStart, Number(targetTrack), -1));
              attempts.push(() => editor.createInsertProjectItemAction(alItem, tStart, Number(targetTrack), -1, false));
            }

            for (const fn of attempts) {
              try {
                action = fn();
                if (action) break;
              } catch (e) {
                lastErr = e;
              }
            }

            if (!action) {
              const name = clipItem?.name || alItem?.name || "unknown";
              const type = clipItem?.type !== undefined ? clipItem.type : "unknown";
              throw new Error(`Could not place: ${lastErr ? (lastErr.message || String(lastErr)) : "Invalid parameter"}. (Item: "${name}", Type: ${type}, V-Track: V${targetTrack + 1})`);
            }
          }

          if (!action) {
            throw new Error(`No clipItem was available to place at V${targetTrack + 1}.`);
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
    // Also doubles as placement verification — see `verified` below.
    let verified = false;
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
              let trimOk = false;
              let trimErr = null;
              const trimRun = () => {
                try {
                  trimOk = freshProject.executeTransaction((compound) => {
                    if (typeof it.createSetEndAction !== "function") {
                      throw new Error("track item has no createSetEndAction");
                    }
                    const setEndAction = it.createSetEndAction(tickTime(p.endTicks));
                    if (!setEndAction) {
                      throw new Error("createSetEndAction returned falsy");
                    }
                    if (!compound.addAction(setEndAction)) {
                      throw new Error("addAction(setEndAction) returned false");
                    }
                  }, "CutDeck: Trim Adjustment Layer Duration");
                } catch (e) {
                  trimErr = e;
                }
              };
              if (typeof freshProject.lockedAccess === "function") {
                freshProject.lockedAccess(trimRun);
              } else {
                trimRun();
              }

              // Read back the real result — don't trust the API's claimed success,
              // confirm the item's end time actually moved.
              let actualEndTicks = null;
              try {
                const eTimeAfter = typeof it.getEndTime === "function" ? await it.getEndTime() : it.endTime;
                actualEndTicks = toBigIntTicks(eTimeAfter);
              } catch (_) {}
              console.log("Adjustment Layer trim result:", {
                trimOk,
                trimErr: trimErr ? (trimErr.message || String(trimErr)) : null,
                requestedEndTicks: p.endTicks.toString(),
                actualEndTicks: actualEndTicks !== null ? actualEndTicks.toString() : null,
                trimHeld: actualEndTicks !== null && actualEndTicks <= (p.endTicks + tpf)
              });

              // Set label color and name.
              // Neither setColorLabel nor setName is a real plain method — confirmed against
              // the official class references, so both used to silently no-op the same way
              // setScaleToFrameSize did above.
              //
              // Name: VideoClipTrackItem.createSetNameAction() is real and per-instance —
              // wrapped in a transaction like every other mutation here, this now actually
              // renames just this placement.
              //
              // Color: VideoClipTrackItem has no color-label action at all (confirmed — only
              // createSetNameAction lives on it); the only real API is
              // ClipProjectItem.createSetColorLabelAction() on the shared master AL project
              // item. Every placement reuses that same master clip, so this recolors every
              // existing and future instance of it, not just this one placement — a genuine
              // Premiere API limitation (no per-instance timeline color override is exposed),
              // not a bug in this call.
              try {
                if (clipItem && typeof clipItem.createSetColorLabelAction === "function") {
                  const setColor = () => {
                    try {
                      freshProject.executeTransaction((compound) => {
                        const colorAction = clipItem.createSetColorLabelAction(getLabelIndex(options.color));
                        if (colorAction) compound.addAction(colorAction);
                      }, "CutDeck: Set Adjustment Layer Color Label");
                    } catch (_) {}
                  };
                  if (typeof freshProject.lockedAccess === "function") {
                    freshProject.lockedAccess(setColor);
                  } else {
                    setColor();
                  }
                }
              } catch (_) {}
              try {
                if (typeof it.createSetNameAction === "function") {
                  const setNameRun = () => {
                    try {
                      freshProject.executeTransaction((compound) => {
                        const nameAction = it.createSetNameAction(p.name);
                        if (!nameAction) throw new Error("createSetNameAction returned falsy");
                        if (!compound.addAction(nameAction)) throw new Error("addAction(nameAction) returned false");
                      }, "CutDeck: Name Adjustment Layer");
                    } catch (_) {}
                  };
                  if (typeof freshProject.lockedAccess === "function") {
                    freshProject.lockedAccess(setNameRun);
                  } else {
                    setNameRun();
                  }
                }
              } catch (_) {}
              verified = true;
              placedItems.push(it);
              break;
            }
          }
        }
      }
    } catch (err) {
      console.log("Trimming duration failed:", err);
    }

    if (!verified) {
      throw new Error(
        `Placed an Adjustment Layer on V${targetTrack + 1} but could not find it there afterward — ` +
        `the edit may have landed on the wrong track instead of a clip you have. Check Edit > Undo History ` +
        `and Ctrl+Z if anything looks wrong before placing more.`
      );
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
    selectedCount: clipsWithTimes.length,
    sequenceWidth,
    sequenceHeight,
    placedItems
  };
}

module.exports = {
  placeAdjustmentLayersOnTimeline,
  findAdjustmentLayerItem,
  getOrCreateAdjBin,
  pickBestCandidate,
  detectResolutionFromMetadata,
  // Exported for timeline/effects.js: the robust (never-throws) getTrackItems lookup, reused
  // rather than re-guessed — see that module's getSelectedTrackItems.
  getTrackClipItems,
  CUTDECK_BIN_NAME,
  ADJ_BIN_NAME,
};
