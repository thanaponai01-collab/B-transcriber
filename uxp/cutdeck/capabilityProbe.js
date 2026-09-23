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

/* One human-readable block for the panel status line, shared by every probe in this file.
   The per-probe title and an optional trailing verdict line are all that ever differed
   between the formatters; extracted when a fourth probe would have meant a fourth copy. */
function formatFindings(title, report, trailer) {
  const lines = [`${title} (${report.complete ? "complete" : "stopped early"})`];
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
  if (trailer) lines.push(trailer);
  return lines.join("\n");
}

function formatReport(report) {
  return formatFindings("Phase 0 probe 1 — marks and timing", report, report.verdict
    ? `VERDICT: Out point looks ${report.verdict}. Set OUT_CONVENTION in timelineRange.js only after confirming against Premiere's own duration display.`
    : `No verdict yet. Set In and Out on the source timeline — ideally on the same frame — and run again.`);
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
  return formatFindings("Adjustment Layer / Motion probe", report);
}

/* Effects-chain probe (CutDeck "Apply Effect" job, see timeline/effects.js): dumps the real
   component chain of whatever's selected on the timeline right now — matchNames, display
   names, and param names — in index order. Read-only: creates/inserts/deletes nothing.

   Its job is to confirm, against THIS build, which components are Premiere's own fixed
   effects (Motion/Opacity/Time Remapping) by real matchName, before effects.js's capture
   logic (which currently skips by display-name guess — see FIXED_EFFECT_DISPLAY_NAMES) is
   trusted on a clip with real user-added effects. Run it against a plain, freshly-created
   Adjustment Layer with ZERO manually-added effects first — everything it reports there is,
   by definition, a fixed effect, not something a user built. */
async function probeEffectChain(ppro) {
  const findings = [];
  const add = (...args) => { findings.push(finding(...args)); return findings[findings.length - 1]; };

  if (!ppro || !ppro.Project) {
    add("host", "Is the Premiere API reachable?", "no", { detail: "require('premierepro') gave no Project" });
    return { probe: "effect-chain", complete: false, findings };
  }
  const projectRead = await attempt("getActiveProject", () => ppro.Project.getActiveProject());
  if (!projectRead.ok || !projectRead.value) {
    add("project", "Is a project open?", "no", projectRead.ok ? { detail: "no active project" } : projectRead);
    return { probe: "effect-chain", complete: false, findings };
  }
  const project = projectRead.value;
  const sequenceRead = await attempt("getActiveSequence", () => project.getActiveSequence());
  if (!sequenceRead.ok || !sequenceRead.value) {
    add("sequence", "Is a sequence open?", "no", sequenceRead.ok ? { detail: "no active sequence" } : sequenceRead);
    return { probe: "effect-chain", complete: false, findings };
  }
  const seq = sequenceRead.value;

  const selRead = await attempt("getSelection", () =>
    (typeof seq.getSelection === "function" ? seq.getSelection() : null));
  let items = [];
  if (selRead.ok && selRead.value) {
    if (typeof selRead.value.getTrackItems === "function") {
      const itemsRead = await attempt("getTrackItems", () => selRead.value.getTrackItems());
      items = itemsRead.ok && itemsRead.value ? itemsRead.value : [];
    } else if (Array.isArray(selRead.value)) {
      items = selRead.value;
    }
  }
  add("selection", "How many track items are selected right now?", String(items.length),
    { note: "Select exactly one item — ideally a freshly-created Adjustment Layer with no " +
        "effects added by hand — before running this probe." });

  if (items.length === 0) {
    return { probe: "effect-chain", complete: false, findings };
  }

  for (const item of items) {
    const label = item.name || "(unnamed)";
    const chainRead = await attempt(`getComponentChain(${label})`, () =>
      (typeof item.getComponentChain === "function" ? item.getComponentChain() : null));
    if (!chainRead.ok || !chainRead.value) {
      add("chain", `Does "${label}" expose a component chain?`, "no",
        chainRead.ok ? { detail: "null chain" } : chainRead);
      continue;
    }
    const chain = chainRead.value;
    const countRead = await attempt(`getComponentCount(${label})`, () => chain.getComponentCount());
    const count = countRead.ok ? countRead.value : 0;

    const components = [];
    for (let i = 0; i < count; i++) {
      const compRead = await attempt(`getComponentAtIndex(${i})`, () => chain.getComponentAtIndex(i));
      if (!compRead.ok || !compRead.value) continue;
      const c = compRead.value;
      const displayName = (await attempt("getDisplayName", () => c.getDisplayName())).value || null;
      const matchName = (await attempt("getMatchName", () => c.getMatchName())).value || null;
      const paramCountRead = await attempt("getParamCount", () => c.getParamCount());
      const paramCount = paramCountRead.ok ? paramCountRead.value : 0;
      const paramNames = [];
      for (let p = 0; p < paramCount; p++) {
        const paramRead = await attempt(`getParam(${p})`, () => c.getParam(p));
        if (paramRead.ok && paramRead.value) paramNames.push(paramRead.value.displayName || `param[${p}]`);
      }
      components.push({ index: i, displayName, matchName, paramCount, paramNames });
    }
    add("components", `What components does "${label}" have, in index order?`,
      components.map((c) => `[${c.index}] ${c.displayName} (${c.matchName})`).join(", ") || "(none read)",
      { components,
        why: "Entries here that you did NOT add by hand are Premiere's own fixed effects — " +
          "copy their real matchNames into timeline/effects.js's fixed-component skip list." });
  }

  return { probe: "effect-chain", complete: true, findings };
}

function formatEffectChainReport(report) {
  return formatFindings("Effect chain probe", report);
}

/* Phase 0 probe of docs/research/cutdeck-transform-panel-plan.md — the Transform & Align
   feature's blocking unknowns, asked of the installed build rather than of Adobe's reference.

   Adobe documents no parameter map. `@adobe/premierepro@26.2.1`'s declarations (the release
   line manifest.json pins) name exactly two match names anywhere, both as doc-comment
   examples: 'PR.ADBE Solarize' and 'AE.ADBE Mosaic'. Motion and Transform are never named,
   their param indices are never listed, and no page states whether Position and Anchor Point
   are in pixels or normalized units, or even whether they share a coordinate space. So every
   number the align math would eventually write has to be aimed by reading the real component
   first — the same "ask the build, don't guess" rule timelineRange.js's OUT_CONVENTION and
   effects.js's fixed-effect list were held to.

   Read-only: creates nothing, inserts nothing, deletes nothing. Safe in a real project.

   Four questions, in the order the plan's phases need them:

     1. What are Motion's and Transform's real match names and param indices HERE?
     2. What SHAPE do point params come back in? The raw JSON is recorded verbatim, not just
        the unwrapped value, because `{"value":[0.5,0.5]}` vs `{"value":{"x":960,"y":540}}` is
        the entire units question and decides whether the anchor-compensation formula in the
        plan's Phase 3 is even expressible. effects.js only ever saw this by accident, on one
        component, while doing something else.
     3. What does this sequence report as frame size and pixel aspect ratio? (PAR is typed
        `Promise<string>`, not a number — recorded raw, unparsed.)
     4. Does `Metadata.getProjectColumnsMetadata()` carry the SOURCE resolution? UXP exposes
        no source width/height on ProjectItem, ClipProjectItem or FootageInterpretation; this
        column dump is the one candidate route (plan Part 3) and Phase 5's frame alignment is
        blocked on the answer. ExtendScript's identically-named call is documented as
        returning the columns of "the current project view layout" — so this must be run with
        the Project panel's Video Info column both SHOWN and HIDDEN. If the answer differs,
        the route depends on a user-configurable panel setting and cannot be trusted silently.

   Run it against, separately: a clip whose source matches the sequence, a clip whose source
   does NOT, a clip with non-square pixels, an Adjustment Layer, and a graphic. */
const TRANSFORM_COMPONENT_HINTS = ["motion", "transform"];

function looksLikeTransformComponent(displayName, matchName) {
  const haystack = `${displayName || ""} ${matchName || ""}`.toLowerCase();
  return TRANSFORM_COMPONENT_HINTS.some((hint) => haystack.indexOf(hint) !== -1);
}

/* Records a param value the way the units question actually needs it: the unwrapped value
   AND the raw shape it arrived in. Adobe's own types declare the double wrapper
   (`Keyframe.value: { value: ... }`), so the unwrap is a contract, not a guess — but what
   sits INSIDE it for a point param is exactly what is undocumented. */
function describeParamValue(keyframe) {
  if (keyframe === null || keyframe === undefined) return { present: false };
  const raw = keyframe.value !== undefined ? keyframe.value : null;
  const unwrapped = (raw && typeof raw === "object" && !Array.isArray(raw) && "value" in raw)
    ? raw.value : raw;
  let rawJson = null;
  try { rawJson = JSON.stringify(raw); } catch (_) { rawJson = "(not JSON-serializable)"; }
  const shape = unwrapped === null || unwrapped === undefined ? "null"
    : Array.isArray(unwrapped) ? `array[${unwrapped.length}]`
    : typeof unwrapped === "object"
      ? `object{${Object.keys(unwrapped).sort().join(",")}}`
      : typeof unwrapped;
  return {
    present: true,
    rawJson,
    shape,
    // The two candidate point shapes, reported explicitly so neither has to be inferred
    // from the JSON by eye when this lands in a bug report.
    hasXY: !!(unwrapped && typeof unwrapped === "object" && "x" in unwrapped && "y" in unwrapped),
    unwrapped: unwrapped === undefined ? null : unwrapped,
  };
}

/* Question 4, isolated: dump the project-columns metadata for one track item's project item.
   Never throws — a build without Metadata, an item without a project item, and a call that
   rejects are all findings. */
async function readSourceDimensionCandidates(ppro, item) {
  if (!ppro || !ppro.Metadata || typeof ppro.Metadata.getProjectColumnsMetadata !== "function") {
    return { available: false, why: "this build exposes no Metadata.getProjectColumnsMetadata" };
  }
  if (!item || typeof item.getProjectItem !== "function") {
    return { available: false, why: "this track item exposes no getProjectItem" };
  }
  const projectItemRead = await attempt("getProjectItem", () => item.getProjectItem());
  if (!projectItemRead.ok || !projectItemRead.value) {
    return { available: false, why: "no project item", detail: projectItemRead.ok ? null : projectItemRead };
  }
  const dumpRead = await attempt("getProjectColumnsMetadata", () =>
    ppro.Metadata.getProjectColumnsMetadata(projectItemRead.value));
  if (!dumpRead.ok) return { available: false, why: "the call failed", detail: dumpRead };

  const rawText = typeof dumpRead.value === "string" ? dumpRead.value : String(dumpRead.value);
  let columns = null;
  try {
    const parsed = JSON.parse(rawText);
    if (Array.isArray(parsed)) columns = parsed;
    else if (parsed && Array.isArray(parsed.columns)) columns = parsed.columns;
  } catch (_) { columns = null; }

  // Anything that could plausibly carry "1920 x 1080". Deliberately broad: the point of the
  // probe is to find out what the column is really called on this build, not to confirm a
  // name guessed in advance.
  const RESOLUTION_HINT = /(video\s*info|resolution|frame\s*size|width|height|dimension)/i;
  const candidates = (columns || [])
    .filter((c) => c && (RESOLUTION_HINT.test(String(c.ColumnID || "")) ||
                         RESOLUTION_HINT.test(String(c.ColumnName || "")) ||
                         /\d{2,}\s*[x×]\s*\d{2,}/.test(String(c.ColumnValue || ""))))
    .map((c) => ({ ColumnID: c.ColumnID, ColumnName: c.ColumnName, ColumnValue: c.ColumnValue }));

  return {
    available: true,
    parsedAsJson: columns !== null,
    columnCount: columns ? columns.length : null,
    resolutionCandidates: candidates,
    // Truncated so one probe run cannot flood the status line; the console.log in main.js
    // carries the whole report as JSON either way.
    rawHead: rawText.slice(0, 600),
    rawLength: rawText.length,
  };
}

async function probeTransformParams(ppro) {
  const findings = [];
  const add = (...args) => { findings.push(finding(...args)); return findings[findings.length - 1]; };

  if (!ppro || !ppro.Project) {
    add("host", "Is the Premiere API reachable?", "no", { detail: "require('premierepro') gave no Project" });
    return { probe: "transform-params", complete: false, findings };
  }
  const projectRead = await attempt("getActiveProject", () => ppro.Project.getActiveProject());
  if (!projectRead.ok || !projectRead.value) {
    add("project", "Is a project open?", "no", projectRead.ok ? { detail: "no active project" } : projectRead);
    return { probe: "transform-params", complete: false, findings };
  }
  const sequenceRead = await attempt("getActiveSequence", () => projectRead.value.getActiveSequence());
  if (!sequenceRead.ok || !sequenceRead.value) {
    add("sequence", "Is a sequence open?", "no", sequenceRead.ok ? { detail: "no active sequence" } : sequenceRead);
    return { probe: "transform-params", complete: false, findings };
  }
  const seq = sequenceRead.value;

  // --- Question 3: the sequence's own geometry ------------------------------------------
  // Both documented routes are read, because they are separate calls on separate classes and
  // nothing promises they agree. If they ever disagree, the align math needs to know which
  // one Premiere itself renders against.
  const frameSizeRead = await attempt("getFrameSize", () =>
    (typeof seq.getFrameSize === "function" ? seq.getFrameSize() : null));
  const settingsRead = await attempt("getSettings", () =>
    (typeof seq.getSettings === "function" ? seq.getSettings() : null));
  const settings = settingsRead.ok ? settingsRead.value : null;
  const frameRectRead = settings && typeof settings.getVideoFrameRect === "function"
    ? await attempt("getVideoFrameRect", () => settings.getVideoFrameRect())
    : { ok: false, error: "no getVideoFrameRect on this build" };
  const parRead = settings && typeof settings.getVideoPixelAspectRatio === "function"
    ? await attempt("getVideoPixelAspectRatio", () => settings.getVideoPixelAspectRatio())
    : { ok: false, error: "no getVideoPixelAspectRatio on this build" };

  const asSize = (r) => (r.ok && r.value && r.value.width !== undefined
    ? `${r.value.width}x${r.value.height}` : null);
  const frameSize = asSize(frameSizeRead);
  const frameRect = asSize(frameRectRead);
  add("sequenceGeometry", "What does this sequence report as frame size and pixel aspect?",
    frameSize || frameRect || "could not read",
    {
      name: seq.name || "(unnamed)",
      "Sequence.getFrameSize()": frameSize || (frameSizeRead.ok ? "(no width on result)" : frameSizeRead.error),
      "SequenceSettings.getVideoFrameRect()": frameRect || (frameRectRead.ok ? "(no width on result)" : frameRectRead.error),
      routesAgree: frameSize && frameRect ? frameSize === frameRect : null,
      // Typed Promise<string> in Adobe's declarations, so it is recorded raw and unparsed.
      pixelAspectRatioRaw: parRead.ok ? JSON.stringify(parRead.value) : parRead.error,
      pixelAspectRatioType: parRead.ok ? typeof parRead.value : null,
    });

  // --- Selection ------------------------------------------------------------------------
  // Same route probeEffectChain uses. Deliberately NOT the per-track fallback in
  // timeline/effects.js: that fallback tests for an `isSelected` member that does not exist
  // in Adobe's declarations at any version in this line, so it finds nothing. A probe that
  // silently inherited that bug would report "nothing selected" on a build where something
  // is plainly selected, which is worse than no probe at all.
  const selRead = await attempt("getSelection", () =>
    (typeof seq.getSelection === "function" ? seq.getSelection() : null));
  let items = [];
  if (selRead.ok && selRead.value) {
    if (typeof selRead.value.getTrackItems === "function") {
      const itemsRead = await attempt("getTrackItems", () => selRead.value.getTrackItems());
      items = itemsRead.ok && itemsRead.value ? itemsRead.value : [];
    } else if (Array.isArray(selRead.value)) {
      items = selRead.value;
    }
  }
  add("selection", "How many track items are selected right now?", String(items.length),
    { selectionCall: selRead.ok ? "ok" : selRead,
      note: "Select ONE clip and run again for each shape in turn: source matching the " +
        "sequence, source not matching, non-square pixels, an Adjustment Layer, a graphic." });

  if (items.length === 0) {
    return { probe: "transform-params", complete: false, findings };
  }

  for (const item of items) {
    const label = item.name || "(unnamed)";

    // Adobe declares getIsSelected(); `isSelected` appears nowhere. Recorded per item so the
    // claim is evidenced on this build rather than inferred from the .d.ts alone.
    add("selectionApi", `Which selection getter does "${label}" actually expose?`,
      typeof item.getIsSelected === "function" ? "getIsSelected()" : "neither",
      { "getIsSelected": typeof item.getIsSelected,
        "isSelected (undocumented)": typeof item.isSelected });

    // --- Question 4 ---------------------------------------------------------------------
    const sourceDims = await readSourceDimensionCandidates(ppro, item);
    add("sourceDimensions", `Can a SOURCE resolution be recovered for "${label}"?`,
      sourceDims.available
        ? (sourceDims.resolutionCandidates && sourceDims.resolutionCandidates.length > 0
            ? `yes — ${sourceDims.resolutionCandidates.length} candidate column(s)`
            : "no — the metadata parsed but carries no resolution-looking column")
        : `no — ${sourceDims.why}`,
      Object.assign({
        why: "UXP exposes no source width/height on ProjectItem, ClipProjectItem or " +
          "FootageInterpretation. This column dump is the only candidate route, and Phase 5 " +
          "frame-alignment is blocked on it. Re-run with the Project panel's Video Info " +
          "column HIDDEN — if the answer changes, the route depends on a user setting.",
      }, sourceDims));

    // --- Questions 1 and 2 --------------------------------------------------------------
    const chainRead = await attempt(`getComponentChain(${label})`, () =>
      (typeof item.getComponentChain === "function" ? item.getComponentChain() : null));
    if (!chainRead.ok || !chainRead.value) {
      add("chain", `Does "${label}" expose a component chain?`, "no",
        chainRead.ok ? { detail: "null chain" } : chainRead);
      continue;
    }
    const chain = chainRead.value;
    const countRead = await attempt(`getComponentCount(${label})`, () => chain.getComponentCount());
    const count = countRead.ok ? countRead.value : 0;

    const allComponents = [];
    const transformComponents = [];
    for (let i = 0; i < count; i++) {
      const compRead = await attempt(`getComponentAtIndex(${i})`, () => chain.getComponentAtIndex(i));
      if (!compRead.ok || !compRead.value) continue;
      const component = compRead.value;
      const displayName = (await attempt("getDisplayName", () => component.getDisplayName())).value || null;
      const matchName = (await attempt("getMatchName", () => component.getMatchName())).value || null;
      allComponents.push({ index: i, displayName, matchName });
      if (looksLikeTransformComponent(displayName, matchName)) {
        transformComponents.push({ index: i, displayName, matchName, component });
      }
    }

    add("components", `What components does "${label}" carry, in index order?`,
      allComponents.map((c) => `[${c.index}] ${c.displayName} (${c.matchName})`).join(", ") || "(none read)",
      { components: allComponents,
        why: "The real Motion/Transform match names for this build go into transform/params.js. " +
          "Match on matchName, never displayName — displayName is localized (Premiere ships " +
          "per-locale ZString dictionaries), which is the same trap effects.js already warns about." });

    if (transformComponents.length === 0) {
      add("transform", `Does "${label}" have a Motion or Transform component?`, "not found",
        { searchedFor: TRANSFORM_COMPONENT_HINTS });
      continue;
    }

    for (const { index, displayName, matchName, component } of transformComponents) {
      const paramCountRead = await attempt("getParamCount", () => component.getParamCount());
      const paramCount = paramCountRead.ok ? paramCountRead.value : 0;

      const params = [];
      for (let p = 0; p < paramCount; p++) {
        const paramRead = await attempt(`getParam(${p})`, () => component.getParam(p));
        if (!paramRead.ok || !paramRead.value) {
          params.push({ index: p, error: paramRead.ok ? "getParam returned nothing" : paramRead.error });
          continue;
        }
        const param = paramRead.value;
        const name = param.displayName || `param[${p}]`;

        // getStartValue() takes no TickTime, which is why effects.js standardized on it: it
        // sidesteps the clip-relative-vs-sequence-relative ambiguity that Adobe documents
        // nowhere. Same choice here, for the same reason.
        const timeVaryingRead = await attempt("isTimeVarying", () =>
          (typeof param.isTimeVarying === "function" ? param.isTimeVarying() : null));
        const startRead = typeof param.getStartValue === "function"
          ? await attempt("getStartValue", () => param.getStartValue())
          : { ok: false, error: "no getStartValue on this param" };

        params.push(Object.assign(
          { index: p, name, isTimeVarying: timeVaryingRead.ok ? timeVaryingRead.value : `error: ${timeVaryingRead.error}` },
          startRead.ok ? describeParamValue(startRead.value) : { present: false, error: startRead.error }
        ));
      }

      add("transformParams",
        `What are "${label}"'s [${index}] ${displayName} params, by index?`,
        params.map((p) => `[${p.index}] ${p.name || "?"}=${p.rawJson || p.error || "?"}`).join(", ") || "(none read)",
        { matchName, componentIndex: index, paramCount, params,
          why: "Index + rawJson together answer the plan's Phase 1 and Phase 3 gates: which " +
            "index is Position/Scale/Anchor, and whether a point arrives as [x,y] or {x,y} " +
            "and in pixels or normalized units. Compare rawJson against the same clip's " +
            "Effect Controls readout before trusting either." });
    }
  }

  return { probe: "transform-params", complete: true, findings };
}

function formatTransformReport(report) {
  return formatFindings("Transform & Align Phase 0 probe — components, params, units", report);
}

/* Keyframe probe — the gate on animated quick-effect presets (timeline/effects.js is
   static-values-only until this reports). Read-only: creates, inserts and deletes nothing, and
   builds no Action objects either.

   The one question Adobe's reference leaves open: ComponentParam.getKeyframeListAsTickTimes()
   returns TickTimes, but relative to WHAT? Three readings are plausible, and they only differ
   on a clip that is both placed later than 0:00 and trimmed at its head:

     sequence  keyframe time = playhead
     clip      keyframe time = playhead - clip start            (0 = clip's first frame)
     media     keyframe time = playhead - clip start + In point (source-media time)

   Premiere's own declarations do say TrackItem.getInPoint() is "relative to the start time of
   the project item" and getStartTime() "relative to the sequence start time", so those two
   are well defined — only the keyframe side is unknown.

   The playhead is the anchor, not a guess about where the user clicked: put a keyframe AT the
   playhead, leave the playhead there, run this. Whichever reading turns the playhead into a
   time that is in the keyframe list is this build's convention. A preset replayed under the
   wrong one lands every keyframe off by the clip's start or In point — invisible on a clip at
   0:00 with no trim, wrong everywhere else. (Speed changes are out of scope: probe a 100% clip.)

   It also records what the interpolation mode numbers mean on this build: the declarations
   carry Keyframe.INTERPOLATION_MODE_* statics and a Constants.InterpolationMode enum, but not
   their numeric values, and effects.js must not store a raw number it can't name. */

/* Pure: which frame(s) of reference put a keyframe exactly on the playhead. All inputs are
   BigInt ticks. `ambiguous` means two readings coincide on this clip (it starts at 0:00, or
   its In point equals its start), so this clip cannot tell them apart. */
function classifyKeyframeReference({ keyframeTicks, playheadTicks, startTicks, inPointTicks }) {
  const candidates = {
    sequence: playheadTicks,
    clip: playheadTicks - startTicks,
    media: playheadTicks - startTicks + inPointTicks,
  };
  const onList = new Set(keyframeTicks.map(String));
  const matches = Object.keys(candidates).filter((k) => onList.has(String(candidates[k])));
  const distinct = new Set(Object.values(candidates).map(String)).size === 3;
  return {
    candidates: Object.fromEntries(Object.entries(candidates).map(([k, v]) => [k, v.toString()])),
    matches,
    ambiguous: !distinct,
    verdict: distinct && matches.length === 1 ? matches[0] : null,
  };
}

function readInterpolationConstants(ppro) {
  const statics = {};
  const kf = ppro && ppro.Keyframe;
  for (const name of ["LINEAR", "HOLD", "BEZIER", "TIME", "TIME_TRANSITION_START", "TIME_TRANSITION_END"]) {
    const key = `INTERPOLATION_MODE_${name}`;
    statics[key] = kf && kf[key] !== undefined ? kf[key] : null;
  }
  const constants = ppro && ppro.Constants && ppro.Constants.InterpolationMode;
  return {
    "Keyframe.INTERPOLATION_MODE_*": statics,
    "Constants.InterpolationMode": constants ? { ...constants } : null,
  };
}

async function probeKeyframeTiming(ppro) {
  const findings = [];
  const add = (...args) => { findings.push(finding(...args)); return findings[findings.length - 1]; };
  const stop = () => ({ probe: "keyframe-timing", complete: false, findings, verdict: null });

  if (!ppro || !ppro.Project) {
    add("host", "Is the Premiere API reachable?", "no", { detail: "require('premierepro') gave no Project" });
    return stop();
  }
  const projectRead = await attempt("getActiveProject", () => ppro.Project.getActiveProject());
  if (!projectRead.ok || !projectRead.value) {
    add("project", "Is a project open?", "no", projectRead.ok ? { detail: "no active project" } : projectRead);
    return stop();
  }
  const sequenceRead = await attempt("getActiveSequence", () => projectRead.value.getActiveSequence());
  if (!sequenceRead.ok || !sequenceRead.value) {
    add("sequence", "Is a sequence open?", "no", sequenceRead.ok ? { detail: "no active sequence" } : sequenceRead);
    return stop();
  }
  const seq = sequenceRead.value;

  add("interpolationConstants", "What numbers does this build use for keyframe interpolation modes?",
    "see evidence", readInterpolationConstants(ppro));

  // Same selection route as probeEffectChain / probeTransformParams (see the note there).
  const selRead = await attempt("getSelection", () =>
    (typeof seq.getSelection === "function" ? seq.getSelection() : null));
  let items = [];
  if (selRead.ok && selRead.value) {
    if (typeof selRead.value.getTrackItems === "function") {
      const itemsRead = await attempt("getTrackItems", () => selRead.value.getTrackItems());
      items = itemsRead.ok && itemsRead.value ? itemsRead.value : [];
    } else if (Array.isArray(selRead.value)) {
      items = selRead.value;
    }
  }
  add("selection", "How many track items are selected?", String(items.length),
    { note: "Select exactly ONE clip that starts later than 0:00 on the timeline AND is trimmed " +
        "at its head. Put the playhead inside it, add a keyframe there (e.g. Scale), add a " +
        "second one elsewhere set to Bezier, leave the playhead on the first, run again." });
  if (items.length !== 1) return stop();
  const item = items[0];
  const label = item.name || "(unnamed)";

  const startRead = await attempt("getStartTime", () => item.getStartTime());
  const endRead = await attempt("getEndTime", () => item.getEndTime());
  const inRead = await attempt("getInPoint", () => item.getInPoint());
  const playheadRead = await attempt("getPlayerPosition", () => seq.getPlayerPosition());
  const start = startRead.ok ? readTick(startRead.value) : null;
  const end = endRead.ok ? readTick(endRead.value) : null;
  const inPoint = inRead.ok ? readTick(inRead.value) : null;
  const playhead = playheadRead.ok ? readTick(playheadRead.value) : null;
  const clipTiming = {
    "getStartTime (sequence)": start ? start.ticks : startRead.error,
    "getEndTime (sequence)": end ? end.ticks : endRead.error,
    "getInPoint (source media)": inPoint ? inPoint.ticks : inRead.error,
    "playhead (sequence)": playhead ? playhead.ticks : playheadRead.error,
  };
  if (!start || !start.ticks || !inPoint || !inPoint.ticks || !playhead || !playhead.ticks) {
    add("clipTiming", `Can "${label}"'s timing and the playhead be read?`, "no", clipTiming);
    return stop();
  }
  const startTicks = BigInt(start.ticks);
  const inPointTicks = BigInt(inPoint.ticks);
  const playheadTicks = BigInt(playhead.ticks);
  const inside = end && end.ticks ? playheadTicks >= startTicks && playheadTicks < BigInt(end.ticks) : null;
  add("clipTiming", `Where is "${label}", and is the playhead on it?`,
    inside === false ? "playhead is OUTSIDE the clip — move it onto the keyframe and run again" : "read",
    clipTiming);

  // Every animated param on every component. Nothing is written; getKeyframePtr only reads.
  const chainRead = await attempt("getComponentChain", () => item.getComponentChain());
  if (!chainRead.ok || !chainRead.value) {
    add("chain", `Does "${label}" expose a component chain?`, "no", chainRead.ok ? null : chainRead);
    return stop();
  }
  const chain = chainRead.value;
  const count = (await attempt("getComponentCount", () => chain.getComponentCount())).value || 0;
  const animated = [];
  for (let i = 0; i < count; i++) {
    const c = (await attempt(`getComponentAtIndex(${i})`, () => chain.getComponentAtIndex(i))).value;
    if (!c) continue;
    const compName = (await attempt("getDisplayName", () => c.getDisplayName())).value || `component[${i}]`;
    const paramCount = (await attempt("getParamCount", () => c.getParamCount())).value || 0;
    for (let p = 0; p < paramCount; p++) {
      const param = (await attempt(`getParam(${p})`, () => c.getParam(p))).value;
      if (!param) continue;
      const varying = await attempt("isTimeVarying", () => param.isTimeVarying());
      if (!varying.ok || !varying.value) continue;
      const listRead = await attempt("getKeyframeListAsTickTimes", () => param.getKeyframeListAsTickTimes());
      const times = listRead.ok && Array.isArray(listRead.value) ? listRead.value : [];
      const keyframes = [];
      for (const t of times.slice(0, 8)) {
        const kf = (await attempt("getKeyframePtr", () => param.getKeyframePtr(t))).value;
        const mode = kf && typeof kf.getTemporalInterpolationMode === "function"
          ? await attempt("getTemporalInterpolationMode", () => kf.getTemporalInterpolationMode())
          : { ok: false, error: "no keyframe object" };
        keyframes.push({
          ticks: readTick(t).ticks,
          positionTicks: kf && kf.position ? readTick(kf.position).ticks : null,
          interpolationMode: mode.ok ? mode.value : mode.error,
          value: kf && kf.value !== undefined ? JSON.stringify(kf.value) : null,
        });
      }
      animated.push({
        param: `${compName} > ${param.displayName || `param[${p}]`}`,
        keyframeCount: times.length,
        listCall: listRead.ok ? "ok" : listRead.error,
        keyframes,
        hasSetInterpolationAction: typeof param.createSetInterpolationAtKeyframeAction === "function",
      });
    }
  }
  if (animated.length === 0) {
    add("animated", `Does "${label}" have any keyframed param?`, "no",
      { note: "Turn on the stopwatch for Scale (or any param) and add a keyframe at the playhead." });
    return stop();
  }
  add("animated", `Which params on "${label}" are keyframed, and what do their keyframes read as?`,
    animated.map((a) => `${a.param} (${a.keyframeCount})`).join(", "), { params: animated });

  const keyframeTicks = [];
  for (const a of animated) for (const k of a.keyframes) if (k.ticks) keyframeTicks.push(BigInt(k.ticks));
  const result = classifyKeyframeReference({ keyframeTicks, playheadTicks, startTicks, inPointTicks });
  add("reference", "Which frame of reference puts a keyframe exactly on the playhead?",
    result.ambiguous
      ? "cannot tell on this clip — it starts at 0:00 or isn't trimmed at its head, so two readings coincide"
      : result.matches.length === 0
        ? "none — no keyframe sits exactly on the playhead (move the playhead onto one and run again)"
        : result.matches.join(" AND "),
    { candidateTicks: result.candidates, matches: result.matches });

  return { probe: "keyframe-timing", complete: true, findings, verdict: result.verdict };
}

function formatKeyframeReport(report) {
  return formatFindings("Keyframe timing probe (animated presets gate)", report, report.verdict
    ? `VERDICT: keyframe times are ${report.verdict}-relative on this build. Record this report before building animated presets.`
    : `No verdict yet — read the findings above for what to change, then run again.`);
}

/* Adjustment Layer creation probe (docs/HANDOFF_CUTDECK_AL_FX_NEXT.md task 1). NOT read-only:
   it imports one generated Adjustment Layer into Project panel > CutDeck > ADJ & FX. That is
   the whole question: the API has no create call, so can a generated one-AL .prproj
   (timeline/alProject.js), sized to the active sequence, come in through importFiles?

   It answers, from the real host: does the import succeed without a dialog, where does the
   item land (the target bin, or a bin named after the file), does Premiere report the frame
   size we wrote, and would CutDeck's own findAdjustmentLayerItem now pick it. Undo steps are
   visible only in Edit > Undo, so the trailer asks the user to look.

   `deps` exists for tests; in Premiere every default is the real module / UXP storage. */
// Name multiset diff: project items have no stable identity across getItems() calls.
function newItemsByName(before, after) {
  const left = new Map();
  for (const it of before) left.set(it.name, (left.get(it.name) || 0) + 1);
  const added = [];
  for (const it of after) {
    const n = left.get(it.name) || 0;
    if (n > 0) left.set(it.name, n - 1); else added.push(it);
  }
  return added;
}

async function probeCreateAdjustmentLayer(ppro, deps = {}) {
  const findings = [];
  const add = (...args) => { findings.push(finding(...args)); return findings[findings.length - 1]; };
  const stop = () => ({ probe: "al-create", complete: false, findings, verdict: null });
  const alProject = deps.alProject || require("./timeline/alProject.js");
  const al = deps.al || require("./timeline/adjustmentLayer.js");
  const write = deps.writeFile || al.writeTempFile;
  const now = deps.now || (() => Date.now());

  if (!ppro || !ppro.Project) {
    add("host", "Is the Premiere API reachable?", "no", { detail: "require('premierepro') gave no Project" });
    return stop();
  }
  const projectRead = await attempt("getActiveProject", () => ppro.Project.getActiveProject());
  if (!projectRead.ok || !projectRead.value) {
    add("project", "Is a project open?", "no", projectRead.ok ? { detail: "no active project" } : projectRead);
    return stop();
  }
  const project = projectRead.value;
  const sequenceRead = await attempt("getActiveSequence", () => project.getActiveSequence());
  if (!sequenceRead.ok || !sequenceRead.value) {
    add("sequence", "Is a sequence open?", "no", sequenceRead.ok ? { detail: "no active sequence" } : sequenceRead);
    return stop();
  }
  const seq = sequenceRead.value;

  const settingsRead = await attempt("getSettings", () => seq.getSettings());
  const settings = settingsRead.ok ? settingsRead.value : null;
  const rectRead = await attempt("getVideoFrameRect", () => settings.getVideoFrameRect());
  const rateRead = await attempt("getVideoFrameRate", () => settings.getVideoFrameRate());
  const parRead = await attempt("getVideoPixelAspectRatio", () => settings.getVideoPixelAspectRatio());
  const width = rectRead.ok && rectRead.value ? Math.round(rectRead.value.width) : null;
  const height = rectRead.ok && rectRead.value ? Math.round(rectRead.value.height) : null;
  const ticksPerFrame = rateRead.ok && rateRead.value ? rateRead.value.ticksPerFrame : null;
  add("sequenceSize", `What size is "${seq.name || "the active sequence"}"?`,
    width && height ? `${width}x${height}` : "unreadable",
    { ticksPerFrame: rateRead.ok ? ticksPerFrame : rateRead.error,
      pixelAspectRatio: parRead.ok ? parRead.value : parRead.error,
      rect: rectRead.ok ? null : rectRead.error });
  if (!width || !height) return stop();

  let built;
  try {
    built = alProject.buildAdjustmentLayerPrproj({ width, height, ticksPerFrame: Number.isSafeInteger(ticksPerFrame) ? ticksPerFrame : null });
  } catch (error) {
    add("build", "Can the Adjustment Layer project be generated?", "no", { error: error.message || String(error) });
    return stop();
  }
  const fileName = `CutDeck ${width}x${height}.prproj`;
  const writeRead = await attempt("writeFile", () => write(fileName, built.bytes));
  add("file", "Was the generated .prproj written?", writeRead.ok ? "yes" : "no",
    writeRead.ok ? { path: writeRead.value, bytes: built.bytes.length, alName: built.name } : writeRead);
  if (!writeRead.ok) return stop();

  const binRead = await attempt("getOrCreateAdjBin", () => al.getOrCreateAdjBin(project));
  if (!binRead.ok || !binRead.value) {
    add("bin", `Is Project panel > CutDeck > ${al.ADJ_BIN_NAME} reachable?`, "no", binRead);
    return stop();
  }
  const adjBin = binRead.value;
  const rootRead = await attempt("getRootItem", () => project.getRootItem());
  const listBin = async (bin) => {
    const r = await attempt("getItems", () => bin.getItems());
    return r.ok && r.value ? r.value : [];
  };
  const binBefore = await listBin(adjBin);
  const rootBefore = rootRead.ok && rootRead.value ? await listBin(rootRead.value) : [];

  const t0 = now();
  const importRead = await attempt("importFiles", () => project.importFiles([writeRead.value], true, adjBin, false));
  const elapsedMs = now() - t0;
  add("import", "Did importFiles(generated .prproj, suppressUI=true, ADJ & FX) succeed?",
    importRead.ok ? String(importRead.value) : "threw",
    { elapsedMs, note: "If Premiere showed an Import Project dialog, the elapsed time includes you clicking it — say so when you report back.",
      error: importRead.ok ? null : importRead.error });
  if (!importRead.ok) return stop();

  const binAdded = newItemsByName(binBefore, await listBin(adjBin));
  const rootAdded = rootRead.ok && rootRead.value ? newItemsByName(rootBefore, await listBin(rootRead.value)) : [];
  const describe = async (it) => {
    if (it.type === 2) return { name: it.name, bin: true, children: (await listBin(it)).map((c) => c.name) };
    return { name: it.name, bin: false, videoInfo: await al.detectResolutionFromMetadata(it) };
  };
  const landed = [];
  for (const it of binAdded) landed.push({ where: al.ADJ_BIN_NAME, ...(await describe(it)) });
  for (const it of rootAdded) landed.push({ where: "project root", ...(await describe(it)) });
  add("landing", "Where did the imported item(s) land?",
    landed.length ? landed.map((l) => `${l.where}: "${l.name}"${l.bin ? " (a bin)" : ""}`).join("; ") : "nowhere visible — nothing new in ADJ & FX or the root",
    { items: landed });

  const direct = landed.find((l) => !l.bin && l.name === built.name);
  const nested = landed.find((l) => l.bin && l.children.includes(built.name));
  const sizeOk = direct && direct.videoInfo && direct.videoInfo.width === width && direct.videoInfo.height === height;
  if (direct) {
    add("size", `Does Premiere report "${built.name}" at ${width}x${height}?`,
      direct.videoInfo ? `${direct.videoInfo.width}x${direct.videoInfo.height}${sizeOk ? "" : " — MISMATCH"}` : "Video Info not populated (check the Project panel's Video Info column by eye)",
      null);
  }

  const pickRead = await attempt("findAdjustmentLayerItem", () => al.findAdjustmentLayerItem(project, seq));
  const pickedName = pickRead.ok && pickRead.value ? pickRead.value.name : null;
  add("pick", "Would Place AL now pick the generated layer for this sequence?",
    pickedName === built.name ? "yes" : pickedName ? `no — it picks "${pickedName}"` : "no AL found",
    pickRead.ok ? null : pickRead);

  const verdict = direct && pickedName === built.name && sizeOk !== false
    ? "works"
    : nested ? "lands-in-subbin" : null;
  return { probe: "al-create", complete: true, findings, verdict, alName: built.name };
}

function formatCreateAdjustmentLayerReport(report) {
  const undo = "Also check Edit > Undo: how many steps did this add, and does one Undo remove the item? Delete the test item afterwards if you like.";
  const trailer = report.verdict === "works"
    ? `VERDICT: CutDeck can create "${report.alName}" itself. ${undo}`
    : report.verdict === "lands-in-subbin"
      ? `VERDICT: the import works but lands inside a bin named after the file; production code would move it up. ${undo}`
      : "No verdict — read the findings above and send them back before any production code is built.";
  return formatFindings("Adjustment Layer creation probe (adds one item)", report, trailer);
}

module.exports = {
  probeCreateAdjustmentLayer, formatCreateAdjustmentLayerReport, newItemsByName,
  probeMarksAndTiming, formatReport, identifyRate, KNOWN_RATES,
  probeAdjustmentLayerMotion, formatMotionReport,
  probeEffectChain, formatEffectChainReport,
  probeTransformParams, formatTransformReport,
  probeKeyframeTiming, formatKeyframeReport, classifyKeyframeReference,
  formatFindings, describeParamValue, looksLikeTransformComponent,
};
