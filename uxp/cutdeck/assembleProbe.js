/* Phase 0 mutation probe for issue #25 — the three-point assemble route.

   THE POINT: not one primitive in issue #25's design has executed once in this
   project. createSequence + createSetSettingsAction, createSetInOutPointsAction,
   createOverwriteItemAction, createSetDisabledAction and createRemoveItemsAction
   are all taken from Adobe's published type definitions — the same evidentiary
   footing that produced eighteen confident, wrong rounds on the clone route
   (#18/#24). This probe spends one click to find out, at N=3 spans instead of 443.

   Three unknowns, deliberately in one click. That breaks the one-variable-per-round
   discipline #18 used, and the reason is that these three are independent and
   produce log signatures that cannot be mistaken for one another:

     1. SETTINGS   Does createSetSettingsAction(source.getSettings()) really carry
                   29.97 / 59.94 across, or does the new sequence fabricate a rate?
                   A fabricated 25 fps is the exact silent corruption issue #25
                   names: every .mp3 in this project's `media` table already reads
                   25/1 from probe()'s fallback while CFD 92 is really 29.97.
     2. PLACEMENT  Three interleaved setInOut/overwrite pairs in ONE transaction.
                   Three DIFFERENT ranges land -> the cheap path lives. Three
                   IDENTICAL ranges -> the shared ClipProjectItem resolves against
                   the last value written, and the fallback is one transaction per
                   span (acceptable now: undo is deleteSequence, not Ctrl+Z).
     3. REMOVAL    Disable item[1], then createRemoveItemsAction(sel, true, ANY) in
                   a separate transaction. Apply is built entirely on that call and
                   it has never run here.

   MUTATES THE PROJECT — the only thing in this panel that does. Run it in a
   disposable project, never a real edit. The panel arms the button in two clicks
   for that reason; every other CutDeck control is read-only or writes to disk.

   Nothing here throws at the caller and nothing is auto-deleted. A missing method,
   a method that throws, a transaction that refuses and a half-built sequence are
   all findings — a probe that dies on the first surprise tells you less than the
   build it was probing, and a partial build is evidence (issue #25: "Never
   auto-delete it"). Deleting the probe sequence is the human's job, and the report
   says so.

   toTicks() below deliberately does NOT reuse timelineRange.ticks(), even though
   they are now siblings. They have opposite jobs: ticks() is the production parser
   and must refuse anything irregular, while this one is a diagnostic reader whose
   whole purpose is to tolerate a host that hands back something unexpected and
   report what it was. Collapsing them would make the probe throw exactly where it
   most needs to keep reading. */

const TICKS_PER_SECOND = 254016000000n;
const PROBE_SEQUENCE_NAME = "CutDeck probe — assemble";

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

/* Dumps an unknown host object's real shape. Every wrong API guess this project
   has made was cheap to fix once the actual prototype was in the log. */
function describe(value) {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value !== "object") return `${typeof value}(${String(value)})`;
  const proto = Object.getPrototypeOf(value);
  const ctor = proto && proto.constructor ? proto.constructor.name : "?";
  const methods = proto ? Object.getOwnPropertyNames(proto).filter((k) => k !== "constructor") : [];
  return `[${ctor}] own=${JSON.stringify(Object.keys(value))} proto=${JSON.stringify(methods)}`;
}

/* Reads a tick count off whatever the host hands back — a TickTime, a decimal
   string, a safe integer — and refuses anything that would carry rounding in.
   Ticks are the unit of record here; seconds are for the log only. */
function toTicks(value, label) {
  if (value === null || value === undefined) throw new Error(`${label} is absent`);
  const raw = (typeof value === "object" && value.ticks !== undefined) ? value.ticks : value;
  if (typeof raw === "bigint") return raw;
  if (typeof raw === "number") {
    if (!Number.isSafeInteger(raw)) throw new Error(`${label} is not an exact tick count: ${raw}`);
    return BigInt(raw);
  }
  if (typeof raw === "string" && /^-?\d+$/.test(raw.trim())) return BigInt(raw.trim());
  throw new Error(`${label} is not a tick value: ${describe(value)}`);
}

/* The getter/constructor spellings below are unverified on this build. Finding out
   which one exists is part of what the probe is for, so a miss records the object's
   real shape rather than throwing a guessed name at the human. */
function pick(object, names) {
  if (!object) return null;
  for (const name of names) if (typeof object[name] === "function") return name;
  return null;
}

async function attempt(label, fn) {
  try { return { ok: true, value: await fn() }; }
  catch (error) { return { ok: false, at: label, error: (error && error.message) || String(error) }; }
}
function attemptSync(label, fn) {
  try { return { ok: true, value: fn() }; }
  catch (error) { return { ok: false, at: label, error: (error && error.message) || String(error) }; }
}

const framesish = (delta, tpf) =>
  delta % tpf === 0n ? `${delta / tpf} frame(s)` : `${delta} ticks (not a whole frame)`;

/* Three source spans with DISTINCT starts AND DISTINCT lengths, placed back to
   back in the destination. Distinct on both axes is what makes unknown 2 readable:
   a total collapse (three identical items) and a partial one (right length, wrong
   start) are different signatures, and neither can be confused with success.

   Every value is an exact multiple of one frame from the start, so "one rounding
   per boundary" (issue #25) holds by construction rather than by care, and adjacent
   placements share a boundary tick exactly — which is what makes a frame eaten by
   createOverwriteItemAction visible in the read-back. */
const SPAN_UNITS = [[0n, 1n], [3n, 2n], [7n, 3n]];  // [startUnit, lengthUnits]; 7+3 = 10 < 12
const SPAN_UNIT_DIVISOR = 12n;

function planSpans(mediaInTicks, mediaOutTicks, ticksPerFrame, destBaseTicks) {
  const durationFrames = (mediaOutTicks - mediaInTicks) / ticksPerFrame;
  const unitFrames = durationFrames / SPAN_UNIT_DIVISOR;
  if (unitFrames < 1n) {
    return { ok: false, reason: `the source clip is only ${durationFrames} frames long; the probe `
      + `needs at least ${SPAN_UNIT_DIVISOR} so its three spans have distinct lengths` };
  }
  const unit = unitFrames * ticksPerFrame;
  const spans = [];
  let cursor = destBaseTicks;
  for (const [startUnit, lengthUnits] of SPAN_UNITS) {
    const sourceIn = mediaInTicks + startUnit * unit;
    const length = lengthUnits * unit;
    spans.push({ index: spans.length, sourceInTicks: sourceIn, sourceOutTicks: sourceIn + length,
      destinationTicks: cursor, lengthTicks: length, lengthFrames: lengthUnits * unitFrames });
    cursor += length;
  }
  return { ok: true, spans, unitFrames, unit, predictedEndTicks: cursor,
    predictedEndFrames: (cursor - destBaseTicks) / ticksPerFrame };
}

async function runAssembleProbe(ppro, log) {
  const say = typeof log === "function" ? log : () => {};
  const findings = [];
  const verdicts = { settings: null, placement: null, removal: null };
  let built = null;  // the probe sequence, once it exists — never auto-deleted
  const add = (id, question, answer, evidence) => {
    findings.push({ id, question, answer, evidence: evidence === undefined ? null : evidence });
    say(`• ${question}\n    ${answer}`);
    return findings[findings.length - 1];
  };
  const stop = (complete) => ({ probe: "assemble-three-point", complete: !!complete, findings, verdicts,
    builtSequenceName: built ? PROBE_SEQUENCE_NAME : null,
    cleanup: built
      ? `A sequence named "${PROBE_SEQUENCE_NAME}" is in the project. Inspect it, then DELETE IT BY HAND. `
        + `This probe never deletes it: a half-built sequence is the evidence.`
      : "Nothing was created." });

  // Section 6 of the handoff requires exact integer tick math. Without BigInt none
  // of the rest would be trustworthy, so there is no point mutating a project.
  let bigintOk = false;
  try { bigintOk = typeof BigInt === "function" && BigInt("9007199254740993") + 1n === 9007199254740994n; }
  catch (_) { bigintOk = false; }
  add("bigint", "Does this UXP runtime support exact BigInt arithmetic?",
    bigintOk ? "yes" : "NO — exact tick math cannot run here; refusing to mutate",
    { checked: "BigInt('9007199254740993') + 1n" });
  if (!bigintOk) return stop(false);

  if (!ppro || !ppro.Project) {
    add("host", "Is the Premiere API reachable?", "no", { detail: "require('premierepro') gave no Project" });
    return stop(false);
  }
  const projectRead = await attempt("getActiveProject", () => ppro.Project.getActiveProject());
  const project = projectRead.ok ? projectRead.value : null;
  if (!project) {
    add("project", "Is a project open?", "no", projectRead.ok ? { detail: "no active project" } : projectRead);
    return stop(false);
  }
  const sourceRead = await attempt("getActiveSequence", () => project.getActiveSequence());
  const source = sourceRead.ok ? sourceRead.value : null;
  if (!source) {
    add("sequence", "Is a source sequence open?", "no",
      sourceRead.ok ? { detail: "no active sequence" } : sourceRead);
    return stop(false);
  }
  add("sequence", "Is a source sequence open?", "yes", { name: source.name || "(unnamed)" });

  const timebaseRead = await attempt("getTimebase", () => source.getTimebase());
  let ticksPerFrame = null;
  try { ticksPerFrame = timebaseRead.ok ? toTicks(timebaseRead.value, "Source timebase") : null; }
  catch (error) { ticksPerFrame = null; timebaseRead.error = error.message; }
  const sourceRate = ticksPerFrame ? identifyRate(ticksPerFrame) : null;
  add("sourceTimebase", "What timebase does the SOURCE sequence report?",
    ticksPerFrame
      ? `${ticksPerFrame} ticks/frame${sourceRate ? ` (${sourceRate} fps)` : " (off the broadcast grid)"}`
      : "unreadable",
    ticksPerFrame ? { rate: sourceRate } : timebaseRead);
  if (!ticksPerFrame || ticksPerFrame <= 0n) return stop(false);

  // One gesture yields the ProjectItem and the media range — issue #25's
  // "first track item on the active sequence" entry point.
  const clip = await readSourceClip(ppro, source, add);
  if (!clip) return stop(false);

  const tickTime = makeTickTime(ppro, add);
  if (!tickTime) return stop(false);

  const spanPlan = planSpans(clip.mediaInTicks, clip.mediaOutTicks, ticksPerFrame, 0n);
  if (!spanPlan.ok) {
    add("spans", "Can three distinct spans be carved from this clip?", "no", { reason: spanPlan.reason });
    return stop(false);
  }

  /* ---- UNKNOWN 1: does a new sequence inherit the source's real timebase? ---- */
  const created = await attempt("createSequence", () =>
    typeof project.createSequence === "function" ? project.createSequence(PROBE_SEQUENCE_NAME) : null);
  if (!created.ok || !created.value) {
    add("createSequence", "Does Project.createSequence() exist and return a sequence?", "no",
      created.ok ? { detail: "returned nothing", projectShape: describe(project) } : created);
    return stop(false);
  }
  built = created.value;
  add("createSequence", "Does Project.createSequence() exist and return a sequence?", "yes",
    { shape: describe(built) });

  const settingsRead = await attempt("getSettings", () =>
    typeof source.getSettings === "function" ? source.getSettings() : null);
  const applied = settingsRead.ok && settingsRead.value
    ? commit(project, "CutDeck probe: copy source sequence settings", (compound) => {
        const action = built.createSetSettingsAction(settingsRead.value);
        if (!compound.addAction(action)) throw new Error("addAction(setSettings) returned false");
      })
    : { ok: false, at: "getSettings", error: settingsRead.error || "source.getSettings() gave nothing" };
  const afterTimebase = await attempt("new getTimebase", () => built.getTimebase());
  let newTicksPerFrame = null;
  try { newTicksPerFrame = afterTimebase.ok ? toTicks(afterTimebase.value, "New timebase") : null; } catch (_) {}
  const newRate = newTicksPerFrame ? identifyRate(newTicksPerFrame) : null;
  if (newTicksPerFrame !== null && newTicksPerFrame === ticksPerFrame) {
    verdicts.settings = "inherited";
    add("settings", "Does createSetSettingsAction carry the source timebase across?",
      `INHERITED — ${newTicksPerFrame} ticks/frame${newRate ? ` (${newRate} fps)` : ""}, same as the source`,
      { applied: applied.ok ? "committed" : applied, sourceRate, newRate });
  } else {
    verdicts.settings = newTicksPerFrame === null ? "unreadable" : "fabricated";
    add("settings", "Does createSetSettingsAction carry the source timebase across?",
      newTicksPerFrame === null
        ? "UNREADABLE — the new sequence would not report a timebase"
        : `FABRICATED — new sequence reports ${newTicksPerFrame} ticks/frame`
          + `${newRate ? ` (${newRate} fps)` : ""} but the source is ${ticksPerFrame}`
          + `${sourceRate ? ` (${sourceRate} fps)` : ""}. This is the silent-corruption case: REFUSE and stop.`,
      { applied: applied.ok ? "committed" : applied, sourceRate, newRate,
        detail: afterTimebase.ok ? null : afterTimebase });
  }
  // Issue #25's own rule: verify the timebase matches, refuse loudly if not. A
  // mismatched destination makes every placement below wrong by construction, so
  // measuring unknowns 2 and 3 against it would produce a number worth nothing.
  if (verdicts.settings !== "inherited") {
    add("stopped", "Were the placement and removal unknowns tested?", "no",
      { why: "the destination timebase does not match the source; placements there would be meaningless" });
    return stop(true);
  }

  /* ---- UNKNOWN 2: N=3 interleaved setInOut + overwrite in ONE transaction ---- */
  const editorRead = pick(ppro.SequenceEditor, ["getEditor"])
    ? await attempt("SequenceEditor.getEditor", () => ppro.SequenceEditor.getEditor(built))
    : { ok: false, at: "SequenceEditor.getEditor", error: "no SequenceEditor.getEditor on this build" };
  if (!editorRead.ok || !editorRead.value) {
    add("editor", "Is there a SequenceEditor for the new sequence?", "no",
      editorRead.ok ? { detail: "returned nothing", shape: describe(ppro.SequenceEditor) } : editorRead);
    return stop(true);
  }
  const editor = editorRead.value;

  const baseRead = await attempt("new getEndTime", () => built.getEndTime());
  let destBase = 0n;
  try { destBase = baseRead.ok ? toTicks(baseRead.value, "New sequence end") : 0n; } catch (_) { destBase = 0n; }
  add("destinationBase", "Where does an empty new sequence start?", `${destBase} ticks`,
    { note: "placements below are absolute from here, so a nonzero sequence start cannot shift them" });
  const spans = spanPlan.spans.map((s) => ({ ...s, destinationTicks: s.destinationTicks + destBase }));
  const predictedEnd = spanPlan.predictedEndTicks + destBase;

  say(`Placing ${spans.length} spans of ${spans.map((s) => s.lengthFrames).join("/")} frames in ONE `
    + `transaction; predicted assembled length ${spanPlan.predictedEndFrames} frames.`);
  const placed = commit(project, "CutDeck probe: three-point assemble (N=3, one transaction)", (compound) => {
    for (const span of spans) {
      const setInOut = clip.projectItem.createSetInOutPointsAction(
        tickTime(span.sourceInTicks), tickTime(span.sourceOutTicks));
      if (!compound.addAction(setInOut)) throw new Error(`addAction(setInOut #${span.index}) returned false`);
      const overwrite = editor.createOverwriteItemAction(
        clip.projectItem, tickTime(span.destinationTicks), 0, 0);
      if (!compound.addAction(overwrite)) throw new Error(`addAction(overwrite #${span.index}) returned false`);
    }
  });
  if (!placed.ok) {
    verdicts.placement = "threw";
    add("placement", "Do three interleaved setInOut/overwrite pairs commit in one transaction?",
      "NO — it threw",
      { ...placed, meaning: "the cheap path is dead here; try one transaction per span next" });
    return stop(true);
  }

  const readBack = await readPlacedItems(built, add);
  if (!readBack) return stop(true);
  verdicts.placement = judgePlacement(readBack, spans, ticksPerFrame, predictedEnd, add,
    await attempt("assembled getEndTime", () => built.getEndTime()));
  if (verdicts.placement !== "independent") return stop(true);

  /* ---- UNKNOWN 3: disable, then ripple-remove in a SEPARATE transaction ---- */
  const victim = readBack.items[1];
  const victimLength = readBack.spans[1].endTicks - readBack.spans[1].startTicks;
  const disabled = commit(project, "CutDeck probe: disable the middle span", (compound) => {
    const action = victim.createSetDisabledAction(true);
    if (!compound.addAction(action)) throw new Error("addAction(setDisabled) returned false");
  });
  const isDisabled = await attempt("isDisabled", () =>
    typeof victim.isDisabled === "function" ? victim.isDisabled() : null);
  add("disable", "Does createSetDisabledAction(true) grey out item[1]?",
    disabled.ok
      ? (isDisabled.value === true
          ? "yes, and isDisabled() confirms it"
          : `committed, but isDisabled() reads ${JSON.stringify(isDisabled.value)}`)
      : "NO — it threw",
    disabled.ok ? { isDisabled: isDisabled.ok ? isDisabled.value : isDisabled } : disabled);
  if (!disabled.ok) { verdicts.removal = "not reached — disable failed"; return stop(true); }

  const selection = await buildSelection(ppro, built, victim, add);
  const mediaAny = ppro.Constants && ppro.Constants.MediaType ? ppro.Constants.MediaType.ANY : undefined;
  const removed = commit(project, "CutDeck probe: ripple-remove the disabled span", (compound) => {
    const action = editor.createRemoveItemsAction(selection.value, true, mediaAny);
    if (!compound.addAction(action)) throw new Error("addAction(removeItems) returned false");
  });
  if (!removed.ok) {
    verdicts.removal = "threw";
    add("removal", "Does createRemoveItemsAction(sel, ripple=true, ANY) work?", "NO — it threw",
      { ...removed, meaning: "Apply is built entirely on this call; it needs another route",
        selectionVia: selection.via });
    return stop(true);
  }
  const endAfter = await attempt("getEndTime after remove", () => built.getEndTime());
  let endAfterTicks = null;
  try { endAfterTicks = endAfter.ok ? toTicks(endAfter.value, "End after remove") : null; } catch (_) {}
  const expected = predictedEnd - victimLength;
  if (endAfterTicks === expected) {
    verdicts.removal = "exact";
    add("removal", "Does createRemoveItemsAction(sel, ripple=true, ANY) work?",
      `YES — length shrank by exactly the disabled span (${victimLength / ticksPerFrame} frames)`,
      { before: predictedEnd.toString(), after: endAfterTicks.toString(), selectionVia: selection.via });
  } else {
    verdicts.removal = endAfterTicks === null ? "unverifiable" : "wrong length";
    add("removal", "Does createRemoveItemsAction(sel, ripple=true, ANY) work?",
      endAfterTicks === null
        ? "committed, but the new length could not be read"
        : `committed, but the length is WRONG: expected ${expected} ticks, got ${endAfterTicks}`
          + ` (off by ${framesish(endAfterTicks - expected, ticksPerFrame)})`,
      { before: predictedEnd.toString(), expected: expected.toString(),
        after: endAfterTicks === null ? endAfter : endAfterTicks.toString(), selectionVia: selection.via });
  }
  return stop(true);
}

/* lockedAccess wrapping executeTransaction is the pattern #18 confirmed against
   Adobe's own sample and a third-party plugin — executeTransaction is never called
   bare. Both callbacks are synchronous, so nothing may be awaited inside. */
function commit(project, label, stage) {
  return attemptSync(label, () => {
    let result = null;
    const run = () => { result = project.executeTransaction((compound) => stage(compound), label); };
    if (typeof project.lockedAccess === "function") project.lockedAccess(run); else run();
    if (result === false) throw new Error(`executeTransaction returned false for "${label}"`);
    return result;
  });
}

async function readSourceClip(ppro, sequence, add) {
  const trackRead = await attempt("getVideoTrack(0)", () => sequence.getVideoTrack(0));
  if (!trackRead.ok || !trackRead.value) {
    add("sourceClip", "Is there a clip on V1 to assemble from?", "no video track 0",
      trackRead.ok ? { detail: "returned nothing" } : trackRead);
    return null;
  }
  const clipType = ppro.Constants && ppro.Constants.TrackItemType
    ? ppro.Constants.TrackItemType.CLIP : undefined;
  const itemsRead = await attempt("getTrackItems", () => trackRead.value.getTrackItems(clipType, false));
  const items = itemsRead.ok ? itemsRead.value : null;
  if (!items || !items.length) {
    add("sourceClip", "Is there a clip on V1 to assemble from?", "no",
      itemsRead.ok ? { detail: "V1 has no clip items" } : itemsRead);
    return null;
  }
  const item = items[0];
  const piRead = await attempt("getProjectItem", () =>
    typeof item.getProjectItem === "function" ? item.getProjectItem() : null);
  if (!piRead.ok || !piRead.value) {
    add("sourceClip", "Does the track item yield a ClipProjectItem?", "no",
      piRead.ok ? { detail: "getProjectItem() gave nothing", shape: describe(item) } : piRead);
    return null;
  }
  const inRead = await attempt("item getInPoint", () => item.getInPoint());
  const outRead = await attempt("item getOutPoint", () => item.getOutPoint());
  let mediaInTicks = null, mediaOutTicks = null;
  try {
    mediaInTicks = toTicks(inRead.value, "Clip media In");
    mediaOutTicks = toTicks(outRead.value, "Clip media Out");
  } catch (error) {
    add("sourceClip", "Can the clip's source media range be read exactly?", "no",
      { error: error.message, in: inRead, out: outRead });
    return null;
  }
  if (mediaOutTicks <= mediaInTicks) {
    add("sourceClip", "Can the clip's source media range be read exactly?", "no",
      { detail: `media Out ${mediaOutTicks} is not after media In ${mediaInTicks}` });
    return null;
  }
  add("sourceClip", "Which clip is the probe assembling from?", item.name || "(unnamed)",
    { mediaIn: mediaInTicks.toString(), mediaOut: mediaOutTicks.toString(), shape: describe(item) });
  return { item, projectItem: piRead.value, mediaInTicks, mediaOutTicks };
}

/* TickTime's constructor spelling is unverified here. Prefer an exact tick
   constructor; fall back to seconds only with the loss recorded, because a seconds
   round trip is exactly the rounding this design exists to avoid. */
function makeTickTime(ppro, add) {
  const TickTime = ppro.TickTime;
  const exact = pick(TickTime, ["createWithTicks", "createWithTickcount", "createWithTickCount"]);
  if (exact) {
    add("tickTime", "How are exact tick values handed back to Premiere?", `TickTime.${exact}(string)`);
    return (value) => TickTime[exact](value.toString());
  }
  if (pick(TickTime, ["createWithSeconds"])) {
    add("tickTime", "How are exact tick values handed back to Premiere?",
      "ONLY TickTime.createWithSeconds — every boundary below goes through a float",
      { shape: describe(TickTime), risk: "sub-frame drift is possible; treat placement results as approximate" });
    return (value) => TickTime.createWithSeconds(Number(value) / Number(TICKS_PER_SECOND));
  }
  add("tickTime", "How are exact tick values handed back to Premiere?", "no usable TickTime constructor",
    { shape: describe(TickTime) });
  return null;
}

async function readPlacedItems(sequence, add) {
  const trackRead = await attempt("new getVideoTrack(0)", () => sequence.getVideoTrack(0));
  if (!trackRead.ok || !trackRead.value) {
    add("readBack", "Can the assembled track be read back?", "no", trackRead);
    return null;
  }
  const itemsRead = await attempt("new getTrackItems", () => trackRead.value.getTrackItems(undefined, false));
  const items = itemsRead.ok && itemsRead.value ? itemsRead.value : null;
  if (!items) { add("readBack", "Can the assembled track be read back?", "no", itemsRead); return null; }
  const spans = [];
  for (let i = 0; i < items.length; i++) {
    const startRead = await attempt(`item[${i}] getStartTime`, () => items[i].getStartTime());
    const endRead = await attempt(`item[${i}] getEndTime`, () => items[i].getEndTime());
    const inRead = await attempt(`item[${i}] getInPoint`, () => items[i].getInPoint());
    try {
      spans.push({ startTicks: toTicks(startRead.value, "start"), endTicks: toTicks(endRead.value, "end"),
        mediaInTicks: toTicks(inRead.value, "in") });
    } catch (error) {
      add("readBack", "Can every assembled item be read back exactly?", "no",
        { index: i, error: error.message });
      return null;
    }
  }
  return { items, spans };
}

/* The whole point of unknown 2. Three distinct ranges is the cheap path living;
   three identical ones is the shared ClipProjectItem resolving against the last
   value written, which costs one transaction per span. Anything else is neither,
   and gets reported as itself rather than squeezed into one of the two. */
function judgePlacement(readBack, spans, ticksPerFrame, predictedEnd, add, endRead) {
  const actual = readBack.spans;
  const shown = actual.map((s, i) => `[${i}] ${s.startTicks}..${s.endTicks} (media in ${s.mediaInTicks}, `
    + `${framesish(s.endTicks - s.startTicks, ticksPerFrame)})`);
  const question = "Do three interleaved setInOut/overwrite pairs land as three distinct spans?";
  if (actual.length !== spans.length) {
    add("placement", question, `NO — ${actual.length} item(s) on the track, expected ${spans.length}`,
      { items: shown });
    return `wrong item count (${actual.length})`;
  }
  const lengths = actual.map((s) => (s.endTicks - s.startTicks).toString());
  const mediaIns = actual.map((s) => s.mediaInTicks.toString());
  if (new Set(lengths).size === 1 && new Set(mediaIns).size === 1) {
    add("placement", question,
      "NO — COLLAPSED. All three items share one media In and one length, so the shared "
      + "ClipProjectItem resolved every overwrite against the LAST setInOut written. "
      + "Fall back to one transaction per span (acceptable: undo is deleteSequence).",
      { items: shown, expected: spans.map((s) => `[${s.index}] in ${s.sourceInTicks} len ${s.lengthTicks}`) });
    return "collapsed";
  }
  const mismatches = [];
  for (let i = 0; i < spans.length; i++) {
    if (actual[i].mediaInTicks !== spans[i].sourceInTicks) {
      mismatches.push(`[${i}] media In ${actual[i].mediaInTicks}, asked ${spans[i].sourceInTicks}`);
    }
    if (actual[i].startTicks !== spans[i].destinationTicks) {
      mismatches.push(`[${i}] starts at ${actual[i].startTicks}, asked ${spans[i].destinationTicks}`);
    }
    if (actual[i].endTicks - actual[i].startTicks !== spans[i].lengthTicks) {
      mismatches.push(`[${i}] is ${framesish(actual[i].endTicks - actual[i].startTicks, ticksPerFrame)}, `
        + `asked ${spans[i].lengthFrames} frame(s)`);
    }
  }
  // Adjacent placements were asked to share a boundary tick exactly; a gap or an
  // overlap here is the black flash / audio pop that issue #25's shared-array
  // rounding exists to prevent, or a frame silently eaten by the overwrite.
  const seams = [];
  for (let i = 1; i < actual.length; i++) {
    const delta = actual[i].startTicks - actual[i - 1].endTicks;
    if (delta !== 0n) {
      seams.push(`between [${i - 1}] and [${i}]: ${framesish(delta, ticksPerFrame)} `
        + `${delta > 0n ? "GAP" : "OVERLAP"}`);
    }
  }
  let endTicks = null;
  try { endTicks = endRead.ok ? toTicks(endRead.value, "assembled end") : null; } catch (_) {}
  if (mismatches.length || seams.length || endTicks !== predictedEnd) {
    add("placement", question, "PARTIALLY — the items are distinct, but they are not what was asked for",
      { items: shown, mismatches, seams,
        assembledEnd: endTicks === null ? endRead : endTicks.toString(),
        predictedEnd: predictedEnd.toString() });
    return "distinct but wrong";
  }
  add("placement", question,
    "YES — three distinct ranges, exact boundaries, exact total length. The cheap path lives: "
    + "one transaction can carry all 443 placements.", { items: shown, seams: "none" });
  return "independent";
}

/* createRemoveItemsAction takes a selection object whose construction is not
   documented for this case. Try the spellings in order and record which one this
   build actually accepted — a wrong guess here is a dead click otherwise. */
async function buildSelection(ppro, sequence, item, add) {
  const question = "How is a removal selection expressed on this build?";
  const viaGet = await attempt("sequence.getSelection", () =>
    typeof sequence.getSelection === "function" ? sequence.getSelection() : null);
  if (viaGet.ok && viaGet.value && typeof viaGet.value.addItem === "function") {
    const group = viaGet.value;
    const filled = attemptSync("selection.addItem", () => {
      if (typeof group.clear === "function") group.clear();
      group.addItem(item, false);
    });
    if (filled.ok) {
      add("selection", question, "Sequence.getSelection() + addItem(item, false)", { shape: describe(group) });
      return { ok: true, value: group, via: "getSelection().addItem" };
    }
    add("selection", question, "getSelection() exists but addItem failed", filled);
  }
  const ctor = pick(ppro.TrackItemSelection, ["createEmptySelection", "create"]);
  if (ctor) {
    const made = attemptSync("TrackItemSelection ctor", () => {
      const group = ppro.TrackItemSelection[ctor]();
      group.addItem(item, false);
      return group;
    });
    if (made.ok) {
      add("selection", question, `TrackItemSelection.${ctor}() + addItem(item, false)`);
      return { ok: true, value: made.value, via: `TrackItemSelection.${ctor}` };
    }
  }
  add("selection", question, "no known constructor worked — passing a bare array and recording what happens",
    { sequenceSelection: viaGet.ok ? describe(viaGet.value) : viaGet,
      trackItemSelection: describe(ppro.TrackItemSelection) });
  return { ok: true, value: [item], via: "bare array (guess)" };
}

/* One block a human can read in the panel and paste onto issue #25. */
function formatReport(report) {
  const lines = [`Phase 0 assemble probe (${report.complete ? "complete" : "stopped early"}) — issue #25`, ``];
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
  lines.push(``);
  lines.push(`VERDICTS  settings:  ${report.verdicts.settings || "not reached"}`);
  lines.push(`          placement: ${report.verdicts.placement || "not reached"}`);
  lines.push(`          removal:   ${report.verdicts.removal || "not reached"}`);
  lines.push(``);
  lines.push(report.cleanup);
  return lines.join("\n");
}

module.exports = { runAssembleProbe, formatReport, planSpans, judgePlacement, identifyRate, toTicks,
  describe, PROBE_SEQUENCE_NAME, SPAN_UNITS, SPAN_UNIT_DIVISOR, TICKS_PER_SECOND };
