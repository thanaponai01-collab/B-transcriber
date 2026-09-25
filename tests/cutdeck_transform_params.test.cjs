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

// --- Anchor Point is normalized to the SOURCE frame, not the sequence frame -----------------
//
// Part 1a, second live run: a 1280x720 clip in a 1920x1080 sequence, Position and Anchor Point
// both set to 100,200 in Effect Controls. The raw values below are verbatim from that run.

test("live 720p-in-1080p run: Position converts against the sequence, Anchor Point against the source", () => {
  const pos = geometry.normalizedToFramePixels([0.0520833320915699, 0.18518517911434174], 1920, 1080);
  assert.ok(Math.abs(pos.x - 100) < 0.01 && Math.abs(pos.y - 200) < 0.01);
  const anchor = geometry.normalizedToFramePixels([0.078125, 0.2777777910232544], 1280, 720);
  assert.ok(Math.abs(anchor.x - 100) < 0.01 && Math.abs(anchor.y - 200) < 0.01);
  // The bug this pins: converting Anchor Point against the sequence frame gives 150, 300.
  const wrong = geometry.normalizedToFramePixels([0.078125, 0.2777777910232544], 1920, 1080);
  assert.ok(Math.abs(wrong.x - 150) < 0.01);
});

test("live non-square run: a 2.0-PAR 1280x720 source still stores Anchor Point against 1280x720", () => {
  // Same clip, Interpret Footage -> Anamorphic 2:1, Video Info "1280 x 720 (2.0)", anchor set
  // to 100,200 in Effect Controls: the raw value was unchanged, so PAR is not applied.
  const size = params.parseVideoInfoSize("1280 x 720 (2.0)");
  const anchor = geometry.normalizedToFramePixels([0.078125, 0.2777777910232544], size.width, size.height);
  assert.ok(Math.abs(anchor.x - 100) < 0.01 && Math.abs(anchor.y - 200) < 0.01);
});

test("parseVideoInfoSize reads the Video Info strings the live runs returned", () => {
  assert.deepEqual(params.parseVideoInfoSize("1280 x 720 (1.0)"), { width: 1280, height: 720, pixelAspect: 1 });
  assert.deepEqual(params.parseVideoInfoSize("3840 x 2160 (1.0)"), { width: 3840, height: 2160, pixelAspect: 1 });
  // A PNG carries trailing text after the (par) group.
  assert.deepEqual(params.parseVideoInfoSize("1920 x 1080 (1.0), Straight Alpha"), { width: 1920, height: 1080, pixelAspect: 1 });
});

test("parseVideoInfoSize keeps a non-square aspect and reports a missing one as null, never 1", () => {
  assert.deepEqual(params.parseVideoInfoSize("1440 x 1080 (1.333)"), { width: 1440, height: 1080, pixelAspect: 1.333 });
  assert.deepEqual(params.parseVideoInfoSize("1280 x 720"), { width: 1280, height: 720, pixelAspect: null });
});

test("parseVideoInfoSize returns null for text without a size", () => {
  assert.equal(params.parseVideoInfoSize(""), null);
  assert.equal(params.parseVideoInfoSize(null), null);
  assert.equal(params.parseVideoInfoSize("Straight Alpha"), null);
  assert.equal(params.parseVideoInfoSize("0 x 720 (1.0)"), null);
});

function fakeColumnsHost(columnsJson) {
  return {
    Metadata: { getProjectColumnsMetadata: () => Promise.resolve(columnsJson) },
  };
}
const itemWithProjectItem = { getProjectItem: () => Promise.resolve({ name: "clip" }) };

test("readSourceFrameSize finds the Video Info column by ColumnID", async () => {
  const json = JSON.stringify([
    { ColumnID: "Column.Intrinsic.Name", ColumnName: "Name", ColumnValue: "clip 1920 x 1080.mp4" },
    { ColumnID: "Column.Intrinsic.VideoInfo", ColumnName: "Video Info", ColumnValue: "1280 x 720 (1.0)" },
  ]);
  assert.deepEqual(await params.readSourceFrameSize(fakeColumnsHost(json), itemWithProjectItem),
    { width: 1280, height: 720, pixelAspect: 1 });
});

test("readSourceFrameSize returns null, never throws, when the source size cannot be read", async () => {
  const noVideoInfo = JSON.stringify([{ ColumnID: "Column.Intrinsic.Name", ColumnValue: "x" }]);
  assert.equal(await params.readSourceFrameSize(fakeColumnsHost(noVideoInfo), itemWithProjectItem), null);
  assert.equal(await params.readSourceFrameSize(fakeColumnsHost("not json"), itemWithProjectItem), null);
  assert.equal(await params.readSourceFrameSize({}, itemWithProjectItem), null);
  assert.equal(await params.readSourceFrameSize(fakeColumnsHost("[]"), {}), null);
  const rejecting = { Metadata: { getProjectColumnsMetadata: () => Promise.reject(new Error("boom")) } };
  assert.equal(await params.readSourceFrameSize(rejecting, itemWithProjectItem), null);
});

// --- readAnchorFrameSize: the frame Anchor Point is normalized to --------------------------------

test("readAnchorFrameSize uses the source frame, falls back to the sequence frame only for a Graphic, else null", async () => {
  const seq = { getSettings: () => Promise.resolve({ getVideoFrameRect: () => Promise.resolve({ width: 1920, height: 1080 }) }) };
  const ppro = { Metadata: { getProjectColumnsMetadata: () => Promise.resolve(JSON.stringify([
    { ColumnID: "Column.Intrinsic.VideoInfo", ColumnValue: "1280 x 720 (1.0)" }])) } };

  const footage = Object.assign(itemWithComponents([motionComponent()]), { getProjectItem: () => Promise.resolve({}) });
  assert.deepEqual(await params.readAnchorFrameSize(ppro, footage, seq), { width: 1280, height: 720, pixelAspect: 1 });

  // Check Transform on a Graphic (2026-09-24): no project item; Opacity, Motion, Vector Motion, Text.
  const graphic = Object.assign(itemWithComponents([
    component("Opacity", "AE.ADBE Opacity", []), motionComponent(),
    component("Vector Motion", "AE.ADBE Graphic Group", []), component("Text", "AE.ADBE Text", []),
  ]), { getProjectItem: () => Promise.resolve(null) });
  assert.deepEqual(await params.readAnchorFrameSize(ppro, graphic, seq), { width: 1920, height: 1080, pixelAspect: 1 });

  const unknown = Object.assign(itemWithComponents([motionComponent()]), { getProjectItem: () => Promise.resolve(null) });
  assert.equal(await params.readAnchorFrameSize(ppro, unknown, seq), null);
});
