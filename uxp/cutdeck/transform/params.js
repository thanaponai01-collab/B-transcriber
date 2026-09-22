// transform/params.js — HOST DISCOVERY ONLY for the Transform & Align panel (Phase 1 of
// docs/research/cutdeck-transform-panel-plan.md). Finds the Motion component on a track item
// and reads its four semantic fields (position, scale, rotation, anchor) by the param indices
// this build was PROVEN to use — Part 1a of the plan, a live Premiere run (26.5.1) on two real
// clip shapes, matched against the Properties panel's own pixel readout to sub-pixel accuracy:
//
//   index 0 Position       array[2], normalized to the SEQUENCE frame, independently per axis
//   index 1 Scale          number (percent), the uniform scale value
//   index 3 Uniform Scale  boolean (this build's ZString gives it no displayName — index only)
//   index 4 Rotation       number (degrees)
//   index 5 Anchor Point   array[2], same normalized space as Position
//
// Matched by matchName ("AE.ADBE Motion"), never displayName — displayName is localized
// (effects.js's FIXED_EFFECT_DISPLAY_NAMES warning applies here too). Never guesses: a build
// where the chain, the component or a param does not resolve returns null for that piece, not
// a zero — turning that into "unavailable" is the panel's job, not this module's.
//
// No geometry (normalized-to-pixel conversion lives in transform/geometry.js, which is pure
// and does not touch premierepro) and no DOM.

const { unwrapKeyframeValue } = require("../timeline/componentAccess.js");

const MOTION_MATCH_NAME = "AE.ADBE Motion";

const PARAM_INDEX = {
  position: 0,
  scale: 1,
  scaleWidth: 2,
  uniformScale: 3,
  rotation: 4,
  anchorPoint: 5,
};

// Searches the item's component chain for the real Motion component. Never throws: a missing
// chain, a component that won't report its match name, or a host with no getComponentChain at
// all are all "not found", same as capabilityProbe.js's looksLikeTransformComponent scan.
async function findMotionComponent(item) {
  if (!item || typeof item.getComponentChain !== "function") return null;
  let chain;
  try {
    chain = await item.getComponentChain();
  } catch (_) {
    return null;
  }
  if (!chain || typeof chain.getComponentCount !== "function") return null;
  const count = chain.getComponentCount();
  for (let i = 0; i < count; i++) {
    let component;
    try {
      component = chain.getComponentAtIndex(i);
    } catch (_) {
      continue;
    }
    if (!component) continue;
    let matchName = null;
    try {
      matchName = await component.getMatchName();
    } catch (_) {
      continue;
    }
    if (matchName === MOTION_MATCH_NAME) return component;
  }
  return null;
}

// Reads one param by index off an already-found component. Returns null when the param itself
// does not resolve, so one bad field never hides the others readTransform() reads alongside it.
async function readParamField(component, index) {
  if (!component || typeof component.getParam !== "function") return null;
  let param;
  try {
    param = component.getParam(index);
  } catch (_) {
    return null;
  }
  if (!param) return null;

  let isTimeVarying = false;
  try {
    isTimeVarying = typeof param.isTimeVarying === "function" ? await param.isTimeVarying() : false;
  } catch (_) {
    isTimeVarying = false;
  }

  // getStartValue() takes no TickTime — it sidesteps the clip-relative-vs-sequence-relative
  // ambiguity that isn't documented anywhere in Adobe's reference (effects.js standardized on
  // the same call for the same reason). For an animated param this is only its value AT the
  // start keyframe, which is exactly why isTimeVarying is reported alongside it: the plan's
  // "skip animated params with a visible explanation" rule depends on the caller checking it
  // before trusting `value`.
  if (typeof param.getStartValue !== "function") return { isTimeVarying, value: null };
  try {
    const keyframe = await param.getStartValue();
    return { isTimeVarying, value: unwrapKeyframeValue(keyframe) };
  } catch (_) {
    return { isTimeVarying, value: null };
  }
}

// Reads the Motion component's four semantic fields for `item`. Returns null when the item has
// no readable Motion component at all — the panel's "unavailable" case, per Phase 1's
// definition of done. Each field is independently null-able so one bad param doesn't take the
// other three down with it.
async function readTransform(item) {
  const component = await findMotionComponent(item);
  if (!component) return null;
  const [position, scale, uniformScale, rotation, anchorPoint] = await Promise.all([
    readParamField(component, PARAM_INDEX.position),
    readParamField(component, PARAM_INDEX.scale),
    readParamField(component, PARAM_INDEX.uniformScale),
    readParamField(component, PARAM_INDEX.rotation),
    readParamField(component, PARAM_INDEX.anchorPoint),
  ]);
  return { position, scale, uniformScale, rotation, anchorPoint };
}

// The sequence's own frame size, read the same dual-route way capabilityProbe.js and
// adjustmentLayer.js already do (SequenceSettings has no plain width/height fields — confirmed
// against the official class reference — it's getVideoFrameRect(): RectF). Needed to convert
// Position/Anchor Point's normalized values into the pixel numbers Effect Controls displays;
// the conversion itself is pure math and lives in transform/geometry.js, not here.
async function readSequenceFrameSize(seq) {
  if (!seq) return null;
  try {
    if (typeof seq.getSettings === "function") {
      const settings = await seq.getSettings();
      if (settings && typeof settings.getVideoFrameRect === "function") {
        const rect = await settings.getVideoFrameRect();
        if (rect && rect.width && rect.height) return { width: rect.width, height: rect.height };
      }
    }
  } catch (_) {}
  try {
    if (typeof seq.getFrameSize === "function") {
      const rect = await seq.getFrameSize();
      if (rect && rect.width && rect.height) return { width: rect.width, height: rect.height };
    }
  } catch (_) {}
  return null;
}

module.exports = {
  MOTION_MATCH_NAME,
  PARAM_INDEX,
  findMotionComponent,
  readTransform,
  readSequenceFrameSize,
};
