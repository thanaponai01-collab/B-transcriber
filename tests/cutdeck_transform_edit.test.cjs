/* Phases 2–5 of docs/research/cutdeck-transform-panel-plan.md: typed field edits, the nine-point
   anchor (Position compensated so the picture stays put) and align to the sequence frame.

   Proven here: the geometry is self-consistent (moving the anchor moves no source pixel; aligned
   bounds land on the frame edge), and the writes go through Premiere's proven rules (built on
   tests/fakes/premiere.cjs: Actions made inside the transaction, point values as PointF, one
   undo step). NOT provable here, and still gated on a live run: that Motion accepts
   createSetValueAction at all (gate 2), that Premiere renders by the same model (rotation sign,
   crop), and that the written values match Effect Controls. */
const test = require("node:test");
const assert = require("node:assert/strict");

const fake = require("./fakes/premiere.cjs");
const geometry = require("../uxp/cutdeck/transform/geometry.js");
const { applyMotionValues } = require("../uxp/cutdeck/transform/apply.js");
const { setAnchor, alignToFrame, setField, readAlignTransform } = require("../uxp/cutdeck/features/align.js");

const close = (a, b, msg) => assert.ok(Math.abs(a - b) < 1e-6, `${msg}: ${a} vs ${b}`);

// --- geometry (pure) ---------------------------------------------------------------------------

const clip = (o = {}) => Object.assign({
  position: { x: 960, y: 540 }, anchor: { x: 640, y: 360 }, scaleX: 1, scaleY: 1, rotation: 0,
}, o);

test("moving the anchor with the compensated Position moves no source pixel", () => {
  const cases = [clip(), clip({ scaleX: 1.5, scaleY: 0.7, rotation: 33 }), clip({ rotation: -90, position: { x: 100, y: -40 } })];
  const source = { width: 1280, height: 720 };
  const rect = geometry.visibleSourceRect(source, { left: 10, top: 0, right: 5, bottom: 20 });
  for (const c of cases) {
    for (const target of Object.keys(geometry.ANCHOR_TARGETS)) {
      const newAnchor = geometry.anchorTargetPoint(rect, target);
      const moved = Object.assign({}, c, { anchor: newAnchor, position: geometry.positionForAnchorMove(c, newAnchor) });
      for (const p of [{ x: 0, y: 0 }, { x: 1280, y: 720 }, { x: 77, y: 500 }]) {
        const before = geometry.sourceToSequence(p, c);
        const after = geometry.sourceToSequence(p, moved);
        close(after.x, before.x, `${target} x`);
        close(after.y, before.y, `${target} y`);
      }
    }
  }
});

test("anchor top-left of an unscaled 1280x720 clip centred in 1080p puts Position on its corner", () => {
  const rect = geometry.visibleSourceRect({ width: 1280, height: 720 }, {});
  const a = geometry.anchorTargetPoint(rect, "top-left");
  assert.deepEqual(a, { x: 0, y: 0 });
  assert.deepEqual(geometry.positionForAnchorMove(clip(), a), { x: 320, y: 180 });
});

test("anchor targets sit on the cropped picture, not the full source", () => {
  const rect = geometry.visibleSourceRect({ width: 1000, height: 500 }, { left: 10, top: 20, right: 30, bottom: 0 });
  assert.deepEqual(geometry.anchorTargetPoint(rect, "top-left"), { x: 100, y: 100 });
  assert.deepEqual(geometry.anchorTargetPoint(rect, "bottom-right"), { x: 700, y: 500 });
  assert.equal(geometry.anchorTargetPoint(rect, "nowhere"), null);
});

test("aligned bounds land on each frame edge and centre", () => {
  const frame = { width: 1920, height: 1080 };
  const source = { width: 1280, height: 720 };
  for (const c of [clip(), clip({ rotation: 30, scaleX: 0.5, scaleY: 0.5 }), clip({ position: { x: 0, y: 0 } })]) {
    const rect = geometry.visibleSourceRect(source, { right: 25 });
    for (const edge of geometry.ALIGN_EDGES) {
      const { dx, dy } = geometry.alignShift(geometry.renderedBounds(c, rect), frame, edge);
      const moved = Object.assign({}, c, { position: { x: c.position.x + dx, y: c.position.y + dy } });
      const b = geometry.renderedBounds(moved, rect);
      const want = {
        left: [b.left, 0], right: [b.right, 1920], hcenter: [(b.left + b.right) / 2, 960],
        top: [b.top, 0], bottom: [b.bottom, 1080], vcenter: [(b.top + b.bottom) / 2, 540],
      }[edge];
      close(want[0], want[1], edge);
    }
  }
});

test("positive rotation turns clockwise on screen (y down): right of the anchor lands below it", () => {
  // The render model's hypothesis for Premiere's sign; the live gate confirms or flips it.
  const c = clip({ anchor: { x: 0, y: 0 }, position: { x: 0, y: 0 } });
  const right = geometry.sourceToSequence({ x: 100, y: 0 }, Object.assign({}, c, { rotation: 90 }));
  const below = geometry.sourceToSequence({ x: 0, y: 100 }, Object.assign({}, c, { rotation: 90 }));
  close(right.x, 0, "right.x"); close(right.y, 100, "right.y");
  close(below.x, -100, "below.x"); close(below.y, 0, "below.y");
});

test("sequenceToSource undoes sourceToSequence, whatever the scale and rotation", () => {
  for (const c of [clip(), clip({ scaleX: 1.5, scaleY: 0.7, rotation: 33 }), clip({ rotation: -120, position: { x: 5, y: 900 } })]) {
    for (const p of [{ x: 0, y: 0 }, { x: 1280, y: 720 }, { x: 77, y: 500 }]) {
      const back = geometry.sequenceToSource(geometry.sourceToSequence(p, c), c);
      close(back.x, p.x, "x"); close(back.y, p.y, "y");
    }
  }
});

test("a 90° rotation swaps the rendered width and height", () => {
  const b = geometry.renderedBounds(clip({ rotation: 90 }), geometry.visibleSourceRect({ width: 1280, height: 720 }, {}));
  close(b.right - b.left, 720, "width");
  close(b.bottom - b.top, 1280, "height");
});

// --- fake Motion on the shared Premiere fake -----------------------------------------------------

// Real Motion order (PREMIERE_FACTS "Motion param indices"): 0 Position, 1 Scale, 2 Scale Width,
// 3 Uniform Scale, 4 Rotation, 5 Anchor Point, 6 Anti-flicker, 7–10 Crop L/T/R/B.
function motionParam(initial, { point = false, keyframed = false } = {}) {
  const p = {
    value: initial,
    isTimeVarying: () => Promise.resolve(keyframed),
    getStartValue: () => Promise.resolve({ value: { value: p.value } }),
    createKeyframe: (v) => ({ value: point ? fake.assertPointValue(v) : v }),
    createSetValueAction: (kf) => fake.action(() => {
      p.value = point ? [kf.value.x, kf.value.y] : kf.value;
    }),
  };
  return p;
}

function motionClip(name, o = {}) {
  // o.graphic: a Premiere Graphic, with Vector Motion in its chain and no project item (live 2026-09-24).
  const v = Object.assign({ position: [0.5, 0.5], scale: 100, scaleWidth: 100, uniform: true, rotation: 0,
    anchor: [0.5, 0.5], crop: [0, 0, 0, 0] }, o);
  const params = [
    motionParam(v.position, { point: true, keyframed: !!o.keyframedPosition }),
    motionParam(v.scale), motionParam(v.scaleWidth), motionParam(v.uniform), motionParam(v.rotation),
    motionParam(v.anchor, { point: true }), motionParam(false),
    ...v.crop.map((c) => motionParam(c)),
  ];
  const motion = { getMatchName: () => Promise.resolve("AE.ADBE Motion"), getParam: (i) => params[i] || null };
  // A Graphic's layers: Vector Motion (Motion's first six params) and one Text component per
  // o.texts entry, its Position at param [2] (Check Transform on a Graphic, 2026-09-24).
  const vmParams = [motionParam([0.5, 0.5], { point: true }), motionParam(o.vmScale || 100), motionParam(100),
    motionParam(true), motionParam(o.vmRotation || 0), motionParam([0.5, 0.5], { point: true })];
  const vm = { getMatchName: () => Promise.resolve("AE.ADBE Graphic Group"), getParam: (i) => vmParams[i] || null };
  const texts = (o.texts || []).map((pos, i) => {
    // Text layer Transform: [2] Position, [3] Scale, [4] Horizontal Scale, [5] Uniform,
    // [6] Rotation, [8] Anchor Point; all points as fractions of the canvas (live 2026-09-24).
    const tp = [null, null, motionParam(pos, { point: true, keyframed: !!o.keyframedText }),
      motionParam(100), motionParam(100), motionParam(true), motionParam(0), motionParam(0),
      motionParam((o.textAnchors || [])[i] || [0, 0], { point: true })];
    return { getMatchName: () => Promise.resolve("AE.ADBE Text"), getParam: (j) => tp[j] || null, position: tp[2], anchor: tp[8], scale: tp[3], rotation: tp[6] };
  });
  const extra = o.shapeLayer ? [{ getMatchName: () => Promise.resolve("AE.ADBE Shape") }] : [];
  const chain = o.graphic ? [motion, vm, ...texts, ...extra] : [motion];
  return {
    name,
    params,
    texts: texts.map((t) => t.position),
    textAnchors: texts.map((t) => t.anchor),
    textScales: texts.map((t) => t.scale),
    textRotations: texts.map((t) => t.rotation),
    source: o.source || "1280 x 720 (1.0)",
    getComponentChain: () => Promise.resolve({ getComponentCount: () => chain.length, getComponentAtIndex: (i) => chain[i] }),
    getProjectItem: () => Promise.resolve(o.graphic ? null : { clipName: name }),
  };
}

function host(items, { aspect = "1:1" } = {}) {
  const { project, undoSteps } = fake.createProject();
  const seq = {
    name: "Seq",
    getSelection: () => Promise.resolve({ getTrackItems: () => Promise.resolve(items) }),
    getSettings: () => Promise.resolve({
      getVideoFrameRect: () => Promise.resolve({ width: 1920, height: 1080 }),
      getVideoPixelAspectRatio: () => Promise.resolve(aspect),
    }),
  };
  project.getActiveSequence = () => Promise.resolve(seq);
  const byName = new Map(items.map((i) => [i.name, i]));
  const ppro = {
    PointF: fake.PointF,
    Project: { getActiveProject: () => Promise.resolve(project) },
    Metadata: {
      getProjectColumnsMetadata: (pi) => Promise.resolve(JSON.stringify([
        { ColumnID: "Column.Intrinsic.VideoInfo", ColumnValue: byName.get(pi.clipName).source },
      ])),
    },
  };
  return { ppro, undoSteps };
}

// --- apply ---------------------------------------------------------------------------------------

test("applyMotionValues writes points as PointF and numbers as-is, all in one undo step", async () => {
  const a = motionClip("A");
  const b = motionClip("B");
  const { ppro, undoSteps } = host([a, b]);
  const project = await ppro.Project.getActiveProject();
  await applyMotionValues(ppro, project, "CutDeck: test", [
    { item: a, name: "A", values: { position: { x: 0.25, y: 0.75 }, scale: 50 } },
    { item: b, name: "B", values: { rotation: 45 } },
  ]);
  assert.deepEqual(a.params[0].value, [0.25, 0.75]);
  assert.equal(a.params[1].value, 50);
  assert.equal(b.params[4].value, 45);
  assert.deepEqual(undoSteps, ["CutDeck: test"]);
});

test("applyMotionValues refuses before writing anything when a clip has no Motion", async () => {
  const a = motionClip("A");
  const { ppro, undoSteps } = host([a]);
  const project = await ppro.Project.getActiveProject();
  const noMotion = { getComponentChain: () => Promise.resolve({ getComponentCount: () => 0 }) };
  await assert.rejects(applyMotionValues(ppro, project, "x", [
    { item: a, name: "A", values: { scale: 10 } },
    { item: noMotion, name: "Audio", values: { scale: 10 } },
  ]), /no Motion/);
  assert.equal(a.params[1].value, 100);
  assert.deepEqual(undoSteps, []);
});

// --- the three edits, end to end -----------------------------------------------------------------

test("setAnchor top-left keeps the picture in place: Anchor → [0,0], Position → the old corner", async () => {
  const a = motionClip("A");
  const { ppro, undoSteps } = host([a]);
  const result = await setAnchor(ppro, "top-left");
  assert.deepEqual(result, { done: 1, skipped: [] });
  assert.deepEqual(a.params[5].value, [0, 0]);
  close(a.params[0].value[0], 320 / 1920, "position x");
  close(a.params[0].value[1], 180 / 1080, "position y");
  assert.deepEqual(undoSteps, ["CutDeck: Anchor top-left"]);
});

test("alignToFrame left moves a half-size centred clip to x = its half width", async () => {
  const a = motionClip("A", { scale: 50 });
  const { ppro } = host([a]);
  await alignToFrame(ppro, "left");
  close(a.params[0].value[0], 320 / 1920, "position x");
  close(a.params[0].value[1], 0.5, "position y untouched");
});

test("edits skip, with a reason, clips that are keyframed or have non-square pixels, and still do the rest", async () => {
  const ok = motionClip("ok");
  const animated = motionClip("anim", { keyframedPosition: true });
  const anamorphic = motionClip("ana", { source: "1440 x 1080 (1.333)" });
  const { ppro, undoSteps } = host([ok, animated, anamorphic]);
  const result = await alignToFrame(ppro, "top");
  assert.equal(result.done, 1);
  assert.equal(result.skipped.length, 2);
  assert.match(result.skipped[0], /"anim" has keyframed/);
  assert.match(result.skipped[1], /"ana": non-square/);
  assert.deepEqual(animated.params[0].value, [0.5, 0.5]);
  assert.equal(undoSteps.length, 1);
});

test("a non-square sequence is refused rather than guessed", async () => {
  const a = motionClip("A");
  const { ppro, undoSteps } = host([a], { aspect: "0.9:1" });
  const result = await setAnchor(ppro, "center");
  assert.equal(result.done, 0);
  assert.deepEqual(undoSteps, []);
});

test("setField writes one axis in pixels, keeping the other axis as it was", async () => {
  const a = motionClip("A", { position: [0.25, 0.5] });
  const { ppro } = host([a]);
  await setField(ppro, "position-y", "108");
  close(a.params[0].value[0], 0.25, "x kept");
  close(a.params[0].value[1], 0.1, "y set");
  await setField(ppro, "anchor-x", "0");
  assert.deepEqual(a.params[5].value, [0, 0.5]);
  await setField(ppro, "scale", " 80 ");
  assert.equal(a.params[1].value, 80);
});

test("setField refuses text that is not a number and skips a keyframed value", async () => {
  const a = motionClip("A", { keyframedPosition: true });
  const { ppro, undoSteps } = host([a]);
  await assert.rejects(setField(ppro, "scale", "abc"), /not a number/);
  const result = await setField(ppro, "position-x", "10");
  assert.equal(result.done, 0);
  assert.match(result.skipped[0], /"A" has this value keyframed/);
  assert.deepEqual(a.params[0].value, [0.5, 0.5]);
  assert.deepEqual(undoSteps, []);
});

test("setField sets every selected clip at once, each axis in its own frame, in one undo step", async () => {
  const a = motionClip("A", { position: [0.25, 0.5], anchor: [0.5, 0.5] });
  const b = motionClip("B", { position: [0.75, 0.1], anchor: [0.5, 0.25], source: "3840 x 2160 (1.0)" });
  const { ppro, undoSteps } = host([a, b]);
  await setField(ppro, "position-x", "960");
  close(a.params[0].value[0], 0.5, "A x"); close(a.params[0].value[1], 0.5, "A y kept");
  close(b.params[0].value[0], 0.5, "B x"); close(b.params[0].value[1], 0.1, "B y kept");
  await setField(ppro, "anchor-y", "0");
  assert.deepEqual(a.params[5].value, [0.5, 0]);
  assert.deepEqual(b.params[5].value, [0.5, 0]);
  await setField(ppro, "rotation", "15");
  assert.equal(a.params[4].value, 15);
  assert.equal(b.params[4].value, 15);
  assert.deepEqual(undoSteps, ["CutDeck: Set position-x", "CutDeck: Set anchor-y", "CutDeck: Set rotation"]);
});

// --- Graphics: Anchor and Align use the measured text box ----------------------------------------

// The live measurement: text drawn at x 11-429, y 904-991 in a default Graphic (Motion at
// 960,540, anchor 960,540 of its sequence-sized canvas).
const TEXT_BOX = { left: 11, top: 904, right: 429, bottom: 991 };
const px = (item) => ({ x: item.params[0].value[0] * 1920, y: item.params[0].value[1] * 1080 });

test("Align left on a Graphic moves its measured text box to x = 0", async () => {
  const g = motionClip("Graphic", { graphic: true });
  const { ppro } = host([g]);
  const measured = [];
  const result = await alignToFrame(ppro, "left", async ({ item }) => { measured.push(item.name); return TEXT_BOX; });
  assert.deepEqual(result, { done: 1, skipped: [] });
  assert.deepEqual(measured, ["Graphic"]);
  close(px(g).x, 960 - 11, "position x moved left by 11");
  close(px(g).y, 540, "position y untouched");
});

test("Align centre and bottom on a Graphic use the text box, not the canvas", async () => {
  const g = motionClip("Graphic", { graphic: true });
  const { ppro } = host([g]);
  await alignToFrame(ppro, "hcenter", async () => TEXT_BOX);
  close(px(g).x, 960 + (960 - 220), "centre of 11..429 is 220");
  await alignToFrame(ppro, "bottom", async () => TEXT_BOX);
  close(px(g).y, 540 + (1080 - 991), "bottom edge to 1080");
});

test("Anchor top-left on a Graphic lands on its text box corner, and the text stays put", async () => {
  const g = motionClip("Graphic", { graphic: true });
  const { ppro } = host([g]);
  await setAnchor(ppro, "top-left", async () => TEXT_BOX);
  // Default Graphic: canvas = sequence frame, unscaled, so the corner is (11, 904) in both spaces.
  close(g.params[5].value[0] * 1920, 11, "anchor x");
  close(g.params[5].value[1] * 1080, 904, "anchor y");
  close(px(g).x, 11, "position x");
  close(px(g).y, 904, "position y");
});

test("a Graphic is skipped with a reason when it cannot be measured; other clips still move", async () => {
  const g = motionClip("Graphic", { graphic: true });
  const v = motionClip("Video");
  const { ppro } = host([g, v]);
  const result = await alignToFrame(ppro, "top", async () => { throw new Error("Move the playhead over it first."); });
  assert.equal(result.done, 1);
  assert.deepEqual(result.skipped, ['"Graphic": Move the playhead over it first.']);
  const nothing = await alignToFrame(ppro, "top", async () => null);
  assert.match(nothing.skipped[0], /draws nothing at the playhead/);
  const noHelper = await alignToFrame(ppro, "top");
  assert.match(noHelper.skipped[0], /needs its text measured/);
});

// --- Graphics with text layers: Align moves the text's own Position -----------------------------

// The live Graphic: its text layer at Position 0, 975 (Properties panel), drawn at x 11-429.
const TEXT_AT = [0, 975 / 1080];
const textPx = (t) => ({ x: t.value[0] * 1920, y: t.value[1] * 1080 });

test("Align left on a text Graphic moves the text layer's own Position, not the Graphic's Motion", async () => {
  const g = motionClip("Graphic", { graphic: true, texts: [TEXT_AT] });
  const { ppro, undoSteps } = host([g]);
  const result = await alignToFrame(ppro, "left", async () => TEXT_BOX);
  assert.deepEqual(result, { done: 1, skipped: [] });
  close(textPx(g.texts[0]).x, -11, "text x: the drawn left edge 11 moves to 0");
  close(textPx(g.texts[0]).y, 975, "text y untouched");
  assert.deepEqual(g.params[0].value, [0.5, 0.5], "Motion Position untouched");
  assert.deepEqual(undoSteps, ["CutDeck: Align left"]);
});

test("every text layer in the Graphic moves together", async () => {
  const g = motionClip("Graphic", { graphic: true, texts: [TEXT_AT, [0.25, 0.5]] });
  const { ppro } = host([g]);
  await alignToFrame(ppro, "top", async () => TEXT_BOX);
  close(textPx(g.texts[0]).y, 975 - 904, "first layer up by 904");
  close(textPx(g.texts[1]).y, 540 - 904, "second layer up by 904");
});

test("the shift is undone through Motion and Vector Motion scale", async () => {
  // Motion at 50% and Vector Motion at 200%: a 11 px shift on screen is 11 px in the text layer.
  const g = motionClip("Graphic", { graphic: true, texts: [TEXT_AT], scale: 50, vmScale: 200 });
  const { ppro } = host([g]);
  await alignToFrame(ppro, "left", async () => TEXT_BOX);
  close(textPx(g.texts[0]).x, -11, "x");
  const h = motionClip("Graphic", { graphic: true, texts: [TEXT_AT], scale: 50 });
  const second = host([h]);
  await alignToFrame(second.ppro, "left", async () => TEXT_BOX);
  close(textPx(h.texts[0]).x, -22, "Motion at 50% alone: 11 px on screen is 22 px in the layer");
});

test("a shape layer or a keyframed text Position moves the whole Graphic instead, leaving nothing behind", async () => {
  for (const extra of [{ shapeLayer: true }, { keyframedText: true }]) {
    const g = motionClip("Graphic", Object.assign({ graphic: true, texts: [TEXT_AT] }, extra));
    const { ppro } = host([g]);
    await alignToFrame(ppro, "left", async () => TEXT_BOX);
    assert.deepEqual(g.texts[0].value, TEXT_AT, "text layer untouched");
    close(g.params[0].value[0] * 1920, 960 - 11, "Motion moved instead");
  }
});

// --- Graphics with text layers: Anchor sets the text's own Anchor Point --------------------------

// Live 2026-09-24: text Position 215.1, 939.6 and Anchor Point 215.1, -35.4 (Properties panel),
// stored as [0.1120, 0.8700] and [0.1120, -0.0327]; text drawn at x 11-429, y 904-991.
const LIVE_TEXT = { texts: [[215.1 / 1920, 939.6 / 1080]], textAnchors: [[215.1 / 1920, -35.4 / 1080]] };
const pt = (param) => ({ x: param.value[0] * 1920, y: param.value[1] * 1080 });

test("Anchor top-left on a text Graphic sets the text's own Anchor Point, and the text stays put", async () => {
  const g = motionClip("Graphic", Object.assign({ graphic: true }, LIVE_TEXT));
  const { ppro, undoSteps } = host([g]);
  const result = await setAnchor(ppro, "top-left", async () => TEXT_BOX);
  assert.deepEqual(result, { done: 1, skipped: [] });
  // The box corner (11, 904) is 204.1 left of and 35.6 above the old anchor point.
  close(pt(g.textAnchors[0]).x, 11, "text anchor x"); close(pt(g.textAnchors[0]).y, -71, "text anchor y");
  close(pt(g.texts[0]).x, 11, "text position x"); close(pt(g.texts[0]).y, 904, "text position y");
  assert.deepEqual(g.params[0].value, [0.5, 0.5], "Motion Position untouched");
  assert.deepEqual(g.params[5].value, [0.5, 0.5], "Motion Anchor untouched");
  assert.deepEqual(undoSteps, ["CutDeck: Anchor top-left"]);
});

test("the text anchor is found through a moved Motion (the live 751,468 / 11,468)", async () => {
  const g = motionClip("Graphic", Object.assign({ graphic: true, position: [751 / 1920, 468 / 1080], anchor: [11 / 1920, 468 / 1080] }, LIVE_TEXT));
  const { ppro } = host([g]);
  await setAnchor(ppro, "top-left", async () => TEXT_BOX);
  // Motion shifts the canvas by +740 px, so the screen corner (11, 904) is canvas (-729, 904).
  close(pt(g.texts[0]).x, -729, "text position x"); close(pt(g.texts[0]).y, 904, "text position y");
  close(pt(g.textAnchors[0]).x, -729, "text anchor x"); close(pt(g.textAnchors[0]).y, -71, "text anchor y");
});

test("Anchor centre then Align left still lands the text's left edge on the frame", async () => {
  const g = motionClip("Graphic", Object.assign({ graphic: true }, LIVE_TEXT));
  const { ppro } = host([g]);
  await setAnchor(ppro, "center", async () => TEXT_BOX);
  close(pt(g.texts[0]).x, 220, "text position at the box centre x");
  await alignToFrame(ppro, "left", async () => TEXT_BOX);
  close(pt(g.texts[0]).x, 220 - 11, "moved left by the box's 11 px");
});

test("readAlignTransform on a text Graphic reads the text layer transform, not Motion", async () => {
  const g = motionClip("Graphic", Object.assign({ graphic: true }, LIVE_TEXT));
  const { ppro } = host([g]);
  const seq = await (await ppro.Project.getActiveProject()).getActiveSequence();
  const state = await readAlignTransform(seq, ppro);
  assert.equal(state.available, true);
  assert.equal(state.clipName, "Graphic");
  // LIVE_TEXT: Position [215.1/1920, 939.6/1080], Anchor [215.1/1920, -35.4/1080]
  close(state.fields.position.x, 215.1, "text position x");
  close(state.fields.position.y, 939.6, "text position y");
  close(state.fields.anchor.x, 215.1, "text anchor x");
  close(state.fields.anchor.y, -35.4, "text anchor y");
  assert.equal(state.fields.scale.value, 100);
  assert.equal(state.fields.rotation.value, 0);
});

test("setField on a text Graphic writes to the text layer's params, leaving Motion untouched", async () => {
  const g = motionClip("Graphic", Object.assign({ graphic: true }, LIVE_TEXT));
  const { ppro, undoSteps } = host([g]);
  const result = await setField(ppro, "position-x", "300");
  assert.equal(result.done, 1);
  close(pt(g.texts[0]).x, 300, "text position x set to 300");
  close(pt(g.texts[0]).y, 939.6, "text position y kept");
  assert.deepEqual(g.params[0].value, [0.5, 0.5], "Motion Position untouched");

  await setField(ppro, "scale", "125");
  assert.equal(g.textScales[0].value, 125, "text scale set to 125");
  assert.equal(g.params[1].value, 100, "Motion scale untouched");

  await setField(ppro, "rotation", "20");
  assert.equal(g.textRotations[0].value, 20, "text rotation set to 20");
  assert.equal(g.params[4].value, 0, "Motion rotation untouched");

  await setField(ppro, "anchor-x", "50");
  close(pt(g.textAnchors[0]).x, 50, "text anchor x set to 50");
  assert.deepEqual(g.params[5].value, [0.5, 0.5], "Motion anchor untouched");
  assert.deepEqual(undoSteps, ["CutDeck: Set position-x", "CutDeck: Set scale", "CutDeck: Set rotation", "CutDeck: Set anchor-x"]);
});

test("setField on a Graphic with shapeLayer falls back to writing Motion", async () => {
  const g = motionClip("Graphic", Object.assign({ graphic: true, shapeLayer: true }, LIVE_TEXT));
  const { ppro } = host([g]);
  await setField(ppro, "scale", "80");
  assert.equal(g.params[1].value, 80, "Motion scale updated");
  assert.equal(g.textScales[0].value, 100, "text layer scale left untouched");
});

test("setField on a Graphic with keyframed text skips with explanation", async () => {
  const g = motionClip("Graphic", Object.assign({ graphic: true, keyframedText: true }, LIVE_TEXT));
  const { ppro } = host([g]);
  const result = await setField(ppro, "position-x", "300");
  assert.equal(result.done, 0);
  assert.match(result.skipped[0], /has this value keyframed/);
  close(pt(g.texts[0]).x, 215.1, "text position untouched");
});

test("consecutive alignments and anchor changes on a Graphic use cached bounds with zero re-measurement", async () => {
  const g = motionClip("Graphic", Object.assign({ graphic: true }, LIVE_TEXT));
  const { ppro } = host([g]);
  let measureCount = 0;
  const measure = async () => {
    measureCount++;
    return TEXT_BOX;
  };

  // First action: measures the clip once
  await alignToFrame(ppro, "left", measure);
  assert.equal(measureCount, 1, "measured on first align");
  // Box (11, 904 - 429, 991) shifted left by 11 px -> left lands at 0
  close(pt(g.texts[0]).x, 215.1 - 11, "aligned left");

  // Second action: Align right -> MUST USE CACHE, measureCount remains 1
  await alignToFrame(ppro, "right", measure);
  assert.equal(measureCount, 1, "did not re-measure for align right");
  // Frame width is 1920, text width is 418 (429 - 11) -> right lands at 1920, left at 1502
  // Position shifted from (215.1 - 11) by +1502 = 1706.1
  close(pt(g.texts[0]).x, 215.1 - 11 + 1502, "aligned right");

  // Third action: Anchor top-left -> MUST USE CACHE, measureCount remains 1
  await setAnchor(ppro, "top-left", measure);
  assert.equal(measureCount, 1, "did not re-measure for anchor change");

  // Fourth action: Align center -> MUST USE CACHE, measureCount remains 1
  await alignToFrame(ppro, "hcenter", measure);
  assert.equal(measureCount, 1, "did not re-measure for align center");

  // Changing scale via setField invalidates the cache for this clip
  await setField(ppro, "scale", "150");
  await alignToFrame(ppro, "left", measure);
  assert.equal(measureCount, 2, "re-measured after scale change");
});

test("when measurement returns an unhideAction, it is committed atomically with the motion values in ONE transaction", async () => {
  const g = motionClip("Graphic", Object.assign({ graphic: true }, LIVE_TEXT));
  let disabled = true;
  g.createSetDisabledAction = (d) => fake.action(() => { disabled = d; });
  const { ppro } = host([g]);

  let unhideCalled = false;
  const measure = async () => {
    return {
      bounds: TEXT_BOX,
      unhideAction: (compound) => {
        unhideCalled = true;
        compound.addAction(g.createSetDisabledAction(false));
      },
    };
  };

  const result = await alignToFrame(ppro, "left", measure);
  assert.equal(result.done, 1);
  assert.equal(unhideCalled, true, "unhide action was executed as part of the compound transaction");
  assert.equal(disabled, false, "clip is restored");
});

test("bounds cache hits even when clip object reference changes if key (track:start) matches", async () => {
  const g1 = motionClip("Graphic", Object.assign({ graphic: true }, LIVE_TEXT));
  const g2 = motionClip("Graphic", Object.assign({ graphic: true }, LIVE_TEXT));
  g1.getTrackIndex = () => Promise.resolve(0);
  g1.getStartTime = () => Promise.resolve(fake.tickTime(100));
  g2.getTrackIndex = () => Promise.resolve(0);
  g2.getStartTime = () => Promise.resolve(fake.tickTime(100));

  let currentItem = g1;
  const { project } = fake.createProject();
  const seq = {
    name: "Seq",
    getSelection: () => Promise.resolve({ getTrackItems: () => Promise.resolve([currentItem]) }),
    getSettings: () => Promise.resolve({
      getVideoFrameRect: () => Promise.resolve({ width: 1920, height: 1080 }),
      getVideoPixelAspectRatio: () => Promise.resolve("1:1"),
    }),
  };
  project.getActiveSequence = () => Promise.resolve(seq);
  const ppro = {
    PointF: fake.PointF,
    Project: { getActiveProject: () => Promise.resolve(project) },
  };

  let measureCount = 0;
  const measure = async () => {
    measureCount++;
    return TEXT_BOX;
  };

  await alignToFrame(ppro, "left", measure);
  assert.equal(measureCount, 1);

  // Now selection returns g2 (different object instance, but same track and start time)
  g2.getComponentChain = g1.getComponentChain;
  currentItem = g2;
  await alignToFrame(ppro, "right", measure);
  assert.equal(measureCount, 1, "reused cached bounds via key even though object reference changed");
});

test("alignToFrame hcenter on odd-width text does not decrease X by 0.5 on consecutive clicks", async () => {
  // Live user scenario (UXPLogs 2026-09-24 22:43-22:48):
  // Drawn bounds 520..1401 (width 881).
  const LIVE_ODD_BOX = { left: 520, top: 383, right: 1401, bottom: 505 };
  const g = motionClip("Graphic", { graphic: true, texts: [[0.5, 0.5]] });
  const { ppro } = host([g]);

  await alignToFrame(ppro, "hcenter", async () => LIVE_ODD_BOX);
  const firstX = g.texts[0].value[0];

  // Second click: should be a no-op (shift 0), NOT decrease by 0.5px
  await alignToFrame(ppro, "hcenter", async () => LIVE_ODD_BOX);
  const secondX = g.texts[0].value[0];

  assert.equal(secondX, firstX, "second align click should not shift position");
});

test("alignToFrame vcenter on odd-height text does not decrease Y on consecutive clicks", async () => {
  // Odd height: 505 - 384 = 121px. Center is 444.5. Frame height 1080 -> center 540.
  const LIVE_ODD_HEIGHT_BOX = { left: 520, top: 384, right: 1400, bottom: 505 };
  const g = motionClip("Graphic", { graphic: true, texts: [[0.5, 0.5]] });
  const { ppro } = host([g]);

  await alignToFrame(ppro, "vcenter", async () => LIVE_ODD_HEIGHT_BOX);
  const firstY = g.texts[0].value[1];

  // Second click: must be identical, not shifting by 0.5
  await alignToFrame(ppro, "vcenter", async () => LIVE_ODD_HEIGHT_BOX);
  const secondY = g.texts[0].value[1];

  assert.equal(secondY, firstY, "second vertical align click should not shift position");
});

test("consecutive align clicks when already aligned do not add undo steps (noop)", async () => {
  const UNCENTERED_BOX = { left: 100, top: 500, right: 300, bottom: 580 };
  const g = motionClip("Graphic", { graphic: true, texts: [[0.5, 0.5]] });
  const { ppro, undoSteps } = host([g]);

  await alignToFrame(ppro, "hcenter", async () => UNCENTERED_BOX);
  assert.equal(undoSteps.length, 1, "first click adds one undo step");

  await alignToFrame(ppro, "hcenter", async () => UNCENTERED_BOX);
  assert.equal(undoSteps.length, 1, "second click is a noop and creates no additional undo step");
});





