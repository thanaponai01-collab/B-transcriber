// transform/geometry.js — PURE rect/point math for the Transform & Align panel. No
// require("premierepro"), so it is unit-testable off-host (plan Part 2's file layout,
// docs/research/cutdeck-transform-panel-plan.md).
//
// Phase 1 needs exactly one conversion: Position and Anchor Point are proven (Part 1a, a live
// Premiere run on two real clip shapes, matched against the Properties panel's own pixel
// readout to sub-pixel accuracy) to be [x, y] normalized to the SEQUENCE frame, independently
// per axis — pixel = fraction * frameWidth on x, fraction * frameHeight on y. Anchor and
// Distribute math (Phases 3+) will add real geometry here; nothing beyond this one conversion
// is built ahead of the phase that needs it.

// A point param has been observed in both an array [x, y] shape (the real build, Part 1a) and
// an {x, y} object shape (an earlier probe on the same build's params, see
// cutdeck_transform_probe.test.cjs's fixture, which captured both shapes deliberately because
// neither was documented). Accept both so a build-to-build shape change doesn't silently read
// garbage instead of refusing.
function pointXY(value) {
  if (!value) return null;
  if (Array.isArray(value) && value.length >= 2) {
    const x = value[0];
    const y = value[1];
    return typeof x === "number" && typeof y === "number" ? { x, y } : null;
  }
  if (typeof value === "object" && typeof value.x === "number" && typeof value.y === "number") {
    return { x: value.x, y: value.y };
  }
  return null;
}

// Converts a normalized Position/Anchor Point value to the pixel coordinates Effect Controls
// and the Properties panel display, given the sequence's frame size. Returns null when either
// input is unusable, never a wrong number.
function normalizedToFramePixels(value, frameWidth, frameHeight) {
  const point = pointXY(value);
  if (!point || !frameWidth || !frameHeight) return null;
  return { x: point.x * frameWidth, y: point.y * frameHeight };
}

module.exports = { pointXY, normalizedToFramePixels };
