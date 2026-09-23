// Single owner for track items lookup and timeline selection.
// Part of Move 5 (issue #53, docs/arch-design-cutdeck-panel.md).
//
// Host-agnostic: takes ppro as an optional parameter instead of requiring
// "premierepro" at module scope, allowing pure off-host testing under Node.js.

// Same lookup, but rethrows the last error instead of masking "couldn't read this
// track" as "this track is empty" — callers that use the result to avoid colliding
// with existing clips (findSmartStackTrack) must be able to tell the difference,
// since treating an unreadable track as empty risks overwriting real footage on it.
async function getTrackClipItemsOrThrow(track, ppro) {
  if (!track || typeof track.getTrackItems !== "function") return [];
  const clipType = (ppro && ppro.Constants && ppro.Constants.TrackItemType && ppro.Constants.TrackItemType.CLIP !== undefined)
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

// Safe helper to get clip track items (never throws if Constants or arguments differ)
async function getTrackClipItems(track, ppro) {
  try {
    return await getTrackClipItemsOrThrow(track, ppro);
  } catch (_) {
    return [];
  }
}

// Adobe declares getIsSelected(): Promise<boolean> on VideoClipTrackItem/AudioClipTrackItem —
// confirmed against @adobe/premierepro's declarations, and confirmed LIVE on this build
// (transform-panel-plan.md Part 1a): `typeof item.getIsSelected` is "function",
// `item.isSelected` is `undefined`. `isSelected` appears nowhere in the declarations at any
// version in this line. Tried first; the old member checks are kept only as a last-resort
// compatibility path for a future build that might expose them differently — never relied on.
async function isTrackItemSelected(it) {
  if (!it) return false;
  if (typeof it.getIsSelected === "function") {
    try { return await it.getIsSelected(); } catch (_) { return false; }
  }
  if (typeof it.isSelected === "function") {
    try { return await it.isSelected(); } catch (_) { return false; }
  }
  if (it.isSelected !== undefined) return !!it.isSelected;
  if (it.selected !== undefined) return !!it.selected;
  return false;
}

// Every track item selected on the timeline right now, unfiltered — both effects.js's capture
// job and transform/params.js's readers need whatever's actually selected (an Adjustment Layer,
// a clip, a graphic), so unlike getSelectedVideoClips this does NOT exclude Adjustment Layers,
// and is not restricted to video tracks either.
async function getSelectedTrackItems(seq, ppro) {
  if (!seq) return [];
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
  } catch (_) {}

  if (rawItems.length > 0) return rawItems;

  // seq.getSelection() has already proven unreliable on this build once before (see
  // getSelectedVideoClips, which needed the exact same fallback) — walk every video AND
  // audio track's own items and ask each one directly whether it's selected.
  const found = [];
  try {
    const videoCount = typeof seq.getVideoTrackCount === "function" ? await seq.getVideoTrackCount() : 0;
    for (let v = 0; v < videoCount; v++) {
      const track = await seq.getVideoTrack(v);
      const items = await getTrackClipItems(track, ppro);
      for (const it of items) if (await isTrackItemSelected(it)) found.push(it);
    }
  } catch (_) {}
  try {
    const audioCount = typeof seq.getAudioTrackCount === "function" ? await seq.getAudioTrackCount() : 0;
    for (let a = 0; a < audioCount; a++) {
      const track = await seq.getAudioTrack(a);
      const items = await getTrackClipItems(track, ppro);
      for (const it of items) if (await isTrackItemSelected(it)) found.push(it);
    }
  } catch (_) {}
  return found;
}

async function getFirstSelectedTrackItem(seq, ppro) {
  const items = await getSelectedTrackItems(seq, ppro);
  return items.length > 0 ? items[0] : null;
}

// Helper to read selected VIDEO clips on active sequence (strictly ignoring audio clips and adjustment layers).
// Replaces today's adjustmentLayer.js getSelectedTimelineClips, built on getSelectedTrackItems.
async function getSelectedVideoClips(ppro, seq) {
  if (!seq) return [];
  const rawItems = await getSelectedTrackItems(seq, ppro);
  if (!rawItems || rawItems.length === 0) return [];

  // Filter: ONLY include Video clips (exclude Audio clips and Adjustment Layers!)
  // In Premiere, linked selection selects Audio clips which may span longer cuts than Video!
  // Also record which video track each item lives on — callers need to tell V1 (the
  // canvas real footage lives on) apart from a duplicate clip sitting on a higher track.
  const videoClips = [];
  const videoItemsTrackMap = new Map();

  try {
    const trackCount = typeof seq.getVideoTrackCount === "function" ? await seq.getVideoTrackCount() : 0;
    for (let v = 0; v < trackCount; v++) {
      const track = await seq.getVideoTrack(v);
      const vItems = await getTrackClipItems(track, ppro);
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
    if (ppro && ppro.AudioClipTrackItem && it instanceof ppro.AudioClipTrackItem) {
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

module.exports = {
  getTrackClipItemsOrThrow,
  getTrackClipItems,
  isTrackItemSelected,
  getSelectedTrackItems,
  getFirstSelectedTrackItem,
  getSelectedVideoClips,
};
