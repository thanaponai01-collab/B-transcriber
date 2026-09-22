// Real Premiere effect application for CutDeck's quick-effect preset buttons — separate from
// timeline/adjustmentLayer.js, which only places/finds the Adjustment Layer. This module is
// the piece that was always missing: turning a captured preset into an actual
// VideoComponentChain mutation on the AL that adjustmentLayer.js just placed.
//
// v1 scope (deliberate): STATIC parameter values only, no keyframes/animation. Capture reads
// each param via ComponentParam.getStartValue() — no TickTime argument at all — specifically
// to avoid the clip-relative-vs-sequence-relative ambiguity that isn't documented anywhere in
// Adobe's reference (an earlier version queried getValueAtTime(trackItem.getStartTime()) and
// that mismatch silently dropped every edited value: this codebase has already been burned once
// by trusting an unverified Premiere timing assumption, see adjustmentLayer.js's
// Adjustment-Layer-scale history). Animated presets are a deliberate later step, gated on a
// probe the same way timelineRange.js's OUT_CONVENTION was — that probe still needs the real
// TickTime frame of reference, which this fix does not resolve, only sidesteps for the static
// case.
//
// API references checked: developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/
// component, componentparam, videocomponentchain, videofilterfactory, audiofilterfactory —
// and the working sample at AdobeDocs/uxp-premiere-pro-samples,
// sample-panels/premiere-api/src/effects.ts (the transaction/lockedAccess shape below is
// lifted directly from that sample, same as every other mutation in this plugin).

// Every plain video clip and Adjustment Layer carries these fixed effects in Premiere's own
// Effect Controls panel — never something a user added, so Capture must never mistake one for
// a real effect to replay. Matched by display name because this build's real matchNames were
// not confirmed at the time this was written (Adobe's own sample only shows a NEW effect
// landing at chain index 2 on a plain clip, which implies but does not document two fixed
// entries before it). Run the "Check Effect Chain" probe (capabilityProbe.js) against a plain,
// effect-free Adjustment Layer to get the real matchNames for this build, then prefer matching
// on matchName here instead — it's stable across UI language, display name isn't guaranteed to
// be.
const FIXED_EFFECT_DISPLAY_NAMES = new Set(["motion", "opacity", "time remapping"]);

// Reused, not re-guessed: adjustmentLayer.js already proved seq.getSelection() alone is
// unreliable on this Premiere build (see its getSelectedTimelineClips) and built a
// never-throws getTrackItems lookup to work around it.
const { getTrackClipItems } = require("./adjustmentLayer.js");

function isFixedComponent(displayName) {
  return FIXED_EFFECT_DISPLAY_NAMES.has(String(displayName || "").trim().toLowerCase());
}

async function isTrackItemSelected(it) {
  if (typeof it.isSelected === "function") {
    try { return await it.isSelected(); } catch (_) { return false; }
  }
  if (it.isSelected !== undefined) return !!it.isSelected;
  if (it.selected !== undefined) return !!it.selected;
  return false;
}

// Every track item selected on the timeline right now, unfiltered — both Capture and the
// Apply Effect job read whatever's actually selected (an Adjustment Layer or a clip), so
// unlike adjustmentLayer.js's getSelectedTimelineClips this must NOT exclude Adjustment
// Layers, and unlike that function this is not restricted to video tracks either.
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

// Reads trackItem's real, currently-applied effect stack (skipping Premiere's own fixed
// Motion/Opacity/Time Remapping) into a plain, JSON-serializable preset object. Static values
// only — see the v1 scope note at the top of this file.
async function captureEffectFromTrackItem(ppro, trackItem) {
  if (!trackItem || typeof trackItem.getComponentChain !== "function") {
    throw new Error("This item has no effect chain to capture from.");
  }
  const chain = await trackItem.getComponentChain();
  if (!chain) throw new Error("Could not read this item's effect chain.");
  const count = chain.getComponentCount();

  const components = [];
  for (let i = 0; i < count; i++) {
    const component = chain.getComponentAtIndex(i);
    if (!component) continue;
    const displayName = await component.getDisplayName();
    if (isFixedComponent(displayName)) continue;
    const matchName = await component.getMatchName();
    const paramCount = component.getParamCount();

    const params = [];
    for (let p = 0; p < paramCount; p++) {
      const param = component.getParam(p);
      if (!param) continue;
      // getStartValue() takes no TickTime — it sidesteps the clip-relative-vs-
      // sequence-relative ambiguity that getValueAtTime(startTime) had (see file
      // header): for a static (non-keyframed) param there's only one value, and
      // getStartValue() reads it directly without needing a time reference at all.
      //
      // Confirmed at runtime (2026-09-22 console capture on a Transform component): the
      // resolved Keyframe's .value is itself a generic {value: <actual>} holder for every
      // param type seen (PointF, boolean, number) — logged output was
      // {"value": {"value": [0.5, 0.5]}} instead of the raw [0.5, 0.5]. Unwrap that extra layer.
      let value = null;
      if (typeof param.getStartValue === "function") {
        try {
          const kf = await param.getStartValue();
          const raw = kf ? kf.value : null;
          value = (raw && typeof raw === "object" && !Array.isArray(raw) && "value" in raw) ? raw.value : raw;
        } catch (_) { value = null; }
      }
      params.push({ index: p, displayName: param.displayName || `param[${p}]`, value });
    }
    components.push({ matchName, displayName, params });
  }

  if (components.length === 0) {
    throw new Error(
      "No real effect found on this item beyond Premiere's own Motion/Opacity/Time Remapping " +
      "— add an effect to it in Premiere's Effect Controls panel first, then Capture."
    );
  }

  return { components };
}

// Replays a captured preset's real components (and their static param values) onto
// trackItem's component chain.
async function applyCapturedPreset(ppro, project, trackItem, preset) {
  if (!preset || !Array.isArray(preset.components) || preset.components.length === 0) {
    throw new Error("This preset has no captured effect data.");
  }
  if (!trackItem || typeof trackItem.getComponentChain !== "function") {
    throw new Error("This track item has no component chain to add an effect to.");
  }
  const chain = await trackItem.getComponentChain();
  if (!chain) throw new Error("Could not read this item's effect chain.");
  const startIndex = chain.getComponentCount();

  // Component creation is async (VideoFilterFactory.createComponent returns a Promise) but
  // project.executeTransaction's callback must be synchronous (same constraint every other
  // mutation in this plugin works under) — so every component is created up front, and only
  // the synchronous insert actions happen inside the first transaction.
  const created = [];
  for (const comp of preset.components) {
    const newComponent = await ppro.VideoFilterFactory.createComponent(comp.matchName);
    if (!newComponent) {
      throw new Error(`Premiere would not recreate "${comp.displayName || comp.matchName}".`);
    }
    created.push({ component: newComponent, spec: comp });
  }

  function runInTransaction(label, fn) {
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

  // Phase 1: insert every component. Confirmed at runtime: the object VideoFilterFactory.
  // createComponent() returns is a VideoFilterComponent, not the chain's Component class — it
  // has no getParam ("component.getParam is not a function"), so its params cannot be touched
  // before insertion. The insert must commit in its own transaction before a real,
  // param-capable Component exists to fetch back from the chain.
  runInTransaction("CutDeck: Apply Captured Preset (insert)", (compound) => {
    let nextIndex = startIndex;
    for (const { component, spec } of created) {
      const insertAction = chain.createInsertComponentAction(component, nextIndex);
      if (!insertAction) throw new Error(`Could not insert "${spec.displayName || spec.matchName}".`);
      if (!compound.addAction(insertAction)) throw new Error("addAction(insert) returned false");
      nextIndex++;
    }
  });

  // Phase 2: re-fetch each just-inserted component from the chain as a real Component (which
  // does have getParam) and set its captured values.
  const liveChain = await trackItem.getComponentChain();
  runInTransaction("CutDeck: Apply Captured Preset (values)", (compound) => {
    let index = startIndex;
    for (const { spec } of created) {
      const liveComponent = liveChain.getComponentAtIndex(index);
      index++;
      if (!liveComponent) {
        console.warn(`CutDeck: could not re-fetch "${spec.displayName || spec.matchName}" ` +
          `after insert — its values are left at default.`);
        continue;
      }
      for (const p of (spec.params || [])) {
        if (p.value === null || p.value === undefined) {
          console.warn(`CutDeck: preset "${spec.displayName || spec.matchName}" param[${p.index}] ` +
            `(${p.displayName}) has no captured value — left at default.`);
          continue;
        }
        try {
          const param = liveComponent.getParam(p.index);
          if (!param) {
            console.warn(`CutDeck: getParam(${p.index}) returned nothing for ` +
              `"${spec.displayName || spec.matchName}" — left at default.`);
            continue;
          }
          const keyframe = param.createKeyframe(p.value);
          const setAction = param.createSetValueAction(keyframe, true);
          if (setAction) compound.addAction(setAction);
          else console.warn(`CutDeck: createSetValueAction returned nothing for ` +
            `"${spec.displayName || spec.matchName}" param[${p.index}] (${p.displayName}), ` +
            `value=${JSON.stringify(p.value)} — left at default.`);
        } catch (e) {
          // A captured value that no longer fits this param's type on the recreated
          // component — skip just this one parameter rather than aborting the whole preset.
          console.warn(`CutDeck: setting "${spec.displayName || spec.matchName}" param[${p.index}] ` +
            `(${p.displayName}) to ${JSON.stringify(p.value)} threw: ${e && e.message}`);
        }
      }
    }
  });

  return true;
}

module.exports = {
  getSelectedTrackItems,
  getFirstSelectedTrackItem,
  captureEffectFromTrackItem,
  applyCapturedPreset,
  isFixedComponent,
  FIXED_EFFECT_DISPLAY_NAMES,
};
