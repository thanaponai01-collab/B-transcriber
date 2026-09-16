/* Phase 0 probe 1 of docs/HANDOFF_CUTDECK_TIMELINE_IN_OUT.md: marks and timing.

   Read-only. It creates nothing, inserts nothing and deletes nothing, so it is safe
   to run in a real project — unlike probes 2-6, which mutate and belong in a
   disposable one. Its job is to answer, from the installed build rather than from
   Adobe's reference, the questions timelineRange.js currently refuses to guess:

     - is Sequence.getOutPoint() the last included frame, or the first excluded one?
     - what is the true ticks-per-frame value, and does it match a broadcast rate?
     - are marks absolute, or relative to a nonzero sequence start timecode?
     - does this UXP runtime have BigInt? (section 6 requires exact integer math)
     - what does an unset mark actually return?

   Nothing here throws at the caller. A missing method, a method that throws and a
   sequence with no marks are all findings — a probe that dies on the first
   surprise tells you less than the build it was probing. */

const { TICKS_PER_SECOND, ticks, toFrames, normalizeSelection } = require("./timelineRange.js");

/* Every rate this project has actually met, from issue #25's job table. */
const KNOWN_RATES = [
  ["23.976", 24000n, 1001n], ["24", 24000n, 1000n], ["25", 25000n, 1000n],
  ["29.97", 30000n, 1001n], ["30", 30000n, 1000n], ["50", 50000n, 1000n],
  ["59.94", 60000n, 1001n], ["60", 60000n, 1000n],
];

const identifyRate = (ticksPerFrame) => {
  for (const [label, num, den] of KNOWN_RATES) {
    if (TICKS_PER_SECOND * den / num === ticksPerFrame) return label;
  }
  return null;
};

/* Calls a host method and records the failure instead of propagating it, so one
   unsupported call cannot hide the answers the other calls would have given. */
async function attempt(label, fn) {
  try {
    const value = await fn();
    return { ok: true, value };
  } catch (error) {
    return { ok: false, error: (error && error.message) || String(error), at: label };
  }
}

const plural = (n) => `${n} frame${n === 1n ? "" : "s"}`;

const finding = (id, question, answer, evidence) => ({ id, question, answer, evidence: evidence || null });

/* Reads whatever a TickTime-like object will give up, without assuming a shape. */
function readTick(value) {
  if (value === null || value === undefined) return { present: false, ticks: null, seconds: null };
  const raw = value.ticks !== undefined ? value.ticks : value;
  let exact = null;
  try { exact = ticks(raw, "tick").toString(); } catch (_) { exact = null; }
  return { present: true, ticks: exact, raw: String(raw),
    seconds: typeof value.seconds === "number" ? value.seconds : null };
}

async function probeMarksAndTiming(ppro) {
  const findings = [];
  const add = (...args) => { findings.push(finding(...args)); return findings[findings.length - 1]; };

  // Section 6 asks for this explicitly before any of the tick math can be trusted.
  let bigintOk = false;
  try { bigintOk = typeof BigInt === "function" && BigInt("9007199254740993") + 1n === 9007199254740994n; }
  catch (_) { bigintOk = false; }
  add("bigint", "Does this UXP runtime support exact BigInt arithmetic?",
    bigintOk ? "yes" : "NO — the exact tick math in timelineRange.js cannot run here",
    { checked: "BigInt('9007199254740993') + 1n" });

  if (!ppro || !ppro.Project) {
    add("host", "Is the Premiere API reachable?", "no", { detail: "require('premierepro') gave no Project" });
    return { probe: "marks-and-timing", complete: false, findings, verdict: null };
  }

  const projectRead = await attempt("getActiveProject", () => ppro.Project.getActiveProject());
  if (!projectRead.ok || !projectRead.value) {
    add("project", "Is a project open?", "no", projectRead.ok ? { detail: "no active project" } : projectRead);
    return { probe: "marks-and-timing", complete: false, findings, verdict: null };
  }
  const sequenceRead = await attempt("getActiveSequence", () => projectRead.value.getActiveSequence());
  if (!sequenceRead.ok || !sequenceRead.value) {
    add("sequence", "Is a sequence open?", "no", sequenceRead.ok ? { detail: "no active sequence" } : sequenceRead);
    return { probe: "marks-and-timing", complete: false, findings, verdict: null };
  }
  const sequence = sequenceRead.value;
  add("sequence", "Is a sequence open?", "yes", { name: sequence.name || "(unnamed)" });

  // 1. Timebase. Everything downstream is expressed in this unit.
  const timebase = await attempt("getTimebase", () => sequence.getTimebase());
  let ticksPerFrame = null;
  if (!timebase.ok) {
    add("timebase", "What is the true ticks-per-frame value?", "call failed", timebase);
  } else {
    try {
      ticksPerFrame = ticks(timebase.value, "Sequence timebase");
      const rate = identifyRate(ticksPerFrame);
      add("timebase", "What is the true ticks-per-frame value?", ticksPerFrame.toString(),
        { returnedType: typeof timebase.value, matchesKnownRate: rate,
          ticksPerSecond: TICKS_PER_SECOND.toString(),
          note: rate ? `divides ${TICKS_PER_SECOND} exactly at ${rate} fps` : "does NOT match any broadcast rate exactly" });
    } catch (error) {
      add("timebase", "What is the true ticks-per-frame value?", "not an exact integer",
        { returned: String(timebase.value), error: error.message });
    }
  }

  // 2. The marks themselves, raw.
  const inRead = await attempt("getInPoint", () => sequence.getInPoint());
  const outRead = await attempt("getOutPoint", () => sequence.getOutPoint());
  const endRead = await attempt("getEndTime", () => sequence.getEndTime());
  const inMark = inRead.ok ? readTick(inRead.value) : null;
  const outMark = outRead.ok ? readTick(outRead.value) : null;
  const endMark = endRead.ok ? readTick(endRead.value) : null;

  add("marks", "What do getInPoint/getOutPoint return right now?",
    inMark && outMark && inMark.present && outMark.present ? "both present" : "at least one is absent",
    { in: inMark, out: outMark, end: endMark,
      inCall: inRead.ok ? "ok" : inRead, outCall: outRead.ok ? "ok" : outRead,
      note: "If no marks are set in Premiere, this line records what an UNSET mark looks like on this build — "
        + "null, zero, or the sequence bounds. That is probe 1's unset-mark question." });

  // 3. The decisive question: what does Out mean?
  let verdict = null;
  if (ticksPerFrame && inMark && outMark && inMark.ticks !== null && outMark.ticks !== null) {
    const delta = ticks(outMark.ticks) - ticks(inMark.ticks);
    let framesIfExclusive = null;
    try { framesIfExclusive = toFrames(delta, ticksPerFrame, "Mark delta").toString(); } catch (_) {}
    if (framesIfExclusive === null) {
      add("outConvention", "Is the Out point inclusive or exclusive?", "indeterminate",
        { deltaTicks: delta.toString(), ticksPerFrame: ticksPerFrame.toString(),
          why: "the marks are not a whole number of frames apart, so neither convention fits" });
    } else if (delta === 0n) {
      verdict = "inclusive";
      add("outConvention", "Is the Out point inclusive or exclusive?", "inclusive",
        { deltaTicks: "0", why: "In and Out report the same tick, so Out names the last INCLUDED frame" });
    } else {
      const exclusive = BigInt(framesIfExclusive);
      add("outConvention", "Is the Out point inclusive or exclusive?",
        delta === ticksPerFrame ? "exclusive if these marks are on the same frame" : "compare against Premiere",
        { deltaTicks: delta.toString(),
          durationIfExclusive: plural(exclusive), durationIfInclusive: plural(exclusive + 1n),
          how: "Read the marked duration Premiere itself shows in the Program Monitor. Whichever of these two "
             + "numbers it equals is this build's convention. Marking In and Out on the SAME frame is the "
             + "crispest test: 1 frame means exclusive, 0 frames means inclusive.",
          // Both readings, computed through the real production code path.
          exclusiveNormalizes: describeNormalize(inMark, outMark, endMark, ticksPerFrame, "exclusive"),
          inclusiveNormalizes: describeNormalize(inMark, outMark, endMark, ticksPerFrame, "inclusive") });
      if (delta === ticksPerFrame) verdict = "exclusive (if marked on one frame)";
    }
  } else {
    add("outConvention", "Is the Out point inclusive or exclusive?", "could not test",
      { why: "needs a timebase and both marks; set In and Out on the source timeline and run again" });
  }

  // 4. Are marks absolute, or offset by a nonzero sequence start timecode?
  const zeroRead = await attempt("getZeroPoint", () =>
    (typeof sequence.getZeroPoint === "function" ? sequence.getZeroPoint() : null));
  add("zeroPoint", "Do marks sit in the same coordinate space as track item times?",
    zeroRead.ok && zeroRead.value ? "sequence reports a start offset" : "no getZeroPoint on this build",
    { zeroPoint: zeroRead.ok ? readTick(zeroRead.value) : zeroRead,
      note: "A shared offset cancels out of every equation in section 6, because marks and track item times "
          + "are differenced against each other. It only matters for the destination's own append cursor." });

  return { probe: "marks-and-timing", complete: true, findings, verdict,
    ticksPerFrame: ticksPerFrame ? ticksPerFrame.toString() : null };
}

/* Runs the real normalizeSelection under one assumed convention and reports what it
   would produce — so the evidence is what production code does, not a restatement. */
function describeNormalize(inMark, outMark, endMark, ticksPerFrame, convention) {
  try {
    const selection = normalizeSelection({
      inTicks: inMark.ticks, outTicks: outMark.ticks,
      endTicks: endMark && endMark.ticks !== null ? endMark.ticks : null,
      ticksPerFrame: ticksPerFrame.toString(), outConvention: convention });
    return { frames: selection.frames.toString(), outExclusiveTicks: selection.outExclusive };
  } catch (error) {
    return { refused: (error && error.message) || String(error) };
  }
}

/* One human-readable block for the panel status line. */
function formatReport(report) {
  const lines = [`Phase 0 probe 1 — marks and timing (${report.complete ? "complete" : "stopped early"})`];
  for (const f of report.findings) {
    lines.push(`• ${f.question}`);
    lines.push(`    ${f.answer}`);
    if (f.evidence) {
      for (const [key, value] of Object.entries(f.evidence)) {
        if (value === null || value === undefined) continue;
        lines.push(`      ${key}: ${typeof value === "object" ? JSON.stringify(value) : value}`);
      }
    }
  }
  lines.push(report.verdict
    ? `VERDICT: Out point looks ${report.verdict}. Set OUT_CONVENTION in timelineRange.js only after confirming against Premiere's own duration display.`
    : `No verdict yet. Set In and Out on the source timeline — ideally on the same frame — and run again.`);
  return lines.join("\n");
}

module.exports = { probeMarksAndTiming, formatReport, identifyRate, KNOWN_RATES };
