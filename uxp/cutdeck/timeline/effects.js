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

// Selection lookup, the fixed-effect skip list, the {value:{value:X}} unwrap and the
// transaction helper all live in timeline/componentAccess.js — lifted out of this file once
// transform/params.js became a second consumer (see that module's header and
// docs/research/cutdeck-transform-panel-plan.md Part 2). Re-exported below for callers that
// already import them from here.
const {
  FIXED_EFFECT_DISPLAY_NAMES,
  isFixedComponent,
  getSelectedTrackItems,
  getFirstSelectedTrackItem,
  unwrapKeyframeValue,
  runInTransaction,
} = require("./componentAccess.js");

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
          value = unwrapKeyframeValue(kf);
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

  // Phase 1: insert every component. Confirmed at runtime: the object VideoFilterFactory.
  // createComponent() returns is a VideoFilterComponent, not the chain's Component class — it
  // has no getParam ("component.getParam is not a function"), so its params cannot be touched
  // before insertion. The insert must commit in its own transaction before a real,
  // param-capable Component exists to fetch back from the chain.
  runInTransaction(project, "CutDeck: Apply Captured Preset (insert)", (compound) => {
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
  runInTransaction(project, "CutDeck: Apply Captured Preset (values)", (compound) => {
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
