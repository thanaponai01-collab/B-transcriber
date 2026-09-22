/* transform/params.js and transform/geometry.js — Phase 1 of
   docs/research/cutdeck-transform-panel-plan.md ("Read-only display of the selected clip's
   position/scale/rotation/anchor, live"). params.js is host discovery only (talks to a fake
   premierepro host, never throws); geometry.js is pure math (no host at all). The param index
   map here (0 Position, 1 Scale, 3 Uniform Scale, 4 Rotation, 5 Anchor Point) is the one Part
   1a's live Premiere run proved for this build (26.5.1) — see the plan doc for the sub-pixel
   cross-check against Effect Controls' own readout. */
const test = require("node:test");
const assert = require("node:assert/strict");

const params = require("../uxp/cutdeck/transform/params.js");
const geometry = require("../uxp/cutdeck/transform/geometry.js");

// --- fake host, mirroring cutdeck_transform_probe.test.cjs's shapes ------------------------

function param(name, inner, opts = {}) {
  return {
    displayName: name,
    isTimeVarying: () => Promise.resolve(opts.timeVarying === undefined ? false : opts.timeVarying),
    getStartValue: opts.throws
      ? () => Promise.reject(new Error(opts.throws))
      : () => Promise.resolve({ value: { value: inner } }),
  };
}

function component(displayName, matchName, paramList) {
  return {
    getDisplayName: () => Promise.resolve(displayName),
    getMatchName: () => Promise.resolve(matchName),
    getParamCount: () => paramList.length,
    getParam: (i) => paramList[i] || null,
  };
}

// Real Motion param order, PROVEN on the installed build (Part 1a): Position, Scale, Scale
// Width, Uniform Scale, Rotation, Anchor Point.
function motionComponent(overrides = {}) {
  const p = Object.assign({
    position: [0.5, 0.5],
    scale: 100,
    scaleWidth: 100,
    uniformScale: true,
    rotation: 0,
    anchorPoint: [0.5, 0.5],
  }, overrides);
  return component("Motion", "AE.ADBE Motion", [
    param("Position", p.position, overrides.positionOpts),
    param("Scale", p.scale, overrides.scaleOpts),
    param("Scale Width", p.scaleWidth),
    param("", p.uniformScale),
    param("Rotation", p.rotation, overrides.rotationOpts),
    param("Anchor Point", p.anchorPoint, overrides.anchorOpts),
  ]);
}

function itemWithComponents(componentList) {
  return {
    name: "clip A",
    getComponentChain: () => Promise.resolve({
      getComponentCount: () => componentList.length,
      getComponentAtIndex: (i) => componentList[i] || null,
    }),
  };
}

// --- findMotionComponent / readTransform ----------------------------------------------------

test("findMotionComponent matches by matchName, not displayName", async () => {
  const motion = motionComponent();
  const item = itemWithComponents([component("Opacity", "AE.ADBE Opacity", []), motion]);
  const found = await params.findMotionComponent(item);
  assert.equal(found, motion);
});

test("findMotionComponent returns null, never throws, when there is no chain or no Motion", async () => {
  assert.equal(await params.findMotionComponent(null), null);
  assert.equal(await params.findMotionComponent({}), null);
  assert.equal(await params.findMotionComponent({ getComponentChain: () => Promise.resolve(null) }), null);
  const item = itemWithComponents([component("Opacity", "AE.ADBE Opacity", [])]);
  assert.equal(await params.findMotionComponent(item), null);
});

test("readTransform returns null for an item with no readable Motion component — the panel's 'unavailable' case", async () => {
  const item = itemWithComponents([component("Opacity", "AE.ADBE Opacity", [])]);
  assert.equal(await params.readTransform(item), null);
});

test("readTransform reads Position/Scale/Rotation/Anchor Point by the PROVEN indices", async () => {
  const item = itemWithComponents([motionComponent({
    position: [0.5, 0.5], scale: 162, rotation: 0, anchorPoint: [0.5, 0.5],
  })]);
  const t = await params.readTransform(item);
  assert.deepEqual(t.position, { isTimeVarying: false, value: [0.5, 0.5] });
  assert.deepEqual(t.scale, { isTimeVarying: false, value: 162 });
  assert.deepEqual(t.rotation, { isTimeVarying: false, value: 0 });
  assert.deepEqual(t.anchorPoint, { isTimeVarying: false, value: [0.5, 0.5] });
});

test("readTransform reports isTimeVarying per field, independently", async () => {
  const item = itemWithComponents([motionComponent({ positionOpts: { timeVarying: true } })]);
  const t = await params.readTransform(item);
  assert.equal(t.position.isTimeVarying, true);
  assert.equal(t.scale.isTimeVarying, false);
});

test("readTransform survives one param throwing without losing the other three", async () => {
  const item = itemWithComponents([motionComponent({ positionOpts: { throws: "value unavailable" } })]);
  const t = await params.readTransform(item);
  assert.equal(t.position.value, null);
  assert.equal(t.scale.value, 100);
  assert.equal(t.rotation.value, 0);
  assert.deepEqual(t.anchorPoint.value, [0.5, 0.5]);
});

test("readSequenceFrameSize reads SequenceSettings.getVideoFrameRect(), falling back to Sequence.getFrameSize()", async () => {
  const withSettings = { getSettings: () => Promise.resolve({ getVideoFrameRect: () => Promise.resolve({ width: 1920, height: 1080 }) }) };
  assert.deepEqual(await params.readSequenceFrameSize(withSettings), { width: 1920, height: 1080 });

  const noSettings = { getFrameSize: () => Promise.resolve({ width: 1280, height: 720 }) };
  assert.deepEqual(await params.readSequenceFrameSize(noSettings), { width: 1280, height: 720 });

  assert.equal(await params.readSequenceFrameSize(null), null);
  assert.equal(await params.readSequenceFrameSize({}), null);
});

// --- geometry.js: pure, no host -------------------------------------------------------------

test("normalizedToFramePixels reproduces Part 1a's live cross-check against Effect Controls", () => {
  // Clip B, repositioned/scaled PNG: Position=[-0.26602596044540405, 0.04159132018685341] on a
  // 1920x1080 sequence -> Properties panel showed "Position -510.8, 44.9".
  const px = geometry.normalizedToFramePixels([-0.26602596044540405, 0.04159132018685341], 1920, 1080);
  assert.equal(Math.round(px.x * 10) / 10, -510.8);
  assert.equal(Math.round(px.y * 10) / 10, 44.9);
});

test("normalizedToFramePixels accepts both the array and {x,y} point shapes", () => {
  assert.deepEqual(geometry.normalizedToFramePixels([0.5, 0.5], 1920, 1080), { x: 960, y: 540 });
  assert.deepEqual(geometry.normalizedToFramePixels({ x: 0.5, y: 0.5 }, 1920, 1080), { x: 960, y: 540 });
});

test("normalizedToFramePixels returns null instead of a wrong number for bad input", () => {
  assert.equal(geometry.normalizedToFramePixels(null, 1920, 1080), null);
  assert.equal(geometry.normalizedToFramePixels([0.5, 0.5], 0, 1080), null);
  assert.equal(geometry.normalizedToFramePixels([0.5, 0.5], null, null), null);
  assert.equal(geometry.normalizedToFramePixels("not a point", 1920, 1080), null);
  assert.equal(geometry.normalizedToFramePixels([0.5], 1920, 1080), null);
});
