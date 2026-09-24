/* Animated presets (timeline/effects.js). The time rule under test came from a live run of
   Check Keyframes on Premiere 26.5 (2026-09-23): keyframe times are MEDIA-relative — a keyframe
   on the clip's first frame read back as exactly getInPoint(). So capture stores
   (keyframe − source In point) and apply writes (target In point + offset).

   The fake host executes every Action it is handed, so the read-back check is exercised
   against real state, not against what the code intended to do. What real Premiere does with
   these calls (e.g. whether the stopwatch adds a keyframe of its own) is only knowable live;
   the read-back warning exists to surface exactly that. */
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");

const effects = require(path.join(__dirname, "..", "uxp", "cutdeck", "timeline", "effects.js"));

const TPF = 8475667200n; // 29.97 fps, the rate of the live probe run
const f = (n) => BigInt(n) * TPF;
const tt = (ticks) => ({ ticks: String(ticks) });

/* A param with real state: static value, time-varying flag, keyframes by tick string. */
function liveParam(name, { value = 100, keyframes = null, pointParam = false } = {}) {
  const state = { value, varying: !!keyframes, keys: new Map() };
  for (const [ticks, v, mode] of keyframes || []) state.keys.set(String(ticks), { value: v, mode });
  const makeKf = (v, ticks) => {
    const kf = { value: { value: v }, position: ticks !== undefined ? tt(ticks) : null };
    if (!pointParam) {
      kf.getTemporalInterpolationMode = () => Promise.resolve(state.keys.get(String(ticks))?.mode ?? 0);
    }
    return kf;
  };
  return {
    displayName: name, state,
    getStartValue: () => Promise.resolve({ value: { value: state.value } }),
    isTimeVarying: () => state.varying,
    getKeyframeListAsTickTimes: () => [...state.keys.keys()].sort((a, b) => (BigInt(a) < BigInt(b) ? -1 : 1)).map(tt),
    getKeyframePtr: (t) => makeKf(state.keys.get(String(t.ticks)).value, t.ticks),
    createKeyframe: (v) => makeKf(v),
    createSetValueAction: (kf) => ({ run: () => { state.value = kf.value.value; } }),
    createSetTimeVaryingAction: (on) => ({ run: () => { state.varying = on; } }),
    createAddKeyframeAction: (kf) => ({ run: () => state.keys.set(String(kf.position.ticks), { value: kf.value.value, mode: 0 }) }),
    createSetInterpolationAtKeyframeAction: (t, mode) => ({ run: () => { state.keys.get(String(t.ticks)).mode = mode; } }),
  };
}
function component(displayName, matchName, params) {
  return {
    getDisplayName: () => Promise.resolve(displayName),
    getMatchName: () => Promise.resolve(matchName),
    getParamCount: () => params.length,
    getParam: (i) => params[i],
  };
}
function trackItem(components, inPointFrames) {
  const chain = {
    list: components,
    getComponentCount: () => chain.list.length,
    getComponentAtIndex: (i) => chain.list[i],
    createInsertComponentAction: (c, at) => ({ run: () => chain.list.splice(at, 0, c.materialize()) }),
  };
  return { chain, getComponentChain: () => Promise.resolve(chain), getInPoint: () => Promise.resolve(tt(f(inPointFrames))) };
}
function project() {
  const labels = [];
  return {
    labels,
    executeTransaction: (fn, label) => {
      labels.push(label);
      const actions = [];
      fn({ addAction: (a) => { actions.push(a); return true; } });
      actions.forEach((a) => a.run());
      return true;
    },
  };
}
/* createComponent returns a factory-side object; inserting it yields a fresh live component. */
function ppro({ pointParam = false } = {}) {
  return {
    TickTime: { createWithTicks: (s) => tt(s) },
    VideoFilterFactory: {
      createComponent: (matchName) => Promise.resolve({
        materialize: () => component("Transform", matchName, [
          liveParam("Position", { value: [0.5, 0.5], pointParam: true }),
          liveParam("Scale"),
          liveParam("Rotation", { value: 0 }),
        ]),
      }),
    },
  };
}

test("placeKeyframes adds each offset to the target's In point", () => {
  assert.deepEqual(effects.placeKeyframes([{ offsetTicks: "0" }, { offsetTicks: f(5).toString() }], f(1000)),
    [f(1000).toString(), f(1005).toString()]);
});

test("capture stores keyframes as offsets from the clip's first frame, with their modes", async () => {
  // Live-probe shape: clip In point at source frame 107893; keyframes on its first frame and 5 later.
  const inFrames = 107893;
  const scale = liveParam("Scale", { keyframes: [[f(inFrames), 100, 0], [f(inFrames + 5), 120, 5]] });
  const position = liveParam("Position", { value: [0.5, 0.5], pointParam: true, keyframes: [[f(inFrames), [0.5, 0.5]]] });
  const item = trackItem([component("Transform", "AE.ADBE Geometry2", [position, scale, liveParam("Rotation", { value: 0 })])], inFrames);

  const captured = await effects.captureEffectFromTrackItem(ppro(), item);
  const [pos, sc, rot] = captured.components[0].params;
  assert.equal(captured.animatedCount, 2);
  assert.deepEqual(sc.keyframes, [
    { offsetTicks: "0", value: 100, mode: 0 },
    { offsetTicks: f(5).toString(), value: 120, mode: 5 },
  ]);
  assert.deepEqual(pos.keyframes, [{ offsetTicks: "0", value: [0.5, 0.5], mode: null }], "PointKeyframe has no mode getter");
  assert.equal(rot.keyframes, undefined, "static params carry no keyframes");
});

test("apply replays keyframes at the target's own In point, with interpolation, and skips static set for them", async () => {
  const preset = { components: [{ matchName: "AE.ADBE Geometry2", displayName: "Transform", params: [
    { index: 1, displayName: "Scale", value: 100, keyframes: [
      { offsetTicks: "0", value: 100, mode: 0 },
      { offsetTicks: f(5).toString(), value: 120, mode: 5 },
    ] },
    { index: 2, displayName: "Rotation", value: 15 },
  ] }] };
  const target = trackItem([], 42);
  const proj = project();
  const { warnings } = await effects.applyCapturedPreset(ppro(), proj, target, preset);

  assert.deepEqual(warnings, []);
  const [, scale, rotation] = [0, 1, 2].map((i) => target.chain.list[0].getParam(i));
  assert.equal(rotation.state.value, 15);
  assert.equal(scale.state.varying, true);
  assert.deepEqual([...scale.state.keys.entries()], [
    [f(42).toString(), { value: 100, mode: 0 }],
    [f(47).toString(), { value: 120, mode: 5 }],
  ]);
  assert.deepEqual(proj.labels, [
    "CutDeck: Apply Captured Preset (insert)",
    "CutDeck: Apply Captured Preset (values)",
    "CutDeck: Apply Captured Preset (enable keyframes)",
    "CutDeck: Apply Captured Preset (keyframes)",
    "CutDeck: Apply Captured Preset (interpolation)",
  ]);
});

test("a static-only preset runs exactly the two old transactions", async () => {
  const preset = { components: [{ matchName: "AE.ADBE Geometry2", params: [{ index: 2, displayName: "Rotation", value: 15 }] }] };
  const proj = project();
  await effects.applyCapturedPreset(ppro(), proj, trackItem([], 0), preset);
  assert.equal(proj.labels.length, 2);
});

test("read-back reports keyframes that didn't land where captured (e.g. a stopwatch-added extra)", async () => {
  const host = ppro();
  const preset = { components: [{ matchName: "AE.ADBE Geometry2", displayName: "Transform", params: [
    { index: 1, displayName: "Scale", value: 100, keyframes: [{ offsetTicks: "0", value: 100, mode: 0 }] },
  ] }] };
  const target = trackItem([], 10);
  const realCreate = host.VideoFilterFactory.createComponent;
  host.VideoFilterFactory.createComponent = async (m) => {
    const c = await realCreate(m);
    const materialize = c.materialize;
    c.materialize = () => {
      const comp = materialize();
      const scale = comp.getParam(1);
      const enable = scale.createSetTimeVaryingAction;
      // Simulate Premiere dropping an extra keyframe at 0 when the stopwatch turns on.
      scale.createSetTimeVaryingAction = (on) => ({ run: () => { enable(on).run(); scale.state.keys.set("0", { value: 1, mode: 0 }); } });
      return comp;
    };
    return c;
  };
  const { warnings } = await effects.applyCapturedPreset(host, project(), target, preset);
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /expected keyframes at .* but found 0, /);
});

test("point values ([x, y] as captured) are written as PointF, other values pass through", () => {
  class PointF { constructor(x, y) { this.x = x; this.y = y; } }
  const host = { PointF };
  const p = effects.toParamValue(host, [0.5, 0.25]);
  assert.ok(p instanceof PointF);
  assert.deepEqual([p.x, p.y], [0.5, 0.25]);
  assert.ok(effects.toParamValue(host, { x: 1, y: 2 }) instanceof PointF);
  assert.equal(effects.toParamValue(host, 100), 100);
  assert.equal(effects.toParamValue(host, true), true);
  assert.deepEqual(effects.toParamValue(host, [1, 2, 3]), [1, 2, 3], "not a 2D point");
});

test("applyCapturedPresetToAll: 3 ALs, still 5 transactions, each AL keyed at its own In point", async () => {
  const preset = { components: [{ matchName: "AE.ADBE Geometry2", displayName: "Transform", params: [
    { index: 1, displayName: "Scale", value: 100, keyframes: [
      { offsetTicks: "0", value: 100, mode: 0 },
      { offsetTicks: f(5).toString(), value: 120, mode: 5 },
    ] },
    { index: 2, displayName: "Rotation", value: 15 },
  ] }] };
  const targets = [trackItem([], 10), trackItem([], 200), trackItem([], 3000)];
  const proj = project();
  const { warnings } = await effects.applyCapturedPresetToAll(ppro(), proj, targets, preset);

  assert.deepEqual(warnings, []);
  assert.equal(proj.labels.length, 5, "one transaction per phase, not per AL");
  for (const [t, inF] of [[targets[0], 10], [targets[1], 200], [targets[2], 3000]]) {
    const [, scale, rotation] = [0, 1, 2].map((i) => t.chain.list[0].getParam(i));
    assert.equal(t.chain.list.length, 1, "exactly one component inserted per AL");
    assert.equal(rotation.state.value, 15);
    assert.deepEqual([...scale.state.keys.keys()], [f(inF).toString(), f(inF + 5).toString()]);
  }
});
