// Shared low-level Premiere component-chain access, lifted out of timeline/effects.js the
// moment transform/params.js needed the same selection lookup and value unwrap — see
// docs/research/cutdeck-transform-panel-plan.md Part 2 ("What they genuinely share... should
// be lifted out of effects.js into a small timeline/componentAccess.js... not duplicated and
// not imported across the seam. That lift is part of Phase 1, not a later cleanup.").
//
// transform/params.js must not import timeline/effects.js and vice versa — this module is the
// one place both are allowed to depend on.

// Reused, not re-guessed: adjustmentLayer.js already proved seq.getSelection() alone is
// unreliable on this Premiere build (see its getSelectedTimelineClips) and built a
// never-throws getTrackItems lookup to work around it. adjustmentLayer.js requires
// "premierepro" at module scope (it is not host-agnostic like this module), so outside a real
// Premiere host — e.g. these tests, run under plain node — that require throws before any of
// its exports can be reached. Caught here rather than left to crash callers that only need
// getSelectedTrackItems for its primary seq.getSelection() route: the fallback below still
// gets a real, if simpler, tolerant getTrackItems call instead of losing the whole module.
let getTrackClipItems;
try {
  ({ getTrackClipItems } = require("./adjustmentLayer.js"));
} catch (_) {
  getTrackClipItems = async (track) => {
    if (!track || typeof track.getTrackItems !== "function") return [];
    try { return (await track.getTrackItems()) || []; } catch (_) { return []; }
  };
}

// Every plain video clip and Adjustment Layer carries these fixed effects in Premiere's own
// Effect Controls panel — never something a user added. Matched by display name because this
// build's real matchNames were not confirmed when effects.js was written (Adobe's own sample
// only shows a NEW effect landing at chain index 2 on a plain clip, which implies but does not
// document two fixed entries before it). Run the "Check Effect Chain" probe (capabilityProbe.js)
// against a plain, effect-free Adjustment Layer to get the real matchNames for this build, then
// prefer matching on matchName here instead — it's stable across UI language, display name isn't.
const FIXED_EFFECT_DISPLAY_NAMES = new Set(["motion", "opacity", "time remapping"]);

function isFixedComponent(displayName) {
  return FIXED_EFFECT_DISPLAY_NAMES.has(String(displayName || "").trim().toLowerCase());
}

// Adobe declares getIsSelected(): Promise<boolean> on VideoClipTrackItem/AudioClipTrackItem —
// confirmed against @adobe/premierepro's declarations, and confirmed LIVE on this build
// (transform-panel-plan.md Part 1a): `typeof item.getIsSelected` is "function",
// `item.isSelected` is `undefined`. `isSelected` appears nowhere in the declarations at any
// version in this line. Tried first; the old member checks are kept only as a last-resort
// compatibility path for a future build that might expose them differently — never relied on.
async function isTrackItemSelected(it) {
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
// a clip, a graphic), so unlike adjustmentLayer.js's getSelectedTimelineClips this must NOT
// exclude Adjustment Layers, and is not restricted to video tracks either.
async function getSelectedTrackItems(seq) {
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
  // adjustmentLayer.js's getSelectedTimelineClips, which needed the exact same fallback) — walk
  // every video AND audio track's own items and ask each one directly whether it's selected.
  const found = [];
  try {
    const videoCount = typeof seq.getVideoTrackCount === "function" ? await seq.getVideoTrackCount() : 0;
    for (let v = 0; v < videoCount; v++) {
      const track = await seq.getVideoTrack(v);
      const items = await getTrackClipItems(track);
      for (const it of items) if (await isTrackItemSelected(it)) found.push(it);
    }
  } catch (_) {}
  try {
    const audioCount = typeof seq.getAudioTrackCount === "function" ? await seq.getAudioTrackCount() : 0;
    for (let a = 0; a < audioCount; a++) {
      const track = await seq.getAudioTrack(a);
      const items = await getTrackClipItems(track);
      for (const it of items) if (await isTrackItemSelected(it)) found.push(it);
    }
  } catch (_) {}
  return found;
}

async function getFirstSelectedTrackItem(seq) {
  const items = await getSelectedTrackItems(seq);
  return items.length > 0 ? items[0] : null;
}

// Confirmed at runtime (transform-panel-plan.md Part 1 item 3, and independently by
// effects.js's capture path): a resolved Keyframe's `.value` is itself a generic
// `{value: <actual>}` holder for every param type (PointF, boolean, number) — logged output was
// `{"value": {"value": [0.5, 0.5]}}` instead of the raw `[0.5, 0.5]`. This is documented in
// Adobe's own types (`Keyframe.value: { value: ... }`), so the unwrap is a contract, not a guess.
function unwrapKeyframeValue(keyframe) {
  if (keyframe === null || keyframe === undefined) return null;
  const raw = keyframe.value !== undefined ? keyframe.value : null;
  return (raw && typeof raw === "object" && !Array.isArray(raw) && "value" in raw) ? raw.value : raw;
}

// The transaction/lockedAccess shape every mutation in this plugin uses (lifted from the
// AdobeDocs sample-panels/premiere-api/src/effects.ts sample). Runs `fn` inside
// project.executeTransaction, wrapped in project.lockedAccess when the host provides it, and
// throws whatever executeTransaction threw (or a generic error) when it reports failure.
function runInTransaction(project, label, fn) {
  let ok = false;
  let thrown = null;
  const run = () => {
    try {
      ok = project.executeTransaction(fn, label);
    } catch (e) {
      thrown = e;
    }
  };
  if (typeof project.lockedAccess === "function") project.lockedAccess(run); else run();
  if (!ok) throw thrown || new Error(`Could not complete "${label}".`);
}

module.exports = {
  FIXED_EFFECT_DISPLAY_NAMES,
  isFixedComponent,
  isTrackItemSelected,
  getSelectedTrackItems,
  getFirstSelectedTrackItem,
  unwrapKeyframeValue,
  runInTransaction,
};
