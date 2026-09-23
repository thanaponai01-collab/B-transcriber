const test = require("node:test");
const assert = require("node:assert/strict");

const {
  resolveTopLayer,
  planPlacements,
  assignPlacementLanes,
} = require("../uxp/cutdeck/timeline/alPlacement.js");


const TPF_24FPS = 10594584000n; // 1 frame in ticks at 24fps

test("resolveTopLayer: single clip returns its full span", () => {
  const clips = [{ track: 0, startTicks: 1000n, endTicks: 5000n }];
  const res = resolveTopLayer(clips);
  assert.equal(res.length, 1);
  assert.equal(res[0].startTicks, 1000n);
  assert.equal(res[0].endTicks, 5000n);
});

test("resolveTopLayer: separated clips preserve the gap", () => {
  const clips = [
    { track: 0, startTicks: 1000n, endTicks: 2000n },
    { track: 0, startTicks: 3000n, endTicks: 4000n },
  ];
  const res = resolveTopLayer(clips);
  assert.equal(res.length, 2);
  assert.equal(res[0].startTicks, 1000n);
  assert.equal(res[0].endTicks, 2000n);
  assert.equal(res[1].startTicks, 3000n);
  assert.equal(res[1].endTicks, 4000n);
});

test("resolveTopLayer: higher track clip wins overlapping region", () => {
  const clips = [
    { track: 1, startTicks: 0n, endTicks: 100n },
    { track: 2, startTicks: 50n, endTicks: 150n },
  ];
  const res = resolveTopLayer(clips);
  assert.equal(res.length, 2);
  // Track 1 wins [0, 50]
  assert.equal(res[0].startTicks, 0n);
  assert.equal(res[0].endTicks, 50n);
  // Track 2 wins [50, 150]
  assert.equal(res[1].startTicks, 50n);
  assert.equal(res[1].endTicks, 150n);
});

test("resolveTopLayer (2026-09-21 dated fix): V2 under V4 and V3 does not introduce extra split points", () => {
  // A V2 clip straddling the real boundary between a V4 clip and a V3 clip
  // must not fragment what should have been 2 clean AL segments into 4.
  const clips = [
    { track: 4, startTicks: 0n, endTicks: 100n },   // V4
    { track: 3, startTicks: 100n, endTicks: 200n }, // V3
    { track: 2, startTicks: 50n, endTicks: 150n },  // V2 underneath both
  ];
  const res = resolveTopLayer(clips);
  // V4 wins [0, 100], V3 wins [100, 200]. V2 never wins any segment.
  assert.equal(res.length, 2);
  assert.equal(res[0].startTicks, 0n);
  assert.equal(res[0].endTicks, 100n);
  assert.equal(res[1].startTicks, 100n);
  assert.equal(res[1].endTicks, 200n);
});

test("resolveTopLayer: clip underneath winning only uncovered tail", () => {
  const clips = [
    { track: 4, startTicks: 0n, endTicks: 100n },
    { track: 2, startTicks: 50n, endTicks: 200n },
  ];
  const res = resolveTopLayer(clips);
  assert.equal(res.length, 2);
  assert.equal(res[0].startTicks, 0n);
  assert.equal(res[0].endTicks, 100n);
  assert.equal(res[1].startTicks, 100n);
  assert.equal(res[1].endTicks, 200n);
});

test("assignPlacementLanes: non-overlapping placements all assign to lane 0", () => {
  const placements = [
    { startTicks: 0n, endTicks: 100n },
    { startTicks: 100n, endTicks: 200n },
    { startTicks: 250n, endTicks: 300n },
  ];
  const lanes = assignPlacementLanes(placements);
  assert.deepEqual(lanes, [0, 0, 0]);
});

test("assignPlacementLanes (2026-09-21 tight cuts): overlapping transition spans stack into separate lanes", () => {
  const placements = [
    { startTicks: 0n, endTicks: 100n },   // cut 1 AL: [0, 100]
    { startTicks: 50n, endTicks: 150n },  // cut 2 AL: [50, 150] (overlaps cut 1)
    { startTicks: 120n, endTicks: 220n }, // cut 3 AL: [120, 220] (overlaps cut 2, but lane 0 is free after 100)
  ];
  const lanes = assignPlacementLanes(placements);
  assert.equal(lanes[0], 0);
  assert.equal(lanes[1], 1);
  assert.equal(lanes[2], 0); // Reuses lane 0 since 120 >= 100
});

test("assignPlacementLanes: 3 fully overlapping placements require 3 lanes", () => {
  const placements = [
    { startTicks: 0n, endTicks: 100n },
    { startTicks: 20n, endTicks: 120n },
    { startTicks: 40n, endTicks: 140n },
  ];
  const lanes = assignPlacementLanes(placements);
  assert.deepEqual(lanes, [0, 1, 2]);
});

test("planPlacements: span mode with selection", () => {
  const spans = [
    { startTicks: 100n, endTicks: 500n },
    { startTicks: 700n, endTicks: 1000n },
  ];
  const p = planPlacements({
    mode: "span",
    spans,
    frames: 16,
    tpf: TPF_24FPS,
    cti: 0n,
  });
  assert.equal(p.length, 1);
  assert.equal(p[0].startTicks, 100n);
  assert.equal(p[0].endTicks, 1000n);
  assert.equal(p[0].name, "ADJ_Span");

  // Single span gets ADJ_Fit
  const pSingle = planPlacements({
    mode: "span",
    spans: [{ startTicks: 100n, endTicks: 500n }],
    frames: 16,
    tpf: TPF_24FPS,
    cti: 0n,
    effectName: "Zoom",
  });
  assert.equal(pSingle.length, 1);
  assert.equal(pSingle[0].name, "ADJ_Zoom");
});

test("planPlacements: span mode fallback to In/Out then CTI", () => {
  // With In/Out
  const pInOut = planPlacements({
    mode: "span",
    spans: [],
    inPoint: 2000n,
    outPoint: 8000n,
    effectName: "Blur",
  });
  assert.equal(pInOut.length, 1);
  assert.equal(pInOut[0].startTicks, 2000n);
  assert.equal(pInOut[0].endTicks, 8000n);
  assert.equal(pInOut[0].name, "ADJ_Blur");

  // Default In/Out naming
  const pInOutDefault = planPlacements({
    mode: "span",
    spans: [],
    inPoint: 2000n,
    outPoint: 8000n,
  });
  assert.equal(pInOutDefault[0].name, "ADJ_InOut");

  // Fallback to CTI
  const pCTI = planPlacements({
    mode: "span",
    spans: [],
    frames: 16,
    tpf: TPF_24FPS,
    cti: 20n * TPF_24FPS,
  });
  assert.equal(pCTI.length, 1);
  assert.equal(pCTI[0].name, "ADJ_16f");
  const half = 8n * TPF_24FPS;
  assert.equal(pCTI[0].startTicks, 20n * TPF_24FPS - half);
  assert.equal(pCTI[0].endTicks, 20n * TPF_24FPS - half + 16n * TPF_24FPS);
});

test("planPlacements: per_clip mode with selection", () => {
  const spans = [
    { startTicks: 100n, endTicks: 500n },
    { startTicks: 700n, endTicks: 1000n },
  ];
  const p = planPlacements({
    mode: "per_clip",
    spans,
  });
  assert.equal(p.length, 2);
  assert.equal(p[0].startTicks, 100n);
  assert.equal(p[0].endTicks, 500n);
  assert.equal(p[0].name, "ADJ_Clip_1");
  assert.equal(p[1].startTicks, 700n);
  assert.equal(p[1].endTicks, 1000n);
  assert.equal(p[1].name, "ADJ_Clip_2");

  // Single clip gets ADJ_Fit
  const p1 = planPlacements({
    mode: "per_clip",
    spans: [{ startTicks: 100n, endTicks: 500n }],
  });
  assert.equal(p1[0].name, "ADJ_Fit");
});

test("planPlacements: transition mode on cuts with clamping", () => {
  const tpf = 1000n;
  const frames = 16;
  const halfFrames = 8n;
  const halfTicks = halfFrames * tpf; // 8000n

  // Two adjacent clips: clip1 [0, 50000], clip2 [50000, 100000]
  // Durations: 50000 each. 45% of 50000 is 22500 > halfTicks (8000), so no clamp reduction.
  const spans = [
    { startTicks: 0n, endTicks: 50000n },
    { startTicks: 50000n, endTicks: 100000n },
  ];
  const p = planPlacements({
    mode: "transition",
    spans,
    frames,
    tpf,
    clamp: true,
  });
  assert.equal(p.length, 1);
  assert.equal(p[0].startTicks, 50000n - 8000n);
  assert.equal(p[0].endTicks, 50000n + 8000n);
  assert.equal(p[0].name, "ADJ_Cut_16f");

  // Short clips triggering clamp: clip1 [40000, 50000] (dur = 10000), clip2 [50000, 55000] (dur = 5000)
  // maxHalfLeft = 10000 * 45 / 100 = 4500 < 8000
  // maxHalfRight = 5000 * 45 / 100 = 2250 < 8000
  const shortSpans = [
    { startTicks: 40000n, endTicks: 50000n },
    { startTicks: 50000n, endTicks: 55000n },
  ];
  const pClamped = planPlacements({
    mode: "transition",
    spans: shortSpans,
    frames,
    tpf,
    clamp: true,
  });
  assert.equal(pClamped.length, 1);
  assert.equal(pClamped[0].startTicks, 50000n - 4500n);
  assert.equal(pClamped[0].endTicks, 50000n + 2250n);

  // When clamp is false, full halfTicks is used
  const pUnclamped = planPlacements({
    mode: "transition",
    spans: shortSpans,
    frames,
    tpf,
    clamp: false,
  });
  assert.equal(pUnclamped.length, 1);
  assert.equal(pUnclamped[0].startTicks, 50000n - 8000n);
  assert.equal(pUnclamped[0].endTicks, 50000n + 8000n);
});

test("planPlacements: transition mode fallback to CTI when no cuts", () => {
  const p = planPlacements({
    mode: "transition",
    spans: [],
    frames: 10,
    tpf: 1000n,
    cti: 20000n,
    effectName: "Whip",
  });
  assert.equal(p.length, 1);
  assert.equal(p[0].startTicks, 20000n - 5000n);
  assert.equal(p[0].endTicks, 20000n - 5000n + 10000n);
  assert.equal(p[0].name, "ADJ_Whip_10f");
});
