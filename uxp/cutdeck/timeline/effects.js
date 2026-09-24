// Real Premiere effect application for CutDeck's quick-effect preset buttons — separate from
// timeline/adjustmentLayer.js, which only places/finds the Adjustment Layer. This module is
// the piece that turns a captured preset into an actual VideoComponentChain mutation on the AL
// that adjustmentLayer.js just placed.
//
// Static values are read with ComponentParam.getStartValue() — no TickTime argument at all — to
// stay clear of time references entirely for the static case (an earlier version queried
// getValueAtTime(trackItem.getStartTime()) and silently dropped every edited value).
//
// Keyframes (animated presets): the Check Keyframes probe (capabilityProbe.js
// probeKeyframeTiming) settled the time reference on Premiere 26.5, 2026-09-23 —
// getKeyframeListAsTickTimes() is MEDIA-relative: a keyframe on a clip's first frame reads back
// as exactly that clip's getInPoint(). So a captured keyframe is stored as an offset from the
// clip's first frame (keyframe time − source In point), in ticks, which is frame-rate
// independent; applying adds it to the TARGET item's own In point. The same probe recorded the
// interpolation numbers (LINEAR 0, HOLD 4, BEZIER 5), which are stored as-is — they come from
// Keyframe.getTemporalInterpolationMode() and go back through the documented
// createSetInterpolationAtKeyframeAction. Point params (Position, Anchor Point) resolve to
// PointKeyframe, which has no interpolation getter in Adobe's declarations, so their mode is
// recorded as null and left at Premiere's default.
//
// Keyframes are replayed at the same offsets from the start, not stretched: a 5-frame zoom
// stays 5 frames on a 2-second Adjustment Layer.
//
// API references checked: developer.adobe.com/premiere-pro/uxp/ppro-reference/classes/
// component, componentparam, keyframe, videocomponentchain, videofilterfactory, and
// @adobe/premierepro@26.2.1's premierepro.d.ts — plus the working sample at
// AdobeDocs/uxp-premiere-pro-samples, sample-panels/premiere-api/src/effects.ts (the
// transaction/lockedAccess shape below is lifted directly from that sample, same as every other
// mutation in this plugin).

// Selection lookup, the fixed-effect skip list, the {value:{value:X}} unwrap and the
// transaction helper all live in timeline/componentAccess.js — lifted out of this file once
// transform/params.js became a second consumer (see that module's header and
// docs/research/cutdeck-transform-panel-plan.md Part 2). Re-exported below for callers that
// already import them from here.
const {
  getSelectedTrackItems,
  getFirstSelectedTrackItem,
} = require("../host/trackItems.js");
const {
  FIXED_EFFECT_DISPLAY_NAMES,
  isFixedComponent,
  unwrapKeyframeValue,
} = require("../host/components.js");
const { toTicks } = require("../host/ticks.js");
const { runTransaction } = require("../host/project.js");

/* Captured point params (Anchor Point, Position) read back as plain [x, y] arrays, but
   createKeyframe only accepts a real PointF for them — an array throws "Illegal Parameter type"
   (UXPLogs, 2026-09-23: every Anchor Point / Position in every applied preset). Convert here;
   every other value type passes through unchanged. */
function toParamValue(ppro, value) {
  const isPair = Array.isArray(value) && value.length === 2 && value.every((n) => typeof n === "number");
  const isXY = value && typeof value === "object" && !Array.isArray(value)
    && typeof value.x === "number" && typeof value.y === "number";
  if ((isPair || isXY) && ppro && typeof ppro.PointF === "function") {
    return isPair ? new ppro.PointF(value[0], value[1]) : new ppro.PointF(value.x, value.y);
  }
  return value;
}

/* Pure: where each captured keyframe lands on a target whose source In point is
   `targetInTicks` (BigInt). Returns tick strings, ready for TickTime.createWithTicks. */
function placeKeyframes(keyframes, targetInTicks) {
  return keyframes.map((k) => (targetInTicks + BigInt(k.offsetTicks)).toString());
}

async function readKeyframes(param, inPointTicks) {
  const times = await param.getKeyframeListAsTickTimes();
  const keyframes = [];
  for (const t of times || []) {
    const kf = await param.getKeyframePtr(t);
    let mode = null;
    if (kf && typeof kf.getTemporalInterpolationMode === "function") {
      try { mode = await kf.getTemporalInterpolationMode(); } catch (_) { mode = null; }
    }
    keyframes.push({
      offsetTicks: (toTicks(t) - inPointTicks).toString(),
      value: unwrapKeyframeValue(kf),
      mode: typeof mode === "number" ? mode : null,
    });
  }
  return keyframes;
}

// Reads trackItem's real, currently-applied effect stack (skipping Premiere's own fixed
// Motion/Opacity/Time Remapping) into a plain, JSON-serializable preset object. A keyframed
// param also carries `keyframes: [{offsetTicks, value, mode}]` (see the file header).
async function captureEffectFromTrackItem(ppro, trackItem) {
  if (!trackItem || typeof trackItem.getComponentChain !== "function") {
    throw new Error("This item has no effect chain to capture from.");
  }
  const chain = await trackItem.getComponentChain();
  if (!chain) throw new Error("Could not read this item's effect chain.");
  const count = chain.getComponentCount();
  // Only needed for keyframes, so only read when something is animated.
  let inPointTicks = null;

  const components = [];
  let animatedCount = 0;
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
      // Confirmed at runtime (2026-09-22 console capture on a Transform component): the
      // resolved Keyframe's .value is itself a generic {value: <actual>} holder — unwrapped by
      // unwrapKeyframeValue.
      let value = null;
      if (typeof param.getStartValue === "function") {
        try {
          const kf = await param.getStartValue();
          value = unwrapKeyframeValue(kf);
        } catch (_) { value = null; }
      }
      const entry = { index: p, displayName: param.displayName || `param[${p}]`, value };

      let varying = false;
      try { varying = typeof param.isTimeVarying === "function" && !!(await param.isTimeVarying()); } catch (_) { varying = false; }
      if (varying) {
        if (inPointTicks === null) inPointTicks = toTicks(await trackItem.getInPoint());
        entry.keyframes = await readKeyframes(param, inPointTicks);
        if (entry.keyframes.length) animatedCount++;
      }
      params.push(entry);
    }
    components.push({ matchName, displayName, params });
  }

  if (components.length === 0) {
    throw new Error(
      "No real effect found on this item beyond Premiere's own Motion/Opacity/Time Remapping " +
      "— add an effect to it in Premiere's Effect Controls panel first, then Capture."
    );
  }

  return { components, animatedCount };
}

// Replays a captured preset's real components — static values, and keyframes where captured —
// onto trackItem's component chain. Returns { warnings: string[] }: anything that did not land
// as captured, including a keyframe read-back that doesn't match.
async function applyCapturedPreset(ppro, project, trackItem, preset) {
  return applyCapturedPresetToAll(ppro, project, [trackItem], preset);
}

// Same, onto every item at once: each phase is ONE transaction across all items, so N ALs
// cost at most 5 undo steps instead of 5 per AL (review 2026-09-24). The phases still commit
// in order — an insert must land before its params exist to set.
async function applyCapturedPresetToAll(ppro, project, trackItems, preset) {
  if (!preset || !Array.isArray(preset.components) || preset.components.length === 0) {
    throw new Error("This preset has no captured effect data.");
  }
  const warnings = [];
  const warn = (msg) => { warnings.push(msg); console.warn("CutDeck: " + msg); };
  const targets = [];
  for (const trackItem of trackItems) {
    if (!trackItem || typeof trackItem.getComponentChain !== "function") {
      throw new Error("This track item has no component chain to add an effect to.");
    }
    const chain = await trackItem.getComponentChain();
    if (!chain) throw new Error("Could not read this item's effect chain.");
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
    targets.push({ trackItem, chain, startIndex: chain.getComponentCount(), created });
  }

  // Phase 1: insert every component. Confirmed at runtime: the object VideoFilterFactory.
  // createComponent() returns is a VideoFilterComponent, not the chain's Component class — it
  // has no getParam ("component.getParam is not a function"), so its params cannot be touched
  // before insertion. The insert must commit in its own transaction before a real,
  // param-capable Component exists to fetch back from the chain.
  runTransaction(project, "CutDeck: Apply Captured Preset (insert)", (compound) => {
    for (const { chain, startIndex, created } of targets) {
      let nextIndex = startIndex;
      for (const { component, spec } of created) {
        const insertAction = chain.createInsertComponentAction(component, nextIndex);
        if (!insertAction) throw new Error(`Could not insert "${spec.displayName || spec.matchName}".`);
        if (!compound.addAction(insertAction)) throw new Error("addAction(insert) returned false");
        nextIndex++;
      }
    }
  });

  // Re-fetch each just-inserted component from the chain as a real Component (which does have
  // getParam), and pair every captured param with its live counterpart once.
  const pairs = [];
  for (const t of targets) {
    const liveChain = await t.trackItem.getComponentChain();
    t.created.forEach(({ spec }, k) => {
      const name = spec.displayName || spec.matchName;
      const liveComponent = liveChain.getComponentAtIndex(t.startIndex + k);
      if (!liveComponent) {
        warn(`could not re-fetch "${name}" after insert — its values are left at default.`);
        return;
      }
      for (const p of (spec.params || [])) {
        const label = `"${name}" param[${p.index}] (${p.displayName})`;
        let param = null;
        try { param = liveComponent.getParam(p.index); } catch (_) { param = null; }
        if (!param) { warn(`getParam(${p.index}) returned nothing for "${name}" — left at default.`); continue; }
        pairs.push({ p, param, label, t });
      }
    });
  }
  const animated = pairs.filter(({ p }) => Array.isArray(p.keyframes) && p.keyframes.length > 0);

  // Phase 2: static values, for every param that isn't animated.
  runTransaction(project, "CutDeck: Apply Captured Preset (values)", (compound) => {
    for (const { p, param, label } of pairs) {
      if (Array.isArray(p.keyframes) && p.keyframes.length > 0) continue;
      if (p.value === null || p.value === undefined) {
        warn(`${label} has no captured value — left at default.`);
        continue;
      }
      try {
        const setAction = param.createSetValueAction(param.createKeyframe(toParamValue(ppro, p.value)), true);
        if (setAction) compound.addAction(setAction);
        else warn(`createSetValueAction returned nothing for ${label} — left at default.`);
      } catch (e) {
        // A captured value that no longer fits this param's type on the recreated component —
        // skip just this one parameter rather than aborting the whole preset.
        warn(`setting ${label} to ${JSON.stringify(p.value)} threw: ${e && e.message}`);
      }
    }
  });

  if (animated.length === 0) return { warnings };

  const TickTime = ppro.TickTime;
  for (const t of targets) {
    if (animated.some((a) => a.t === t)) t.targetIn = toTicks(await t.trackItem.getInPoint());
  }

  // Phase 3: turn keyframing on (the stopwatch). Its own transaction, so the params are
  // time-varying before any keyframe is added to them.
  runTransaction(project, "CutDeck: Apply Captured Preset (enable keyframes)", (compound) => {
    for (const { param } of animated) compound.addAction(param.createSetTimeVaryingAction(true));
  });

  // Phase 4: the keyframes themselves, at each target's In point + captured offset.
  runTransaction(project, "CutDeck: Apply Captured Preset (keyframes)", (compound) => {
    for (const { p, param, label, t } of animated) {
      const at = placeKeyframes(p.keyframes, t.targetIn);
      p.keyframes.forEach((k, i) => {
        try {
          const keyframe = param.createKeyframe(toParamValue(ppro, k.value));
          keyframe.position = TickTime.createWithTicks(at[i]);
          compound.addAction(param.createAddKeyframeAction(keyframe));
        } catch (e) {
          warn(`keyframe ${i + 1} of ${label} threw: ${e && e.message}`);
        }
      });
    }
  });

  // Phase 5: interpolation (Linear / Hold / Bezier), where it was readable at capture.
  const withMode = animated.filter(({ p }) => p.keyframes.some((k) => typeof k.mode === "number"));
  if (withMode.length) {
    runTransaction(project, "CutDeck: Apply Captured Preset (interpolation)", (compound) => {
      for (const { p, param, label, t } of withMode) {
        const at = placeKeyframes(p.keyframes, t.targetIn);
        p.keyframes.forEach((k, i) => {
          if (typeof k.mode !== "number") return;
          try {
            compound.addAction(param.createSetInterpolationAtKeyframeAction(TickTime.createWithTicks(at[i]), k.mode, true));
          } catch (e) {
            warn(`interpolation on keyframe ${i + 1} of ${label} threw: ${e && e.message}`);
          }
        });
      }
    });
  }

  // Read back: the keyframe list must be exactly the captured times. Anything else — an extra
  // keyframe the stopwatch added on its own, a dropped one — is reported, not assumed away.
  for (const { p, param, label, t } of animated) {
    try {
      const got = ((await param.getKeyframeListAsTickTimes()) || []).map((x) => toTicks(x).toString());
      const want = placeKeyframes(p.keyframes, t.targetIn);
      if (got.length !== want.length || want.some((w) => !got.includes(w))) {
        warn(`${label}: expected keyframes at ${want.join(", ")} but found ${got.join(", ") || "none"}.`);
      }
    } catch (e) {
      warn(`could not read back keyframes of ${label}: ${e && e.message}`);
    }
  }

  return { warnings };
}

module.exports = {
  getSelectedTrackItems,
  getFirstSelectedTrackItem,
  captureEffectFromTrackItem,
  applyCapturedPreset,
  applyCapturedPresetToAll,
  placeKeyframes,
  toParamValue,
  isFixedComponent,
  FIXED_EFFECT_DISPLAY_NAMES,
};
