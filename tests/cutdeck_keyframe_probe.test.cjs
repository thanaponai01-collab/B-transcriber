/* The keyframe timing probe (capabilityProbe.js probeKeyframeTiming) gates animated presets.
   What is provable off-host: given a host that reports keyframes in reading X, the probe names
   X — and never names anything when the clip can't distinguish the readings. What real
   Premiere reports is the point of running it, and is not provable here. */
const test = require("node:test");
const assert = require("node:assert/strict");

const capability = require("../uxp/cutdeck/capabilityProbe.js");
const { classifyKeyframeReference, probeKeyframeTiming, formatKeyframeReport } = capability;

const TPF = 10160640000n; // 25 fps
const f = (n) => BigInt(n) * TPF;
const tick = (n) => ({ ticks: f(n).toString() });

test("classifier names each reading when the clip separates all three", () => {
  const base = { playheadTicks: f(120), startTicks: f(100), inPointTicks: f(50) };
  assert.equal(classifyKeyframeReference({ ...base, keyframeTicks: [f(120)] }).verdict, "sequence");
  assert.equal(classifyKeyframeReference({ ...base, keyframeTicks: [f(20)] }).verdict, "clip");
  assert.equal(classifyKeyframeReference({ ...base, keyframeTicks: [f(70)] }).verdict, "media");
  const none = classifyKeyframeReference({ ...base, keyframeTicks: [f(3)] });
  assert.deepEqual(none.matches, []);
  assert.equal(none.verdict, null);
});

test("classifier refuses a verdict when readings coincide (clip at 0:00, or untrimmed head)", () => {
  const atZero = classifyKeyframeReference({ keyframeTicks: [f(20)], playheadTicks: f(20), startTicks: 0n, inPointTicks: f(50) });
  assert.equal(atZero.ambiguous, true);
  assert.equal(atZero.verdict, null);
  const untrimmed = classifyKeyframeReference({ keyframeTicks: [f(20)], playheadTicks: f(120), startTicks: f(100), inPointTicks: 0n });
  assert.equal(untrimmed.ambiguous, true);
  assert.equal(untrimmed.verdict, null);
});

// --- fake host: one clip at 100f on the timeline, trimmed 50f into its media, playhead at 120f.
function fakeHost({ keyframeFrames, selected = 1, listThrows = false }) {
  const param = {
    displayName: "Scale",
    isTimeVarying: () => true,
    getKeyframeListAsTickTimes: () => {
      if (listThrows) throw new Error("not implemented");
      return keyframeFrames.map(tick);
    },
    getKeyframePtr: (t) => ({
      position: t,
      value: { value: 100 },
      getTemporalInterpolationMode: () => Promise.resolve(2),
    }),
    createSetInterpolationAtKeyframeAction: () => ({}),
  };
  const item = {
    name: "interview_A",
    getStartTime: () => Promise.resolve(tick(100)),
    getEndTime: () => Promise.resolve(tick(200)),
    getInPoint: () => Promise.resolve(tick(50)),
    getComponentChain: () => Promise.resolve({
      getComponentCount: () => 1,
      getComponentAtIndex: () => ({
        getDisplayName: () => Promise.resolve("Motion"),
        getParamCount: () => 1,
        getParam: () => param,
      }),
    }),
  };
  const seq = {
    getSelection: () => Promise.resolve({ getTrackItems: () => Promise.resolve(Array(selected).fill(item)) }),
    getPlayerPosition: () => Promise.resolve(tick(120)),
  };
  return {
    Project: { getActiveProject: () => Promise.resolve({ getActiveSequence: () => Promise.resolve(seq) }) },
    Keyframe: { INTERPOLATION_MODE_LINEAR: 2, INTERPOLATION_MODE_BEZIER: 0 },
  };
}

for (const [reading, frames] of [["sequence", [120, 180]], ["clip", [20, 80]], ["media", [70, 130]]]) {
  test(`probe reports "${reading}" when the host stores keyframes ${reading}-relative`, async () => {
    const report = await probeKeyframeTiming(fakeHost({ keyframeFrames: frames }));
    assert.equal(report.complete, true);
    assert.equal(report.verdict, reading);
    assert.match(formatKeyframeReport(report), new RegExp(`VERDICT: keyframe times are ${reading}-relative`));
  });
}

test("probe records interpolation constants and per-keyframe modes verbatim", async () => {
  const report = await probeKeyframeTiming(fakeHost({ keyframeFrames: [20, 80] }));
  const constants = report.findings.find((x) => x.id === "interpolationConstants").evidence;
  assert.equal(constants["Keyframe.INTERPOLATION_MODE_*"].INTERPOLATION_MODE_BEZIER, 0);
  assert.equal(constants["Keyframe.INTERPOLATION_MODE_*"].INTERPOLATION_MODE_HOLD, null, "absent statics are recorded as null, not guessed");
  const animated = report.findings.find((x) => x.id === "animated").evidence.params[0];
  assert.equal(animated.keyframes[0].interpolationMode, 2);
  assert.equal(animated.hasSetInterpolationAction, true);
});

test("probe stops without a verdict unless exactly one clip is selected", async () => {
  for (const selected of [0, 2]) {
    const report = await probeKeyframeTiming(fakeHost({ keyframeFrames: [20], selected }));
    assert.equal(report.complete, false);
    assert.equal(report.verdict, null);
  }
});

test("a throwing keyframe list is a finding, not a crash", async () => {
  const report = await probeKeyframeTiming(fakeHost({ keyframeFrames: [], listThrows: true }));
  const animated = report.findings.find((x) => x.id === "animated");
  assert.equal(animated.evidence.params[0].listCall, "not implemented");
  assert.equal(report.verdict, null);
});

test("probe is read-only: it never calls a create*Action or executeTransaction", () => {
  const src = require("node:fs").readFileSync(require.resolve("../uxp/cutdeck/capabilityProbe.js"), "utf8");
  const body = src.slice(src.indexOf("async function probeKeyframeTiming"), src.indexOf("function formatKeyframeReport"));
  assert.doesNotMatch(body, /\.create\w*Action\(|executeTransaction|lockedAccess/);
});
