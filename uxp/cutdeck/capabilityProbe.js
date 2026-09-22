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

/* Phase 2 probe: reads the ACTUAL Motion component (Scale, Position, Anchor Point, ...) of
   every Adjustment Layer sitting on the current sequence's timeline, right now. Ground truth
   for the "does the AL actually scale to a differently-shaped sequence" question —
   createSetScaleToFrameSizeAction() cannot be verified by re-reading a flag (ClipProjectItem
   has no such getter — confirmed against the official class reference), so the only way to
   know what Premiere actually did is to read the live effect values it produced. Read-only,
   creates/inserts/deletes nothing. */
async function probeAdjustmentLayerMotion(ppro) {
  const findings = [];
  const add = (...args) => { findings.push(finding(...args)); return findings[findings.length - 1]; };

  if (!ppro || !ppro.Project) {
    add("host", "Is the Premiere API reachable?", "no", { detail: "require('premierepro') gave no Project" });
    return { probe: "adjustment-layer-motion", complete: false, findings };
  }
  const projectRead = await attempt("getActiveProject", () => ppro.Project.getActiveProject());
  if (!projectRead.ok || !projectRead.value) {
    add("project", "Is a project open?", "no", projectRead.ok ? { detail: "no active project" } : projectRead);
    return { probe: "adjustment-layer-motion", complete: false, findings };
  }
  const project = projectRead.value;
  const sequenceRead = await attempt("getActiveSequence", () => project.getActiveSequence());
  if (!sequenceRead.ok || !sequenceRead.value) {
    add("sequence", "Is a sequence open?", "no", sequenceRead.ok ? { detail: "no active sequence" } : sequenceRead);
    return { probe: "adjustment-layer-motion", complete: false, findings };
  }
  const seq = sequenceRead.value;

  // SequenceSettings has no plain videoFrameWidth/videoFrameHeight fields (confirmed
  // against the official class reference — this was the same wrong-field-name mistake as
  // BinProjectItem/FolderItem) — it's getVideoFrameRect(): RectF, and RectF is the plain
  // {width, height} struct.
  const settingsRead = await attempt("getSettings", () =>
    (typeof seq.getSettings === "function" ? seq.getSettings() : null));
  const rectRead = settingsRead.ok && settingsRead.value && typeof settingsRead.value.getVideoFrameRect === "function"
    ? await attempt("getVideoFrameRect", () => settingsRead.value.getVideoFrameRect())
    : { ok: false };
  const dims = rectRead.ok && rectRead.value && rectRead.value.width
    ? { width: rectRead.value.width, height: rectRead.value.height }
    : null;
  add("sequence", "What does this sequence report as its frame size?",
    dims ? `${dims.width}x${dims.height}` : "could not read",
    { name: seq.name || "(unnamed)", settingsCall: settingsRead.ok ? "ok" : settingsRead });

  // Find every Adjustment Layer clip sitting on THIS sequence's timeline right now.
  const found = [];
  try {
    const vCount = await seq.getVideoTrackCount();
    for (let v = 0; v < vCount; v++) {
      const track = await seq.getVideoTrack(v);
      if (!track || typeof track.getTrackItems !== "function") continue;
      const clipType = ppro.Constants && ppro.Constants.TrackItemType ? ppro.Constants.TrackItemType.CLIP : undefined;
      const items = await track.getTrackItems(clipType, false);
      for (const it of (items || [])) {
        let isAL = false;
        if (typeof it.isAdjustmentLayer === "function") {
          try { isAL = await it.isAdjustmentLayer(); } catch (_) { isAL = false; }
        }
        if (isAL) found.push({ item: it, track: v + 1 });
      }
    }
  } catch (error) {
    add("scan", "Could this sequence's video tracks be scanned?", "no", { error: error.message || String(error) });
  }

  add("found", "How many Adjustment Layer clips are on this sequence's timeline right now?", String(found.length),
    { items: found.map((f) => `V${f.track}: "${f.item.name || "?"}"`) });

  for (const { item, track } of found) {
    const label = `V${track} "${item.name || "?"}"`;

    const mediaType = ppro.Constants && ppro.Constants.MediaType ? ppro.Constants.MediaType.VIDEO : undefined;
    const chainRead = await attempt(`getComponentChain(${label})`, () =>
      (typeof item.getComponentChain === "function" ? item.getComponentChain(mediaType) : null));
    if (!chainRead.ok || !chainRead.value) {
      add("chain", `Does ${label} expose a video component chain?`, "no",
        chainRead.ok ? { detail: "null chain" } : chainRead);
      continue;
    }
    const chain = chainRead.value;
    const countRead = await attempt(`getComponentCount(${label})`, () => chain.getComponentCount());
    const count = countRead.ok ? countRead.value : 0;

    const components = [];
    let motion = null;
    for (let i = 0; i < count; i++) {
      const compRead = await attempt(`getComponentAtIndex(${i})`, () => chain.getComponentAtIndex(i));
      if (!compRead.ok || !compRead.value) continue;
      const c = compRead.value;
      const displayName = (await attempt("getDisplayName", () => c.getDisplayName())).value || null;
      const matchName = (await attempt("getMatchName", () => c.getMatchName())).value || null;
      components.push({ displayName, matchName });
      if (!motion && ((displayName || "").toLowerCase() === "motion" || (matchName || "").toLowerCase().indexOf("motion") !== -1)) {
        motion = c;
      }
    }
    add("components", `What components does ${label} have?`,
      components.map((c) => c.displayName || c.matchName || "?").join(", ") || "(none read)", { components });

    if (!motion) {
      add("motion", `Does ${label} have a Motion component?`, "not found", null);
      continue;
    }

    const startRead = await attempt("getStartTime", () =>
      (typeof item.getStartTime === "function" ? item.getStartTime() : null));
    const paramCountRead = await attempt("getParamCount", () => motion.getParamCount());
    const paramCount = paramCountRead.ok ? paramCountRead.value : 0;

    const params = [];
    for (let i = 0; i < paramCount; i++) {
      const paramRead = await attempt(`getParam(${i})`, () => motion.getParam(i));
      if (!paramRead.ok || !paramRead.value) continue;
      const p = paramRead.value;
      const name = p.displayName || `param[${i}]`;
      let value = null;
      if (startRead.ok && startRead.value && typeof p.getValueAtTime === "function") {
        const valRead = await attempt(`getValueAtTime(${name})`, () => p.getValueAtTime(startRead.value));
        value = valRead.ok ? valRead.value : `error: ${valRead.error}`;
      }
      params.push({ name, value });
    }
    add("motionParams", `What are ${label}'s Motion parameters right now?`,
      params.map((p) => `${p.name}=${JSON.stringify(p.value)}`).join(", ") || "(none read)", { params });
  }

  return { probe: "adjustment-layer-motion", complete: true, findings, sequenceDims: dims };
}

function formatMotionReport(report) {
  const lines = [`Adjustment Layer / Motion probe (${report.complete ? "complete" : "stopped early"})`];
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
  return lines.join("\n");
}

module.exports = {
  probeMarksAndTiming, formatReport, identifyRate, KNOWN_RATES,
  probeAdjustmentLayerMotion, formatMotionReport,
};
