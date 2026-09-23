/* Phase 1 of docs/HANDOFF_CUTDECK_TIMELINE_IN_OUT.md: exact range and placement
   arithmetic. Pure — nothing here touches Premiere or mutates a timeline. */
const test = require("node:test");
const assert = require("node:assert/strict");
const { normalizeSelection, ticks, toFrames, OUT_CONVENTION } = require("../uxp/cutdeck/timelineRange.js");

// Premiere's tick grid divides every broadcast rate exactly; that is why it exists.
const TPS = 254016000000n;
const TPF_2997 = 8475667200n;   // 30000/1001
const TPF_23976 = 10594584000n; // 24000/1001
const TPF_25 = 10160640000n;    // 25

const select = (inFrames, outFrames, tpf = TPF_2997, extra = {}) => normalizeSelection({
  inTicks: (BigInt(inFrames) * tpf).toString(),
  outTicks: (BigInt(outFrames) * tpf).toString(),
  ticksPerFrame: tpf.toString(), outConvention: "exclusive", ...extra });

const frames = (tickValue, tpf = TPF_2997) => toFrames(tickValue, tpf);

test("the tick grid divides the broadcast rates this project actually uses", () => {
  assert.equal(TPS * 1001n / 30000n, TPF_2997);
  assert.equal(TPS * 1001n / 24000n, TPF_23976);
  assert.equal(TPS / 25n, TPF_25);
  assert.equal(TPS % 25n, 0n);
});

test("no range can be normalized until the Out-point convention is verified", () => {
  assert.equal(OUT_CONVENTION, null, "a verified convention must come from the Phase 0 probe, not a guess");
  assert.throws(() => normalizeSelection({ inTicks: "0", outTicks: "100", ticksPerFrame: "10" }),
    /convention has not been verified/);
  assert.throws(() => normalizeSelection({ inTicks: "0", outTicks: "100", ticksPerFrame: "10", outConvention: "maybe" }),
    /convention has not been verified/);
});

test("the two conventions differ by exactly one frame and nothing else", () => {
  const common = { inTicks: "0", outTicks: (10n * TPF_2997).toString(), ticksPerFrame: TPF_2997.toString() };
  const exclusive = normalizeSelection({ ...common, outConvention: "exclusive" });
  const inclusive = normalizeSelection({ ...common, outConvention: "inclusive" });
  assert.equal(exclusive.frames, 10n);
  assert.equal(inclusive.frames, 11n);
  assert.equal(inclusive.outExclusiveTicks - exclusive.outExclusiveTicks, TPF_2997);
});

test("a one-frame range at 29.97 is one frame", () => {
  const selection = select(100, 101);
  assert.equal(selection.frames, 1n);
});

test("23.976 and 25 produce exact frame counts with no rounding", () => {
  for (const [tpf, label] of [[TPF_23976, "23.976"], [TPF_25, "25"]]) {
    const selection = select(1000, 1013, tpf);
    assert.equal(selection.frames, 13n, label);
    assert.equal(toFrames(selection.inTicks, tpf), 1000n, label);
    assert.equal(toFrames(selection.outExclusiveTicks, tpf), 1013n, label);
  }
});

test("tick values past Number precision stay exact", () => {
  const start = 1300000n;  // ~12 hours at 29.97
  assert.ok(start * TPF_2997 > BigInt(Number.MAX_SAFE_INTEGER), "the fixture must actually exceed 2^53");
  const selection = select(start, start + 1n);
  assert.equal(selection.frames, 1n);
  assert.equal(frames(selection.inTicks), start);
  assert.equal(frames(selection.outExclusiveTicks), start + 1n);
});

/* Records what Number actually does at this scale, so the BigInt rule is kept for
   its real reason and not argued away by someone who measures the easy case. */
test("Number survives frame-aligned ticks but not off-grid ones", () => {
  const aligned = 1300000n * TPF_2997;
  assert.ok(aligned > BigInt(Number.MAX_SAFE_INTEGER));
  assert.equal(BigInt(Number(aligned)), aligned, "frame-aligned values carry a 2^8 factor and survive");
  assert.notEqual(BigInt(Number(aligned + 1n)), aligned + 1n, "an off-grid tick collapses onto its neighbour");
  assert.equal(BigInt(Number(aligned + 1n)), aligned);
});

test("unusable marks are rejected with a message the editor can act on", () => {
  const base = { ticksPerFrame: TPF_2997.toString(), outConvention: "exclusive" };
  assert.throws(() => normalizeSelection({ ...base, inTicks: null, outTicks: "100" }), /Mark In and Out/);
  assert.throws(() => normalizeSelection({ ...base, inTicks: "100", outTicks: undefined }), /Mark In and Out/);
  assert.throws(() => normalizeSelection({ ...base, inTicks: "200", outTicks: "100" }), /not after the In point/);
  assert.throws(() => normalizeSelection({ ...base, inTicks: "100", outTicks: "100" }), /not after the In point/);
  assert.throws(() => normalizeSelection({ ...base, inTicks: "-1", outTicks: "100" }), /before the start/);
  assert.throws(() => normalizeSelection({ ...base, inTicks: "0",
    outTicks: (10n * TPF_2997).toString(), endTicks: (5n * TPF_2997).toString() }), /past the end/);
  assert.throws(() => normalizeSelection({ ...base, inTicks: "0", outTicks: "1" }),
    /not a whole number of frames/, "a mark off the frame grid means something upstream rounded");
});

test("inexact tick values are refused rather than silently coerced", () => {
  assert.throws(() => ticks(1.5, "In point"), /not a whole number of ticks/);
  assert.throws(() => ticks(Number.MAX_SAFE_INTEGER + 2, "In point"), /exceeds exact Number range/);
  assert.throws(() => ticks("12.0", "In point"), /not an exact tick value/);
  assert.throws(() => ticks(null, "In point"), /not an exact tick value/);
  assert.equal(ticks("  42  "), 42n);
  assert.equal(ticks(42), 42n);
  assert.equal(ticks(42n), 42n);
});

/* ---- Phase 0 probe 1: orchestration only. Host mocks cannot establish Premiere's
   real behavior (handoff section 10) — they establish that the probe reports it
   instead of dying on it. ---- */
const { probeMarksAndTiming, formatReport, identifyRate } = require("../uxp/cutdeck/capabilityProbe.js");

const answer = (report, id) => (report.findings.find((f) => f.id === id) || {}).answer;
const evidence = (report, id) => (report.findings.find((f) => f.id === id) || {}).evidence || {};

function host(sequence, overrides = {}) {
  return { Project: { getActiveProject: async () => ({
    getActiveSequence: async () => sequence, ...overrides }) } };
}
const sequenceMock = (opts = {}) => ({
  name: opts.name || "Interview",
  getTimebase: async () => (opts.timebase === undefined ? TPF_2997.toString() : opts.timebase),
  getInPoint: async () => opts.in,
  getOutPoint: async () => opts.out,
  getEndTime: async () => ({ ticks: (100000n * TPF_2997).toString(), seconds: 3336 }),
  ...(opts.extra || {}) });

const tick = (frames) => ({ ticks: (BigInt(frames) * TPF_2997).toString(), seconds: Number(frames) / 29.97 });

test("the probe identifies every frame rate this project has met", () => {
  assert.equal(identifyRate(TPF_2997), "29.97");
  assert.equal(identifyRate(TPF_23976), "23.976");
  assert.equal(identifyRate(TPF_25), "25");
  assert.equal(identifyRate(4237833600n), "59.94");
  assert.equal(identifyRate(12345n), null);
});

test("an exclusive host: one frame apart reads as exclusive and normalizes to 1 frame", async () => {
  const report = await probeMarksAndTiming(host(sequenceMock({ in: tick(100), out: tick(101) })));
  assert.equal(report.complete, true);
  assert.equal(answer(report, "bigint"), "yes");
  assert.equal(answer(report, "timebase"), TPF_2997.toString());
  assert.equal(evidence(report, "timebase").matchesKnownRate, "29.97");
  assert.match(report.verdict, /exclusive/);
  assert.equal(evidence(report, "outConvention").durationIfExclusive, "1 frame");
  assert.equal(evidence(report, "outConvention").durationIfInclusive, "2 frames");
  // The evidence is produced by the real production path, not restated.
  assert.equal(evidence(report, "outConvention").exclusiveNormalizes.frames, "1");
  assert.equal(evidence(report, "outConvention").inclusiveNormalizes.frames, "2");
});

test("an inclusive host: identical marks read as inclusive", async () => {
  const report = await probeMarksAndTiming(host(sequenceMock({ in: tick(100), out: tick(100) })));
  assert.equal(report.verdict, "inclusive");
  assert.match(evidence(report, "outConvention").why, /last INCLUDED frame/);
});

test("a wide range gives no verdict but hands the editor a decisive comparison", async () => {
  const report = await probeMarksAndTiming(host(sequenceMock({ in: tick(100), out: tick(400) })));
  assert.equal(report.verdict, null);
  assert.equal(evidence(report, "outConvention").durationIfExclusive, "300 frames");
  assert.equal(evidence(report, "outConvention").durationIfInclusive, "301 frames");
  assert.match(evidence(report, "outConvention").how, /Program Monitor/);
});

test("unset marks are recorded as the answer, not treated as a crash", async () => {
  const report = await probeMarksAndTiming(host(sequenceMock({ in: null, out: null })));
  assert.equal(report.complete, true);
  assert.equal(answer(report, "marks"), "at least one is absent");
  assert.equal(evidence(report, "marks").in.present, false);
  assert.equal(answer(report, "outConvention"), "could not test");
  assert.equal(report.verdict, null);
});

test("a build whose mark calls throw still reports the timebase it did get", async () => {
  const report = await probeMarksAndTiming(host(sequenceMock({
    in: tick(1), out: tick(2),
    extra: { getInPoint: async () => { throw new Error("not a function"); } } })));
  assert.equal(report.complete, true);
  assert.equal(answer(report, "timebase"), TPF_2997.toString());
  assert.deepEqual(evidence(report, "marks").inCall.at, "getInPoint");
  assert.equal(report.verdict, null);
});

test("a timebase that is not an exact integer is called out rather than used", async () => {
  const report = await probeMarksAndTiming(host(sequenceMock({ timebase: "8475667200.5", in: tick(1), out: tick(2) })));
  assert.equal(answer(report, "timebase"), "not an exact integer");
  assert.equal(answer(report, "outConvention"), "could not test");
});

test("a timebase off the broadcast grid is flagged, not quietly accepted", async () => {
  const report = await probeMarksAndTiming(host(sequenceMock({ timebase: "12345", in: tick(1), out: tick(2) })));
  assert.equal(evidence(report, "timebase").matchesKnownRate, null);
  assert.match(evidence(report, "timebase").note, /does NOT match any broadcast rate/);
});

test("no host, no project and no sequence each stop cleanly with a finding", async () => {
  for (const [subject, id] of [
    [{}, "host"],
    [{ Project: { getActiveProject: async () => null } }, "project"],
    [host(null), "sequence"]]) {
    const report = await probeMarksAndTiming(subject);
    assert.equal(report.complete, false, id);
    assert.equal(answer(report, id), "no", id);
    assert.equal(report.verdict, null, id);
    assert.equal(answer(report, "bigint"), "yes", "the runtime check runs before any host call");
  }
});

test("every report formats to something an editor can read and paste back", async () => {
  for (const sequence of [sequenceMock({ in: tick(100), out: tick(101) }), sequenceMock({ in: null, out: null })]) {
    const text = formatReport(await probeMarksAndTiming(host(sequence)));
    assert.match(text, /Phase 0 probe 1/);
    assert.ok(text.split("\n").length > 5);
  }
  assert.match(formatReport(await probeMarksAndTiming({})), /stopped early/);
});

test("reports serialize to JSON — the panel logs them, and BigInt would throw", async () => {
  for (const sequence of [
    sequenceMock({ in: tick(100), out: tick(101) }),
    sequenceMock({ in: tick(100), out: tick(400) }),
    sequenceMock({ in: null, out: null }),
    sequenceMock({ timebase: "12345", in: tick(1), out: tick(2) })]) {
    const report = await probeMarksAndTiming(host(sequence));
    const text = JSON.stringify(report);
    assert.ok(text.length > 0);
    assert.deepEqual(JSON.parse(text).probe, "marks-and-timing");
  }
});
