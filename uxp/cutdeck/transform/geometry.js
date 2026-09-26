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

const zeroNear = (v) => (Math.abs(v) < 1e-4 ? 0 : v);

// The shift that puts `bounds` on an edge or centre of `box` ({left, top, right, bottom}): the
// sequence frame for Align to Frame, the selection's outer box for Align to Selection.
function alignShiftTo(bounds, box, edge) {
  switch (edge) {
    case "left": return { dx: zeroNear(box.left - bounds.left), dy: 0 };
    case "hcenter": return { dx: zeroNear((box.left + box.right) / 2 - (bounds.left + bounds.right) / 2), dy: 0 };
    case "right": return { dx: zeroNear(box.right - bounds.right), dy: 0 };
    case "top": return { dx: 0, dy: zeroNear(box.top - bounds.top) };
    case "vcenter": return { dx: 0, dy: zeroNear((box.top + box.bottom) / 2 - (bounds.top + bounds.bottom) / 2) };
    case "bottom": return { dx: 0, dy: zeroNear(box.bottom - bounds.bottom) };
    default: return null;
  }
}

function alignShift(bounds, frame, edge) {
  return alignShiftTo(bounds, { left: 0, top: 0, right: frame.width, bottom: frame.height }, edge);
}

// The smallest box holding every box in `list`.
function unionBounds(list) {
  return {
    left: Math.min(...list.map((b) => b.left)),
    top: Math.min(...list.map((b) => b.top)),
    right: Math.max(...list.map((b) => b.right)),
    bottom: Math.max(...list.map((b) => b.bottom)),
  };
}

// Distribute along `axis` ("x" | "y"): the outermost two (by centre) stay put and the rest move
// between them, either with equal spacing between CENTRES or equal GAPS between edges (a gap
// goes negative when the clips overlap). Returns the shift for each box, in input order.
function distributeShifts(list, axis, mode) {
  const [lo, hi] = axis === "x" ? ["left", "right"] : ["top", "bottom"];
  const centre = (b) => (b[lo] + b[hi]) / 2;
  const order = list.map((_, i) => i).sort((a, b) => centre(list[a]) - centre(list[b]));
  const shifts = list.map(() => 0);
  const n = order.length;
  if (mode === "centers") {
    const first = centre(list[order[0]]);
    const step = (centre(list[order[n - 1]]) - first) / (n - 1);
    order.forEach((idx, k) => { shifts[idx] = zeroNear(first + k * step - centre(list[idx])); });
  } else {
    const total = order.reduce((sum, idx) => sum + (list[idx][hi] - list[idx][lo]), 0);
    const gap = (list[order[n - 1]][hi] - list[order[0]][lo] - total) / (n - 1);
    let edge = list[order[0]][lo];
    order.forEach((idx) => {
      shifts[idx] = zeroNear(edge - list[idx][lo]);
      edge += list[idx][hi] - list[idx][lo] + gap;
    });
  }
  return shifts;
}

// Distribute across the sequence frame along `axis` ("x" | "y"):
// - "centers": centers are spaced evenly across the frame at (k + 1) * frameDim / (n + 1).
// - "gaps": equal margin on outer edges and equal gaps between elements: gap = (frameDim - totalDim) / (n + 1).
function distributeFrameShifts(list, frame, axis, mode) {
  const [lo, hi] = axis === "x" ? ["left", "right"] : ["top", "bottom"];
  const frameDim = axis === "x" ? frame.width : frame.height;
  const centre = (b) => (b[lo] + b[hi]) / 2;
  const order = list.map((_, i) => i).sort((a, b) => centre(list[a]) - centre(list[b]));
  const shifts = list.map(() => 0);
  const n = order.length;
  if (n === 0) return shifts;

  if (mode === "centers") {
    const step = frameDim / (n + 1);
    order.forEach((idx, k) => {
      const targetCenter = (k + 1) * step;
      shifts[idx] = zeroNear(targetCenter - centre(list[idx]));
    });
  } else {
    const totalDim = order.reduce((sum, idx) => sum + (list[idx][hi] - list[idx][lo]), 0);
    const gap = (frameDim - totalDim) / (n + 1);
    let edge = gap;
    order.forEach((idx) => {
      shifts[idx] = zeroNear(edge - list[idx][lo]);
      edge += (list[idx][hi] - list[idx][lo]) + gap;
    });
  }
  return shifts;
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
  alignShiftTo,
  unionBounds,
  distributeShifts,
  distributeFrameShifts,
};
