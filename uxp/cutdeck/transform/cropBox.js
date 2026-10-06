// transform/cropBox.js — PURE geometry for the Crop Box (docs/research/cutdeck-crop-box-plan.md).
// No premierepro, no DOM. Turns a drag on the panel's frame preview into Motion's Crop
// Left/Top/Right/Bottom (percent of the SOURCE frame, PREMIERE_FACTS "Motion param indices"
// 7-10), using the same clip model the Transform & Align panel already proved live
// (geometry.js: Position + R(rot)·Scale·(p − Anchor)).

const { visibleSourceRect, sequenceToSource, sourceToSequence } = require("./geometry.js");

// Smallest visible size a drag may leave, in percent of the source side.
const MIN_VISIBLE_PCT = 1;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const round3 = (v) => Math.round(v * 1000) / 1000;

// Preview pixels (the <img> showing the exported sequence frame) → sequence pixels.
function previewToSequence(point, preview, seqFrame) {
  return { x: (point.x / preview.width) * seqFrame.width, y: (point.y / preview.height) * seqFrame.height };
}

function sequenceToPreview(point, preview, seqFrame) {
  return { x: (point.x / seqFrame.width) * preview.width, y: (point.y / seqFrame.height) * preview.height };
}

// The four corners of the uncropped source and of the visible (cropped) rect, in sequence
// pixels, for drawing the outline and the box. Corners, not bounds: a rotated clip is a
// rotated quad.
function cropQuads(clip, source, crop) {
  const quad = (r) => [
    { x: r.left, y: r.top }, { x: r.right, y: r.top },
    { x: r.right, y: r.bottom }, { x: r.left, y: r.bottom },
  ].map((p) => sourceToSequence(p, clip));
  return {
    full: quad({ left: 0, top: 0, right: source.width, bottom: source.height }),
    visible: quad(visibleSourceRect(source, crop)),
  };
}

// A drag of `handle` ("left" | "top" | "right" | "bottom" | "top-left" | … ) to `seqPoint`.
// The point is mapped back into source pixels, so the edge follows the pointer at any
// rotation and scale. Returns the new crop (percent), clamped so the opposite edge is never
// crossed and at least MIN_VISIBLE_PCT stays visible.
function dragCrop(handle, seqPoint, clip, source, crop) {
  const p = sequenceToSource(seqPoint, clip);
  const xPct = (p.x / source.width) * 100;
  const yPct = (p.y / source.height) * 100;
  const next = { ...crop };
  if (handle.includes("left")) next.left = clamp(xPct, 0, 100 - next.right - MIN_VISIBLE_PCT);
  if (handle.includes("right")) next.right = clamp(100 - xPct, 0, 100 - next.left - MIN_VISIBLE_PCT);
  if (handle.includes("top")) next.top = clamp(yPct, 0, 100 - next.bottom - MIN_VISIBLE_PCT);
  if (handle.includes("bottom")) next.bottom = clamp(100 - yPct, 0, 100 - next.top - MIN_VISIBLE_PCT);
  for (const k of ["left", "top", "right", "bottom"]) next[k] = round3(next[k]);
  return next;
}

// Moving the whole box (drag inside it) by a sequence-pixel delta: keeps its size, slides it
// within the source.
function moveCrop(fromSeq, toSeq, clip, source, crop) {
  const a = sequenceToSource(fromSeq, clip);
  const b = sequenceToSource(toSeq, clip);
  const w = 100 - crop.left - crop.right;
  const h = 100 - crop.top - crop.bottom;
  const left = clamp(crop.left + ((b.x - a.x) / source.width) * 100, 0, 100 - w);
  const top = clamp(crop.top + ((b.y - a.y) / source.height) * 100, 0, 100 - h);
  return { left: round3(left), top: round3(top), right: round3(100 - w - left), bottom: round3(100 - h - top) };
}

// Motion field names apply.js writes (PARAM_INDEX cropLeft…cropBottom).
function cropToMotionValues(crop) {
  return { cropLeft: crop.left, cropTop: crop.top, cropRight: crop.right, cropBottom: crop.bottom };
}

module.exports = {
  MIN_VISIBLE_PCT,
  previewToSequence,
  sequenceToPreview,
  cropQuads,
  dragCrop,
  moveCrop,
  cropToMotionValues,
};
