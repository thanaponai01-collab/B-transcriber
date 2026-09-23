const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");

const { normalizeSelection, ticks, toFrames, serialize, OUT_CONVENTION, OUT_CONVENTIONS } = require("../uxp/cutdeck/timelineRange.js");
const { probeMarksAndTiming, formatReport, identifyRate } = require("../uxp/cutdeck/capabilityProbe.js");

// Standard broadcast ticks-per-frame constants
const TPS = 254016000000n;
const TPF_2997 = 8475667200n;
const TPF_23976 = 10594584000n;
const TPF_25 = 10160640000n;
const TPF_5994 = 4237833600n;

// --- Phase 3: Adversarial Attack Suite for Issue #57 Correctness Gate ---

// 1. Dead Code Isolation Invariants
test("ATTACK [dead-code]: assemblyPlan.js is physically unresolvable and cannot be required", () => {
  assert.throws(
    () => require("../uxp/cutdeck/assemblyPlan.js"),
    (err) => err.code === "MODULE_NOT_FOUND",
    "assemblyPlan.js must be completely removed from filesystem"
  );
});

test("ATTACK [dead-code]: assembleProbe.js is physically unresolvable and cannot be required", () => {
  assert.throws(
    () => require("../uxp/cutdeck/assembleProbe.js"),
    (err) => err.code === "MODULE_NOT_FOUND",
    "assembleProbe.js must not exist in uxp/cutdeck"
  );
});

test("ATTACK [dead-code]: no production file or test imports assemblyPlan or planAppend", () => {
  const root = path.join(__dirname, "..");
  const scanDirs = [path.join(root, "uxp"), path.join(root, "tests")];

  function scan(dir) {
    const results = [];
    for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
      if (ent.name === "node_modules" || ent.name === "package") continue;
      const full = path.join(dir, ent.name);
      if (ent.isDirectory()) results.push(...scan(full));
      else if (ent.name.endsWith(".js") || ent.name.endsWith(".cjs") || ent.name.endsWith(".html")) {
        const content = fs.readFileSync(full, "utf8");
        // Exclude this gate test itself from self-matching literal strings
        if (ent.name === "cutdeck_gate_issue57.test.cjs") continue;
        if (/assemblyPlan|planAppend/i.test(content)) {
          results.push(`${path.relative(root, full)}: matched assemblyPlan/planAppend`);
        }
      }
    }
    return results;
  }

  const matches = scanDirs.flatMap(scan);
  assert.deepEqual(matches, [], `Forbidden dead references found: ${matches.join(", ")}`);
});

// 2. Hostile & Edge Timing Attacks on normalizeSelection & ticks
test("ATTACK [timing-edge]: unverified convention rejects regardless of casing, type or whitespace", () => {
  const base = { inTicks: "0", outTicks: TPF_2997.toString(), ticksPerFrame: TPF_2997.toString() };
  for (const badConv of [null, undefined, "", "EXCLUSIVE", "exclusive ", " inclusive", "true", 1, {}, []]) {
    assert.throws(
      () => normalizeSelection({ ...base, outConvention: badConv }),
      /convention has not been verified/,
      `Convention ${JSON.stringify(badConv)} must be rejected`
    );
  }
});

test("ATTACK [timing-edge]: non-integer, float, or invalid strings throw strict validation errors", () => {
  const base = { ticksPerFrame: TPF_2997.toString(), outConvention: "exclusive" };

  for (const badVal of ["12.5", "abc", "0x10", "NaN", "Infinity", "1e5", "", "   "]) {
    assert.throws(
      () => normalizeSelection({ ...base, inTicks: badVal, outTicks: TPF_2997.toString() }),
      /not an exact tick value/,
      `inTicks=${JSON.stringify(badVal)} must throw exact tick value error`
    );
    assert.throws(
      () => normalizeSelection({ ...base, inTicks: "0", outTicks: badVal }),
      /not an exact tick value/,
      `outTicks=${JSON.stringify(badVal)} must throw exact tick value error`
    );
  }
});

test("ATTACK [timing-edge]: negative, zero, or non-positive sequence timebase is refused", () => {
  const base = { inTicks: "0", outTicks: "100", outConvention: "exclusive" };

  assert.throws(() => normalizeSelection({ ...base, ticksPerFrame: "0" }), /positive tick count/);
  assert.throws(() => normalizeSelection({ ...base, ticksPerFrame: "-8475667200" }), /positive tick count/);
  assert.throws(() => toFrames(100n, 0n), /positive tick count/);
  assert.throws(() => toFrames(100n, -100n), /positive tick count/);
});

test("ATTACK [timing-edge]: negative In point is strictly refused", () => {
  const base = { outTicks: (10n * TPF_2997).toString(), ticksPerFrame: TPF_2997.toString(), outConvention: "exclusive" };

  assert.throws(() => normalizeSelection({ ...base, inTicks: "-1" }), /before the start of the sequence/);
  assert.throws(() => normalizeSelection({ ...base, inTicks: -8475667200n }), /before the start of the sequence/);
});

test("ATTACK [timing-edge]: inverted and zero-length ranges are rejected", () => {
  const base = { ticksPerFrame: TPF_2997.toString(), outConvention: "exclusive" };

  // Zero length: In == Out
  assert.throws(
    () => normalizeSelection({ ...base, inTicks: (10n * TPF_2997).toString(), outTicks: (10n * TPF_2997).toString() }),
    /Out point is not after the In point/
  );

  // Inverted: In > Out
  assert.throws(
    () => normalizeSelection({ ...base, inTicks: (20n * TPF_2997).toString(), outTicks: (10n * TPF_2997).toString() }),
    /Out point is not after the In point/
  );
});

test("ATTACK [timing-edge]: out of bounds against sequence end is caught", () => {
  const base = {
    inTicks: "0",
    outTicks: (100n * TPF_2997).toString(),
    endTicks: (99n * TPF_2997).toString(),
    ticksPerFrame: TPF_2997.toString(),
    outConvention: "exclusive",
  };

  assert.throws(() => normalizeSelection(base), /past the end of the sequence/);

  // Exactly at sequence end is valid
  const exact = normalizeSelection({ ...base, endTicks: (100n * TPF_2997).toString() });
  assert.equal(exact.frames, 100n);
});

test("ATTACK [timing-edge]: off-grid marks reject without silent rounding", () => {
  const base = { ticksPerFrame: TPF_2997.toString(), outConvention: "exclusive" };

  // 1 tick off-grid on inTicks
  assert.throws(
    () => normalizeSelection({ ...base, inTicks: "1", outTicks: (10n * TPF_2997).toString() }),
    /not a whole number of frames/
  );

  // 1 tick off-grid on outTicks
  assert.throws(
    () => normalizeSelection({ ...base, inTicks: "0", outTicks: (10n * TPF_2997 + 1n).toString() }),
    /not a whole number of frames/
  );
});

// 3. Mathematical Invariants and Property Tests
test("PROPERTY: exact additive partition holds for any split point", () => {
  const tpf = TPF_2997;
  const inFrames = 50n;
  const splitFrames = 120n;
  const outFrames = 250n;

  const total = normalizeSelection({
    inTicks: (inFrames * tpf).toString(),
    outTicks: (outFrames * tpf).toString(),
    ticksPerFrame: tpf.toString(),
    outConvention: "exclusive",
  });

  const part1 = normalizeSelection({
    inTicks: (inFrames * tpf).toString(),
    outTicks: (splitFrames * tpf).toString(),
    ticksPerFrame: tpf.toString(),
    outConvention: "exclusive",
  });

  const part2 = normalizeSelection({
    inTicks: (splitFrames * tpf).toString(),
    outTicks: (outFrames * tpf).toString(),
    ticksPerFrame: tpf.toString(),
    outConvention: "exclusive",
  });

  assert.equal(part1.frames + part2.frames, total.frames);
  assert.equal(part1.durationTicks + part2.durationTicks, total.durationTicks);
  assert.equal(part1.outExclusiveTicks, part2.inTicks);
});

test("PROPERTY: inclusive vs exclusive is consistently off-by-one frame across all frame rates", () => {
  const rates = [
    { tpf: TPF_2997, label: "29.97" },
    { tpf: TPF_23976, label: "23.976" },
    { tpf: TPF_25, label: "25" },
    { tpf: TPF_5994, label: "59.94" },
  ];

  for (const { tpf, label } of rates) {
    const common = {
      inTicks: (100n * tpf).toString(),
      outTicks: (150n * tpf).toString(),
      ticksPerFrame: tpf.toString(),
    };

    const excl = normalizeSelection({ ...common, outConvention: "exclusive" });
    const incl = normalizeSelection({ ...common, outConvention: "inclusive" });

    assert.equal(incl.frames - excl.frames, 1n, `Frame difference on ${label}`);
    assert.equal(incl.durationTicks - excl.durationTicks, tpf, `Duration tick difference on ${label}`);
    assert.equal(incl.outExclusiveTicks - excl.outExclusiveTicks, tpf, `Exclusive out diff on ${label}`);
  }
});

test("PROPERTY: deep scale invariance: arithmetic at 100 hours matches arithmetic at 0 hours", () => {
  const tpf = TPF_2997;
  const hundredHoursFrames = 100n * 3600n * 30n; // ~10,800,000 frames
  const spanFrames = 1500n;

  const lowRange = normalizeSelection({
    inTicks: "0",
    outTicks: (spanFrames * tpf).toString(),
    ticksPerFrame: tpf.toString(),
    outConvention: "exclusive",
  });

  const highRange = normalizeSelection({
    inTicks: (hundredHoursFrames * tpf).toString(),
    outTicks: ((hundredHoursFrames + spanFrames) * tpf).toString(),
    ticksPerFrame: tpf.toString(),
    outConvention: "exclusive",
  });

  assert.equal(lowRange.frames, highRange.frames);
  assert.equal(lowRange.durationTicks, highRange.durationTicks);
  assert.ok(highRange.inTicks > BigInt(Number.MAX_SAFE_INTEGER), "must genuinely exceed 2^53");
});

// 4. Adversarial Host Mocks against Capability Probe Marks & Timing
test("ATTACK [probe]: probe survives crashing sequence getters and reports clean findings", async () => {
  const hostileHost = {
    Project: {
      getActiveProject: async () => ({
        getActiveSequence: async () => ({
          name: "HostileSeq",
          getTimebase: async () => { throw new Error("Timebase API corrupt"); },
          getInPoint: async () => { throw new Error("InPoint crashed"); },
          getOutPoint: async () => null,
          getEndTime: async () => ({ ticks: "0", seconds: 0 }),
        }),
      }),
    },
  };

  const report = await probeMarksAndTiming(hostileHost);
  assert.equal(report.complete, true);
  assert.equal(report.verdict, null);
  const timebaseFinding = report.findings.find((f) => f.id === "timebase");
  assert.match(timebaseFinding.evidence.error, /Timebase API corrupt/);
  assert.equal(timebaseFinding.answer, "call failed");

  const formatted = formatReport(report);
  assert.match(formatted, /Phase 0 probe 1/);
  assert.doesNotMatch(formatted, /undefined|\[object Object\]/);
});
