// transform/geometry.js — PURE rect/point math for the Transform & Align panel. No
// require("premierepro"), so it is unit-testable off-host (plan Part 2's file layout,
// docs/research/cutdeck-transform-panel-plan.md).
//
// Two pixel spaces (Part 1a, proven live against Effect Controls): Position is normalized to the
// SEQUENCE frame, Anchor Point to the clip's SOURCE frame. Pass the right frame for the param;
// they only coincide when the source matches the sequence.
//
// The render model below (Phases 3 and 5) is geometry reasoning, NOT an Adobe formula — it is
// the hypothesis the live gates test:
//
//   seqPoint = Position + R(rotation) · (Scale ⊙ (srcPoint − Anchor))
//
// with Position in sequence pixels, Anchor and srcPoint in source pixels, Scale as fractions
// (100% = 1) and rotation in degrees, positive = clockwise on screen (y grows downward). It
// assumes square pixels on both sides; callers refuse anything else.

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
// and the Properties panel display, given the frame that param is normalized to (sequence for
// Position, source for Anchor Point). Returns null when either
// input is unusable, never a wrong number.
function normalizedToFramePixels(value, frameWidth, frameHeight) {
  const point = pointXY(value);
  if (!point || !frameWidth || !frameHeight) return null;
  return { x: point.x * frameWidth, y: point.y * frameHeight };
}

// The inverse, for writing: pixels in `frame` back to the normalized value Premiere stores.
function framePixelsToNormalized(point, frameWidth, frameHeight) {
  if (!point || !frameWidth || !frameHeight) return null;
  return { x: point.x / frameWidth, y: point.y / frameHeight };
}

// The part of the source that is still visible after Motion's Crop (percent of each side), in
// source pixels.
function visibleSourceRect(source, crop) {
  const c = crop || {};
  const pct = (v) => (typeof v === "number" ? v / 100 : 0);
  return {
    left: pct(c.left) * source.width,
    top: pct(c.top) * source.height,
    right: (1 - pct(c.right)) * source.width,
    bottom: (1 - pct(c.bottom)) * source.height,
  };
}

// The nine-point anchor picker's targets, as fractions of the visible rect.
const ANCHOR_TARGETS = {
  "top-left": [0, 0], top: [0.5, 0], "top-right": [1, 0],
  left: [0, 0.5], center: [0.5, 0.5], right: [1, 0.5],
  "bottom-left": [0, 1], bottom: [0.5, 1], "bottom-right": [1, 1],
};

function anchorTargetPoint(rect, name) {
  const t = ANCHOR_TARGETS[name];
  if (!t) return null;
  return { x: rect.left + t[0] * (rect.right - rect.left), y: rect.top + t[1] * (rect.bottom - rect.top) };
}

// R(rotation) · (Scale ⊙ v): a source-pixel offset turned into a sequence-pixel offset.
function sourceOffsetToSequence(v, clip) {
  const sx = v.x * clip.scaleX;
  const sy = v.y * clip.scaleY;
  const rad = (clip.rotation * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  return { x: sx * cos - sy * sin, y: sx * sin + sy * cos };
}

// `clip` = { position: {x,y} seq px, anchor: {x,y} source px, scaleX, scaleY (fractions),
// rotation (degrees) }. Where a source pixel lands in the sequence frame.
function sourceToSequence(point, clip) {
  const d = sourceOffsetToSequence({ x: point.x - clip.anchor.x, y: point.y - clip.anchor.y }, clip);
  return { x: clip.position.x + d.x, y: clip.position.y + d.y };
}

// The inverse: which source pixel is drawn at a sequence pixel. Needed to put the anchor on a
// point measured in the frame (a Graphic's drawn text box). Scale must be non-zero.
function sequenceToSource(point, clip) {
  const dx = point.x - clip.position.x;
  const dy = point.y - clip.position.y;
  const rad = (clip.rotation * Math.PI) / 180;
  const cos = Math.cos(rad);
  const sin = Math.sin(rad);
  // R(-rotation) undoes the turn, then undo the scale.
  const ux = dx * cos + dy * sin;
  const uy = -dx * sin + dy * cos;
  return { x: clip.anchor.x + ux / clip.scaleX, y: clip.anchor.y + uy / clip.scaleY };
}

// The Position that keeps the picture where it is when the anchor moves to `newAnchor`:
// P' = P + R·S·(A' − A). Both anchors in source pixels; the result in sequence pixels.
function positionForAnchorMove(clip, newAnchor) {
  const d = sourceOffsetToSequence({ x: newAnchor.x - clip.anchor.x, y: newAnchor.y - clip.anchor.y }, clip);
  return { x: clip.position.x + d.x, y: clip.position.y + d.y };
}

// Axis-aligned bounds, in sequence pixels, of the visible rect as rendered.
function renderedBounds(clip, rect) {
  const corners = [
    { x: rect.left, y: rect.top }, { x: rect.right, y: rect.top },
    { x: rect.left, y: rect.bottom }, { x: rect.right, y: rect.bottom },
  ].map((p) => sourceToSequence(p, clip));
  const xs = corners.map((p) => p.x);
  const ys = corners.map((p) => p.y);
  return { left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys) };
}

const ALIGN_EDGES = ["left", "hcenter", "right", "top", "vcenter", "bottom"];

function alignShift(bounds, frame, edge) {
  const zero = (v) => (Math.abs(v) < 1e-4 ? 0 : v);
  switch (edge) {
    case "left": return { dx: zero(-bounds.left), dy: 0 };
    case "hcenter": return { dx: zero(frame.width / 2 - (bounds.left + bounds.right) / 2), dy: 0 };
    case "right": return { dx: zero(frame.width - bounds.right), dy: 0 };
    case "top": return { dx: 0, dy: zero(-bounds.top) };
    case "vcenter": return { dx: 0, dy: zero(frame.height / 2 - (bounds.top + bounds.bottom) / 2) };
    case "bottom": return { dx: 0, dy: zero(frame.height - bounds.bottom) };
    default: return null;
  }
}

module.exports = {
  pointXY,
  normalizedToFramePixels,
  framePixelsToNormalized,
  visibleSourceRect,
  ANCHOR_TARGETS,
  anchorTargetPoint,
  sourceToSequence,
  sequenceToSource,
  positionForAnchorMove,
  renderedBounds,
  ALIGN_EDGES,
  alignShift,
};
