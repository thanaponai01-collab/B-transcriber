const test = require("node:test");
const assert = require("node:assert");
const box = require("../uxp/cutdeck/transform/cropBox.js");

const source = { width: 1920, height: 1080 };
const zero = { left: 0, top: 0, right: 0, bottom: 0 };
// Clip centred in a 1920x1080 sequence at 100%, no rotation: source px == sequence px.
const plain = { position: { x: 960, y: 540 }, anchor: { x: 960, y: 540 }, scaleX: 1, scaleY: 1, rotation: 0 };

test("dragging the left edge to x=192 crops 10% left", () => {
  assert.deepStrictEqual(box.dragCrop("left", { x: 192, y: 300 }, plain, source, zero), { ...zero, left: 10 });
});

test("corner drag sets two sides", () => {
  const c = box.dragCrop("bottom-right", { x: 1728, y: 972 }, plain, source, zero);
  assert.deepStrictEqual(c, { left: 0, top: 0, right: 10, bottom: 10 });
});

test("an edge can't cross the opposite edge", () => {
  const c = box.dragCrop("left", { x: 1900, y: 0 }, plain, source, { ...zero, right: 50 });
  assert.strictEqual(c.left, 50 - box.MIN_VISIBLE_PCT);
});

test("at 50% scale the pointer still lands on the edge", () => {
  const half = { ...plain, scaleX: 0.5, scaleY: 0.5 };
  // Picture spans 480..1440; 10% in from the left is 480 + 96.
  assert.strictEqual(box.dragCrop("left", { x: 576, y: 540 }, half, source, zero).left, 10);
});

test("rotated 90°: dragging toward screen-right moves the source top edge", () => {
  const rot = { ...plain, rotation: 90 };
  // Clockwise 90°: source top lands on screen right. Pointer 108 px in from that side → top 10%.
  const c = box.dragCrop("top", { x: 960 + 540 - 108, y: 540 }, rot, source, zero);
  assert.strictEqual(c.top, 10);
});

test("moving the box keeps its size and stays inside the source", () => {
  const crop = { left: 10, top: 10, right: 10, bottom: 10 };
  assert.deepStrictEqual(box.moveCrop({ x: 0, y: 0 }, { x: 192, y: 0 }, plain, source, crop),
    { left: 20, top: 10, right: 0, bottom: 10 });
  assert.deepStrictEqual(box.moveCrop({ x: 0, y: 0 }, { x: 5000, y: 0 }, plain, source, crop),
    { left: 20, top: 10, right: 0, bottom: 10 });
});

test("preview <-> sequence round-trips", () => {
  const pv = { width: 320, height: 180 };
  const seq = { width: 1920, height: 1080 };
  assert.deepStrictEqual(box.previewToSequence({ x: 32, y: 18 }, pv, seq), { x: 192, y: 108 });
  assert.deepStrictEqual(box.sequenceToPreview({ x: 192, y: 108 }, pv, seq), { x: 32, y: 18 });
});

test("cropToMotionValues uses apply.js field names", () => {
  assert.deepStrictEqual(box.cropToMotionValues({ left: 1, top: 2, right: 3, bottom: 4 }),
    { cropLeft: 1, cropTop: 2, cropRight: 3, cropBottom: 4 });
});
