const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  cutsToTicks, keepSubranges, planCutApply, verifyReadBack,
} = require("../uxp/cutdeck/timeline/cutPlanApply.js");

const golden = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "cutdeck_native_plan_golden.json"), "utf8"));
const TPF = BigInt(golden.ticks_per_frame);
const F = (n) => BigInt(n) * TPF;

function item(mediaType, track, start, end, mediaIn, extra = {}) {
  return { id: `${mediaType}${track}@${start}`, name: `${mediaType}${track}`, mediaType, track,
    startTicks: F(start), endTicks: F(end), inTicks: F(mediaIn), speed: 1, ...extra };
}

function toFrames(items, plan) {
  const out = [];
  items.forEach((it, i) => {
    for (const p of plan.edits[i].pieces) {
      out.push([it.mediaType, it.track, Number(p.startTicks / TPF), Number(p.endTicks / TPF), Number(p.inTicks / TPF)]);
    }
  });
  return out.sort((a, b) => (JSON.stringify(a) < JSON.stringify(b) ? -1 : 1));
}

test("golden: planner matches xml_recut.recut() frame-for-frame on the captured synced stack", () => {
  const items = golden.before.map(([k, t, s, e, i]) => item(k, t, s, e, i));
  const plan = planCutApply(items, cutsToTicks(golden, golden.ticks_per_frame));
  assert.equal(plan.refusal, undefined);
  const sortKey = (r) => JSON.stringify(r);
  assert.deepEqual(toFrames(items, plan).map(sortKey).sort(), golden.after.map(sortKey).sort());
});

test("golden: read-back of the planned result verifies clean; a 1-tick drift is caught", () => {
  const items = golden.before.map(([k, t, s, e, i]) => item(k, t, s, e, i));
  const plan = planCutApply(items, cutsToTicks(golden, golden.ticks_per_frame));
  const actual = [];
  items.forEach((it, i) => plan.edits[i].pieces.forEach((p) => actual.push({ ...it, ...p })));
  assert.deepEqual(verifyReadBack(items, plan, actual), []);
  actual[3] = { ...actual[3], startTicks: actual[3].startTicks + 1n };
  const problems = verifyReadBack(items, plan, actual);
  assert.equal(problems.length, 2);
  assert.match(problems.join("\n"), /unexpected .*\n?.*missing|missing/);
});

test("read-back: an item left behind inside a cut is reported, not ignored", () => {
  const items = [item("video", 0, 0, 100, 0)];
  const plan = planCutApply(items, [[F(40), F(60)]]);
  const actual = plan.edits[0].pieces.map((p) => ({ ...items[0], ...p }));
  actual.push({ ...items[0], startTicks: F(80), endTicks: F(100), inTicks: F(80) });
  assert.deepEqual(verifyReadBack(items, plan, actual).length, 1);
});

test("ops: keep, move, trim, remove, split", () => {
  const cuts = [[F(50), F(60)]];
  const items = [
    item("video", 0, 0, 40, 0),       // before the cut: keep
    item("video", 0, 70, 90, 5),      // after the cut: move left 10
    item("video", 1, 40, 55, 0),      // tail in the cut: trim
    item("video", 2, 52, 58, 0),      // wholly inside: remove
    item("audio", 0, 0, 100, 7),      // spans it: split
  ];
  const { edits, removedTicks } = planCutApply(items, cuts);
  assert.deepEqual(edits.map((e) => e.op), ["keep", "move", "trim", "remove", "split"]);
  assert.deepEqual(edits[1].pieces, [{ startTicks: F(60), endTicks: F(80), inTicks: F(5) }]);
  assert.deepEqual(edits[2].pieces, [{ startTicks: F(40), endTicks: F(50), inTicks: F(0) }]);
  assert.deepEqual(edits[4].pieces, [
    { startTicks: F(0), endTicks: F(50), inTicks: F(7) },
    { startTicks: F(50), endTicks: F(90), inTicks: F(67) },
  ]);
  assert.equal(removedTicks, F(10));
});

test("head trim: a clip starting inside a cut keeps media continuity", () => {
  const { edits } = planCutApply([item("video", 1, 27, 200, 0)], [[F(10), F(40)]]);
  assert.equal(edits[0].op, "trim");
  assert.deepEqual(edits[0].pieces, [{ startTicks: F(10), endTicks: F(170), inTicks: F(13) }]);
});

test("sync: relative offset of surviving pieces across tracks is unchanged", () => {
  const cuts = [[F(100), F(130)], [F(400), F(410)]];
  const v = item("video", 0, 0, 1000, 0), a = item("audio", 3, 17, 1017, 0);
  const { edits } = planCutApply([v, a], cuts);
  // Media time at every surviving sequence position must agree between tracks as before.
  const mediaAt = (pieces, t, shift) => { const p = pieces.find((q) => q.startTicks <= t && t < q.endTicks); return p ? p.inTicks + (t - p.startTicks) + shift : null; };
  for (const t of [F(0), F(50), F(99), F(100), F(300), F(500), F(900)]) {
    const mv = mediaAt(edits[0].pieces, t, 0n), ma = mediaAt(edits[1].pieces, t, F(17));
    if (mv !== null && ma !== null) assert.equal(ma, mv, `offset drift at frame ${t / TPF}`);
  }
});

test("refusal: whole plan, names clip and timecode, only when a cut lands inside", () => {
  const cuts = [[F(50), F(60)]];
  const fast = item("video", 0, 40, 80, 0, { speed: 2, name: "B-roll" });
  assert.match(planCutApply([item("video", 1, 0, 100, 0), fast], cuts).refusal,
    /B-roll \(video track 1\) at 00:00:01\.333-00:00:02\.666 is at 200% speed/);
  for (const flag of [{ reversed: true }, { isTransition: true }, { isNested: true }, { isMulticam: true }]) {
    assert.ok(planCutApply([item("video", 0, 40, 80, 0, flag)], cuts).refusal, JSON.stringify(flag));
  }
  // The same clip wholly after the cut only moves — allowed.
  const moved = planCutApply([item("video", 0, 70, 90, 0, { speed: 2, isNested: true })], cuts);
  assert.equal(moved.refusal, undefined);
  assert.equal(moved.edits[0].op, "move");
});

test("cutsToTicks: refuses a frame-grid mismatch and malformed lists", () => {
  assert.throws(() => cutsToTicks({ ticks_per_frame: "8475667200", cuts_frames: [[1, 2]] }, "10584000000"), /ticks\/frame/);
  assert.throws(() => cutsToTicks({ ticks_per_frame: String(TPF), cuts_frames: [[5, 5]] }, TPF), /empty/);
  assert.throws(() => cutsToTicks({ ticks_per_frame: String(TPF), cuts_frames: [[5, 9], [8, 12]] }, TPF), /overlaps/);
  assert.deepEqual(cutsToTicks({ ticks_per_frame: String(TPF), cuts_frames: [[1, 2]] }, String(TPF)), [[F(1), F(2)]]);
});

test("keepSubranges mirrors _keep_subranges edge cases", () => {
  assert.deepEqual(keepSubranges(0n, 10n, []), [[0n, 10n]]);
  assert.deepEqual(keepSubranges(0n, 10n, [[0n, 10n]]), []);
  assert.deepEqual(keepSubranges(0n, 10n, [[2n, 3n], [3n, 5n]]), [[0n, 2n], [5n, 10n]]);
  assert.deepEqual(keepSubranges(5n, 10n, [[0n, 6n], [9n, 20n]]), [[6n, 9n]]);
});
