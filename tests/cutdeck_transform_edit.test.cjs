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
const { setAnchor, alignToFrame, alignToSelection, distribute, setField, readAlignTransform } = require("../uxp/cutdeck/features/align.js");

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
  const chain = o.graphic ? (o.noVectorMotion ? [motion, ...texts, ...extra] : [motion, vm, ...texts, ...extra]) : [motion];
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






// --- Phase 6: align to selection, distribute ----------------------------------------------------

// Rendered box of a scale-only 1280x720 clip in the 1920x1080 frame, from its written Position.
const box = (c) => {
  const w = (1280 * c.params[1].value) / 100;
  const h = (720 * c.params[1].value) / 100;
  const cx = c.params[0].value[0] * 1920;
  const cy = c.params[0].value[1] * 1080;
  return { left: cx - w / 2, right: cx + w / 2, top: cy - h / 2, bottom: cy + h / 2, cx, cy };
};
const at = (x, y = 0.5, scale = 50) => ({ position: [x / 1920, y], scale });

test("unionBounds spans every box; alignShiftTo aligns to that box, not the frame", () => {
  const u = geometry.unionBounds([{ left: 10, top: 20, right: 50, bottom: 60 }, { left: 0, top: 30, right: 40, bottom: 90 }]);
  assert.deepEqual(u, { left: 0, top: 20, right: 50, bottom: 90 });
  const b = { left: 10, top: 20, right: 50, bottom: 60 };
  assert.deepEqual(geometry.alignShiftTo(b, u, "left"), { dx: -10, dy: 0 });
  assert.deepEqual(geometry.alignShiftTo(b, u, "right"), { dx: 0, dy: 0 });
  assert.deepEqual(geometry.alignShiftTo(b, u, "vcenter"), { dx: 0, dy: 15 });
  assert.deepEqual(geometry.alignShift(b, { width: 100, height: 100 }, "left"), { dx: -10, dy: 0 });
});

test("distributeShifts: centres even out, the outer two stay, results follow input order", () => {
  const boxes = [{ left: 375, right: 425, top: 0, bottom: 10 }, { left: 75, right: 125, top: 0, bottom: 10 }, { left: 100, right: 200, top: 0, bottom: 10 }];
  // centres 400 / 100 / 150: sorted 100 (idx1), 150 (idx2), 400 (idx0) → middle goes to 250.
  const s = geometry.distributeShifts(boxes, "x", "centers");
  assert.deepEqual(s.map((v) => Math.round(v * 1e6) / 1e6), [0, 0, 100]);
});

test("distributeShifts gaps: equal space between neighbours whatever their widths", () => {
  const boxes = [{ left: 0, right: 100, top: 0, bottom: 1 }, { left: 120, right: 140, top: 0, bottom: 1 }, { left: 500, right: 700, top: 0, bottom: 1 }];
  const s = geometry.distributeShifts(boxes, "x", "gaps");
  const moved = boxes.map((b, i) => ({ l: b.left + s[i], r: b.right + s[i] }));
  close(moved[1].l - moved[0].r, moved[2].l - moved[1].r, "gap");
  close(moved[0].l, 0, "first stays"); close(moved[2].r, 700, "last stays");
});

test("distributeFrameShifts centers: spaces element centers evenly across the sequence frame", () => {
  const frame = { width: 1920, height: 1080 };
  const boxes = [
    { left: 100, right: 300, top: 0, bottom: 10 }, // center 200
    { left: 800, right: 1000, top: 0, bottom: 10 }, // center 900
  ];
  // n = 2: targets are 1920 / 3 = 640 and 2 * 1920 / 3 = 1280.
  const s = geometry.distributeFrameShifts(boxes, frame, "x", "centers");
  close(200 + s[0], 640, "box 0 center");
  close(900 + s[1], 1280, "box 1 center");
});

test("distributeFrameShifts gaps: equal margins on screen edges and equal gaps between elements", () => {
  const frame = { width: 1920, height: 1080 };
  // 3 boxes with widths 200, 200, 200: total width = 600.
  // Remaining space = 1920 - 600 = 1320.
  // (n + 1) = 4 spaces (left margin, 2 middle gaps, right margin) -> each space = 1320 / 4 = 330.
  const boxes = [
    { left: 50, right: 250, top: 0, bottom: 10 },
    { left: 700, right: 900, top: 0, bottom: 10 },
    { left: 1400, right: 1600, top: 0, bottom: 10 },
  ];
  const s = geometry.distributeFrameShifts(boxes, frame, "x", "gaps");
  const moved = boxes.map((b, i) => ({ left: b.left + s[i], right: b.right + s[i] }));
  const marginL = moved[0].left - 0;
  const gap1 = moved[1].left - moved[0].right;
  const gap2 = moved[2].left - moved[1].right;
  const marginR = 1920 - moved[2].right;

  close(marginL, 330, "left margin");
  close(gap1, 330, "middle gap 1");
  close(gap2, 330, "middle gap 2");
  close(marginR, 330, "right margin");
});

test("alignToSelection left lines every clip's left edge up on the leftmost clip", async () => {
  const a = motionClip("A", at(400));
  const b = motionClip("B", at(1000, 0.3, 30));
  const { ppro, undoSteps } = host([a, b]);
  const left = Math.min(box(a).left, box(b).left);
  const result = await alignToSelection(ppro, "left");
  assert.deepEqual(result, { done: 2, skipped: [] });
  close(box(a).left, left, "A left"); close(box(b).left, left, "B left");
  close(box(b).cy, 0.3 * 1080, "B's y untouched");
  assert.deepEqual(undoSteps, ["CutDeck: Align left to selection"]);
});

test("alignToSelection needs two clips and writes nothing with one", async () => {
  const a = motionClip("A", at(400));
  const { ppro, undoSteps } = host([a]);
  await assert.rejects(() => alignToSelection(ppro, "left"), /at least 2/);
  assert.deepEqual(undoSteps, []);
});

test("distribute h-centers spaces three clips' centres evenly, in one undo step", async () => {
  const [a, b, c] = [motionClip("A", at(300)), motionClip("B", at(500, 0.4)), motionClip("C", at(1500, 0.6))];
  const { ppro, undoSteps } = host([b, c, a]); // selection order must not matter
  const result = await distribute(ppro, "h-centers");
  assert.equal(result.done, 3);
  close(box(b).cx, (300 + 1500) / 2, "middle centre");
  close(box(a).cx, 300, "leftmost stays"); close(box(c).cx, 1500, "rightmost stays");
  close(box(b).cy, 0.4 * 1080, "y untouched");
  assert.deepEqual(undoSteps, ["CutDeck: Distribute h-centers"]);
});

test("distribute v-gaps makes the vertical gaps equal for clips of different heights", async () => {
  const cs = [motionClip("A", at(960, 0.2, 30)), motionClip("B", at(960, 0.35, 60)), motionClip("C", at(960, 0.9, 40))];
  const { ppro } = host(cs);
  await distribute(ppro, "v-gaps");
  const [a, b, c] = cs.map(box);
  close(b.top - a.bottom, c.top - b.bottom, "gap");
  close(a.top, 0.2 * 1080 - 0.5 * 720 * 0.3, "first stays");
});

test("distribute needs three usable clips: two, or three with one keyframed, is refused untouched", async () => {
  const [a, b] = [motionClip("A", at(300)), motionClip("B", at(900))];
  const one = host([a, b]);
  await assert.rejects(() => distribute(one.ppro, "h-centers"), /at least 3/);
  const animated = motionClip("Z", Object.assign(at(1500), { keyframedPosition: true }));
  const two = host([a, b, animated]);
  await assert.rejects(() => distribute(two.ppro, "h-gaps"), /at least 3.*Z.*keyframed/);
  assert.deepEqual([one.undoSteps, two.undoSteps], [[], []]);
});

test("distribute with to='frame' spaces 2 clips across sequence frame with equal margins and gaps", async () => {
  // 2 clips of width 640 (scale 50% of 1280): widths are 640, 640. Total = 1280.
  // In 1920 frame: remaining space = 1920 - 1280 = 640.
  // 3 spaces -> each space is 640 / 3 = 213.333333 px.
  const a = motionClip("A", at(200));
  const b = motionClip("B", at(1200));
  const { ppro, undoSteps } = host([a, b]);
  const result = await distribute(ppro, "h-gaps", null, "frame");
  assert.equal(result.done, 2);
  const [bA, bB] = [box(a), box(b)];
  const marginL = bA.left;
  const middleGap = bB.left - bA.right;
  const marginR = 1920 - bB.right;
  close(marginL, 640 / 3, "left margin");
  close(middleGap, 640 / 3, "middle gap");
  close(marginR, 640 / 3, "right margin");
  assert.deepEqual(undoSteps, ["CutDeck: Distribute h-gaps across frame"]);
});

test("distribute with to='frame' needs at least 2 usable clips; 1 is refused", async () => {
  const a = motionClip("A", at(300));
  const one = host([a]);
  await assert.rejects(() => distribute(one.ppro, "h-centers", null, "frame"), /at least 2/);
  assert.deepEqual(one.undoSteps, []);
});

test("distribute with to='frame' on single Graphic with 2 text layers distributes across frame", async () => {
  const g = motionClip("Graphic", {
    graphic: true,
    texts: [[0.2, 0.5], [0.8, 0.5]], // 384, 1536
    vectorMotion: { scale: 100, scaleWidth: 100, uniformScale: true, rotation: 0 },
  });
  const { ppro, undoSteps } = host([g]);

  const result = await distribute(ppro, "h-centers", null, "frame");
  assert.equal(result.done, 1);
  // 2 layers: target centers at 1920 / 3 = 640 and 2 * 1920 / 3 = 1280
  close(g.texts[0].value[0] * 1920, 640, "Layer 0 center at 640");
  close(g.texts[1].value[0] * 1920, 1280, "Layer 1 center at 1280");
  assert.deepEqual(undoSteps, ["CutDeck: Distribute h-centers across frame text layers"]);
});

test("setField on a multi-text Graphic preserves relative positions between text layers", async () => {
  const g = motionClip("Graphic", {
    graphic: true,
    texts: [[0.1, 0.5], [0.3, 0.5]],
    vectorMotion: { scale: 100, scaleWidth: 100, uniformScale: true, rotation: 0 },
  });
  const { ppro } = host([g]);

  const res = await setField(ppro, "position-x", "200");
  assert.equal(res.done, 1);

  close(g.texts[0].value[0] * 1920, 200, "Layer 0 moved to 200");
  close(g.texts[1].value[0] * 1920, 584, "Layer 1 moved by same delta (+8px) preserving spacing");
});

test("setAnchor on a multi-text Graphic falls back to Motion anchor and does not collapse text positions", async () => {
  const g = motionClip("Graphic", {
    graphic: true,
    texts: [[0.1, 0.2], [0.5, 0.8]],
    vectorMotion: { scale: 100, scaleWidth: 100, uniformScale: true, rotation: 0 },
  });
  const { ppro } = host([g]);

  const TEXT_BOX = { left: 100, top: 200, right: 900, bottom: 800 };
  const measure = async () => TEXT_BOX;

  await setAnchor(ppro, "top-left", measure);

  close(g.texts[0].value[0], 0.1, "Text 0 position preserved");
  close(g.texts[1].value[0], 0.5, "Text 1 position preserved");
  close(g.params[5].value[0] * 1920, 100, "Motion anchor X matches top-left");
  close(g.params[5].value[1] * 1080, 200, "Motion anchor Y matches top-left");
});

test("isGraphic returns true for a clip with AE.ADBE Text even without AE.ADBE Graphic Group", async () => {
  const { isGraphic } = require("../uxp/cutdeck/transform/params.js");
  const textOnlyClip = {
    getComponentChain: async () => ({
      getComponentCount: () => 2,
      getComponentAtIndex: (i) => ({
        getMatchName: () => (i === 0 ? "AE.ADBE Motion" : "AE.ADBE Text"),
      }),
    }),
  };
  assert.equal(await isGraphic(textOnlyClip), true);
});

test("alignToFrame on multi-text Graphic shifts bounds cache once, not multiplied by layer count", async () => {
  const g = motionClip("Graphic", {
    graphic: true,
    texts: [[0.2, 0.5], [0.6, 0.5]],
    vectorMotion: { scale: 100, scaleWidth: 100, uniformScale: true, rotation: 0 },
  });
  const { ppro } = host([g]);

  let measureCount = 0;
  const TEXT_BOX = { left: 200, top: 400, right: 600, bottom: 500 };
  const measure = async () => {
    measureCount++;
    return TEXT_BOX;
  };

  await alignToFrame(ppro, "left", measure);
  assert.equal(measureCount, 1);

  await alignToFrame(ppro, "right", measure);
  assert.equal(measureCount, 1, "did not re-measure on second align");

  close(g.texts[0].value[0] * 1920, 0.2 * 1920 + 1320, "Text 0 at right");
  close(g.texts[1].value[0] * 1920, 0.6 * 1920 + 1320, "Text 1 at right");
});

test("setField on multi-text Graphic scales proportionally and rotates with relative delta", async () => {
  const g = motionClip("Graphic", {
    graphic: true,
    texts: [[0.2, 0.5], [0.6, 0.5]],
    vectorMotion: { scale: 100, scaleWidth: 100, uniformScale: true, rotation: 0 },
  });
  // Initially Text 0 is 100%, Text 1 is set to 80% scale, 15° rotation
  g.textScales[1].value = 80;
  g.textRotations[1].value = 15;
  const { ppro } = host([g]);

  // Scale: 100 -> 150 (ratio = 1.5). Text 0 becomes 150, Text 1 becomes 80 * 1.5 = 120
  await setField(ppro, "scale", "150");
  assert.equal(g.textScales[0].value, 150, "Text 0 scale is 150");
  assert.equal(g.textScales[1].value, 120, "Text 1 scale proportionally scaled to 120");

  // Rotation: 0 -> 10 (delta = +10°). Text 0 becomes 10, Text 1 becomes 15 + 10 = 25
  await setField(ppro, "rotation", "10");
  assert.equal(g.textRotations[0].value, 10, "Text 0 rotation is 10");
  assert.equal(g.textRotations[1].value, 25, "Text 1 rotation relatively shifted to 25");
});

test("alignToSelection on a single Graphic with multiple text layers aligns text layers inside the graphic", async () => {
  const g = motionClip("Graphic", {
    graphic: true,
    texts: [[0.2, 0.3], [0.5, 0.6]], // Layer 0: x=384, y=324; Layer 1: x=960, y=648
    vectorMotion: { scale: 100, scaleWidth: 100, uniformScale: true, rotation: 0 },
  });
  const { ppro, undoSteps } = host([g]);

  // Align left: should align Layer 1's X to Layer 0's X (384 px = 0.2)
  const result = await alignToSelection(ppro, "left");
  assert.equal(result.done, 1);
  close(g.texts[0].value[0] * 1920, 384, "Layer 0 stays at 384");
  close(g.texts[1].value[0] * 1920, 384, "Layer 1 moved left to 384");
  assert.deepEqual(undoSteps, ["CutDeck: Align left text layers"]);

  // Align vcenter: should center their Y positions
  await alignToSelection(ppro, "vcenter");
  const expectedCenterY = (324 + 648) / 2; // 486
  close(g.texts[0].value[1] * 1080, expectedCenterY, "Layer 0 Y centered");
  close(g.texts[1].value[1] * 1080, expectedCenterY, "Layer 1 Y centered");
});

test("distribute on a single Graphic with 3 text layers evenly distributes their positions", async () => {
  const g = motionClip("Graphic", {
    graphic: true,
    texts: [[0.1, 0.2], [0.3, 0.3], [0.9, 0.8]], // x = 192, 576, 1728
    vectorMotion: { scale: 100, scaleWidth: 100, uniformScale: true, rotation: 0 },
  });
  const { ppro, undoSteps } = host([g]);

  const result = await distribute(ppro, "h-centers");
  assert.equal(result.done, 1);
  // Outer text layers stay at 192 and 1728; middle text layer moves to (192 + 1728)/2 = 960
  close(g.texts[0].value[0] * 1920, 192, "First layer stays at 192");
  close(g.texts[2].value[0] * 1920, 1728, "Last layer stays at 1728");
  close(g.texts[1].value[0] * 1920, 960, "Middle layer evenly spaced at 960");
  assert.deepEqual(undoSteps, ["CutDeck: Distribute h-centers text layers"]);
});

test("alignToFrame and setAnchor work on a Graphic clip without Vector Motion", async () => {
  const g = motionClip("Graphic", {
    graphic: true,
    noVectorMotion: true,
    texts: [[0.5, 0.5]],
  });
  const { ppro } = host([g]);

  const TEXT_BOX = { left: 400, top: 300, right: 800, bottom: 500 };
  const measure = async () => TEXT_BOX;

  // Align left on text clip with no Vector Motion shifts the text layer directly
  await alignToFrame(ppro, "left", measure);
  close(g.texts[0].value[0] * 1920, 0.5 * 1920 - 400, "Text layer shifted left without VM");
  assert.deepEqual(g.params[0].value, [0.5, 0.5], "Motion Position untouched");

  // Set anchor on text clip with no Vector Motion updates text anchor and position
  await setAnchor(ppro, "center", measure);
  assert.deepEqual(g.params[5].value, [0.5, 0.5], "Motion anchor untouched");
  close(pt(g.texts[0]).x, 200, "Text position updated to center of shifted box (200)");
  close(pt(g.texts[0]).y, 400, "Text position updated to center (400)");
  close(pt(g.textAnchors[0]).x, -360, "Text anchor updated to -360");
  close(pt(g.textAnchors[0]).y, -140, "Text anchor updated to -140");
});
