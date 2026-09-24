/* Native rough cut Route A (docs/HANDOFF_CUTDECK_NATIVE_ROUGH_CUT.md 3.2): apply the helper's
   cut list to a COPY of the editor's sequence with live Premiere edits, then prove it by
   read-back. The source sequence is never edited.

   Built only on what the "Test Native Cut" probe proved live (TODO_LEDGER 2026-09-24):
     - createMoveAction is RELATIVE; linked audio does NOT follow, so every item moves itself.
     - createRemoveItemsAction(ripple=false, <its media type>) removes just that item.
     - createSetInPointAction trims the head, createSetOutPointAction the tail (media time).
       createSetEndAction is broken on this build — never used.
     - a clone OVERWRITES the time it lands on — used here as the razor (see applyPlan).
     - items read before a transaction can go stale, so every step re-reads the copy.
   Up to five undo steps, said in the status line. */

const { runTransaction, getOrCreateBin, asBinLike, CUTDECK_BIN_NAME, ROUGH_CUTS_BIN_NAME } = require("../host/project.js");
const { TICKS_PER_SECOND, toTicks } = require("../host/ticks.js");
const { readSequence } = require("./nativeSync.js");
const { cutsToTicks, planCutApply, verifyReadBack, shiftFor } = require("./cutPlanApply.js");

const CLONE_GAP = 2n * TICKS_PER_SECOND;

const kindOf = (c) => c.kind; // "video" | "audio" from readSequence
const itemKey = (c) => `${kindOf(c)}|${c.track}|${c.start}`;
const asPlanItem = (c, extra = {}) => ({ id: itemKey(c), name: c.path ? String(c.path).split(/[\\/]/).pop() : "clip",
  mediaType: kindOf(c), track: c.track, startTicks: c.start, endTicks: c.end, inTicks: c.inPoint, ...extra });

/* Everything the planner's whole-plan refusal needs, read from the host. */
async function readItems(ppro, seq) {
  const s = await readSequence(ppro, seq);
  const items = [];
  for (const c of [...s.video, ...s.audio]) {
    let speed = 1, reversed = false, isNested = false, isMulticam = false;
    try { speed = await c.item.getSpeed(); } catch (_) { /* not reported: treat as normal */ }
    try { reversed = !!(await c.item.isSpeedReversed()); } catch (_) { /* idem */ }
    try {
      const pi = ppro.ClipProjectItem.cast(await c.item.getProjectItem());
      if (pi && typeof pi.isSequence === "function") isNested = !!(await pi.isSequence());
      if (pi && typeof pi.isMulticamClip === "function") isMulticam = !!(await pi.isMulticamClip());
    } catch (_) { /* graphics / adjustment layers have no clip project item */ }
    items.push(asPlanItem(c, { speed, reversed, isNested, isMulticam, raw: c }));
  }
  const transitions = [];
  const type = ppro.Constants.TrackItemType.TRANSITION;
  for (const [kind, count, get] of [["video", s.videoTracks, (i) => seq.getVideoTrack(i)], ["audio", s.audioTracks, (i) => seq.getAudioTrack(i)]]) {
    for (let t = 0; t < count; t++) {
      const track = await get(t);
      const found = track ? (await track.getTrackItems(type, false)) || [] : [];
      for (const x of found) {
        transitions.push({ id: `${kind}-transition-${t}`, name: "transition", mediaType: kind, track: t, isTransition: true,
          startTicks: toTicks(await x.getStartTime()), endTicks: toTicks(await x.getEndTime()), inTicks: 0n });
      }
    }
  }
  return { items, transitions, videoTracks: s.videoTracks, audioTracks: s.audioTracks };
}

/* Applies the cuts to `copy`, whose clips are `items`. Returns the undo-step count.

   Splits use Premiere's own overwrite as the razor. Live run 2 (2026-09-24) showed the first
   design — one full-length clone per extra piece, parked past the end — cannot scale: 432 cuts
   on a 25-minute clip meant ~431 full-length clones per track, and pieces went missing. Instead:
     1. one filler per track: clone that track's clip past the end,
     2. trim it to ONE frame,
     3. clone the filler onto every cut edge that falls inside a clip — an overwrite splits the
        clip under it, so the kept pieces are the original clip, effects and all,
     4. remove everything now lying inside a cut (the fillers too),
     5. move every survivor left by what was removed before it. */
async function applyPlan(ppro, project, copy, items, cuts, tpf) {
  const tick = (n) => ppro.TickTime.createWithTicks(n.toString());
  const editor = () => ppro.SequenceEditor.getEditor(copy);
  // Actions must be CREATED inside the transaction callback — built outside it, Premiere throws
  // "The script object is no longer valid." (live run 2026-09-24). So each step passes a list
  // of builders, not actions.
  const tx = (label, builders) => {
    if (!builders.length) return 0;
    runTransaction(project, `CutDeck: ${label}`, (compound) => {
      builders.forEach((build, i) => {
        const where = `${label}: action ${i + 1} of ${builders.length}${build.what ? ` (${build.what})` : ""}`;
        let action, added;
        try { action = build(); } catch (e) { throw new Error(`${where} failed to build: ${e.message}`); }
        if (!action) throw new Error(`${where}: Premiere returned no action (${action})`);
        try { added = compound.addAction(action); } catch (e) { throw new Error(`${where} was refused: ${e.message}`); }
        if (!added) throw new Error(`${where}: addAction returned false`);
      });
    });
    return 1;
  };
  const read = () => readSequence(ppro, copy);
  const all = (seq) => [...seq.video, ...seq.audio];
  const lane = (c) => `${c.kind || c.mediaType}|${c.track}`;
  let steps = 0;

  // Where each track needs a razor: every cut edge strictly inside a clip. The edge at b is cut
  // by a one-frame filler ending there, so the filler itself lies inside the cut.
  const edges = new Map(); // lane -> Set of filler starts
  const sourceOf = new Map(); // lane -> an item on that track to make the filler from
  for (const it of items) {
    for (const [a, b] of cuts) {
      if (!(a < it.endTicks && b > it.startTicks)) continue;
      const at = new Set(edges.get(lane(it)) || []);
      if (a > it.startTicks) at.add(a);
      if (b < it.endTicks) at.add(b - tpf);
      if (at.size) { edges.set(lane(it), at); if (!sourceOf.has(lane(it))) sourceOf.set(lane(it), it); }
    }
  }
  const endNow = items.reduce((m, it) => (it.endTicks > m ? it.endTicks : m), 0n);
  const park = ((endNow + CLONE_GAP) / tpf) * tpf;
  const findIn = (seq, key, start) => all(seq).find((c) => lane(c) === key && c.start === start);

  // 1-2. fillers: clone each lane's source clip to `park`, then trim it to one frame.
  let seq = await read();
  steps += tx("make razor fillers", [...sourceOf].map(([key, it]) => {
    const src = findIn(seq, key, it.startTicks);
    if (!src) throw new Error(`clip on ${key.replace("|", " track ")} vanished`);
    return () => editor().createCloneTrackItemAction(src.item, tick(park - it.startTicks), 0, 0, false, false);
  }));
  seq = await read();
  steps += tx("trim razor fillers", [...sourceOf.keys()].map((key) => {
    const f = findIn(seq, key, park);
    if (!f) throw new Error(`razor filler on ${key.replace("|", " track ")} did not land`);
    return () => f.item.createSetOutPointAction(tick(f.inPoint + tpf));
  }));

  // 3. razor: one filler clone per cut edge.
  seq = await read();
  const razor = [];
  for (const [key, at] of edges) {
    const f = findIn(seq, key, park);
    if (!f || f.end - f.start !== tpf) throw new Error(`razor filler on ${key.replace("|", " track ")} is not one frame long`);
    for (const p of at) {
      razor.push(Object.assign(() => editor().createCloneTrackItemAction(f.item, tick(p - park), 0, 0, false, false),
        { what: `${key.replace("|", " track ")}, filler from ${f.path || "no media"}, edge at ${Number(p) / Number(TICKS_PER_SECOND)}s, offset ${p - park}` }));
    }
  }
  steps += tx("split at cut edges", razor);

  // 4. remove everything inside a cut, and the fillers — per media type.
  seq = await read();
  const inside = (c) => c.start >= park || cuts.some(([a, b]) => a <= c.start && c.end <= b);
  const doomed = all(seq).filter(inside);
  if (doomed.length) {
    steps += 1;
    const MT = ppro.Constants.MediaType;
    runTransaction(project, "CutDeck: remove cut pieces", (compound) => {
      for (const kind of ["video", "audio"]) {
        const these = doomed.filter((c) => c.kind === kind);
        if (!these.length) continue;
        let added = false;
        ppro.TrackItemSelection.createEmptySelection((selection) => {
          for (const c of these) selection.addItem(c.item, true);
          added = compound.addAction(editor().createRemoveItemsAction(selection, false, kind === "video" ? MT.VIDEO : MT.AUDIO));
        });
        if (!added) throw new Error(`addAction(remove ${kind}) returned false`);
      }
    });
  }

  // 5. close the gaps, left to right so nothing lands on a piece not yet moved away.
  seq = await read();
  const moves = all(seq).map((c) => ({ c, by: shiftFor(c.start, cuts) })).filter((m) => m.by > 0n)
    .sort((x, y) => (x.c.start < y.c.start ? -1 : x.c.start > y.c.start ? 1 : 0));
  steps += tx("close gaps", moves.map(({ c, by }) => () => c.item.createMoveAction(tick(-by))));
  return steps;
}

/* The whole Route A: copy, plan, apply, verify, open. Throws before any edit on a refusal. */
async function applyNativeCut(ppro, project, source, cutsJson, resultName) {
  const cuts = cutsToTicks(cutsJson, await source.getTimebase());
  const before = await readItems(ppro, source);
  const refusal = planCutApply(before.transitions, cuts).refusal || planCutApply(before.items, cuts).refusal;
  if (refusal) throw new Error(`Cannot cut natively: ${refusal}`);

  const beforeIds = new Set((await project.getSequences()).map((s) => s.guid.toString()));
  runTransaction(project, "CutDeck: copy sequence", (compound) => {
    if (!compound.addAction(source.createCloneAction())) throw new Error("addAction(copy sequence) returned false");
  });
  const created = (await project.getSequences()).filter((s) => !beforeIds.has(s.guid.toString()));
  if (created.length !== 1) throw new Error(`Copying the sequence gave ${created.length} new sequences; nothing was cut`);
  const copy = created[0];
  const copyItem = await copy.getProjectItem();
  runTransaction(project, "CutDeck: name copy", (compound) => {
    if (!compound.addAction(copyItem.createSetNameAction(resultName))) throw new Error("addAction(rename) returned false");
  });
  // File it under CutDeck > Rough Cuts (FolderItem.createMoveItemAction d.ts:1271, called on the
  // item's current parent as alLibrary does; ProjectItem.getParentBin d.ts:2515). It is opened
  // only once cut (or failed), so Premiere does not redraw it for every edit.
  const bin = asBinLike(await getOrCreateBin(project, [CUTDECK_BIN_NAME, ROUGH_CUTS_BIN_NAME]));
  runTransaction(project, "CutDeck: file rough cut", (compound) => {
    const parent = asBinLike(copyItem.getParentBin());
    if (!compound.addAction(parent.createMoveItemAction(copyItem, bin))) throw new Error("addAction(move to bin) returned false");
  });
  const started = Date.now();
  let items, plan, steps, actual;
  try {
    items = (await readItems(ppro, copy)).items;
    plan = planCutApply(items, cuts);
    if (plan.refusal) throw new Error(`Cannot cut natively: ${plan.refusal}`);
    steps = await applyPlan(ppro, project, copy, items, cuts, toTicks(await copy.getTimebase()));
    actual = (await readItems(ppro, copy)).items;
  } finally {
    await project.openSequence(copy);
    await project.setActiveSequence(copy);
  }
  const elapsedSeconds = (Date.now() - started) / 1000;
  const problems = verifyReadBack(items, plan, actual);
  if (problems.length) {
    throw new Error(`The cut copy "${resultName}" does not match the plan (${problems.length} problem(s); first: ${problems[0]}). `
      + "It is left open for inspection; your original sequence is untouched.");
  }
  const splits = plan.edits.filter((e) => e.op === "split").length;
  return { cuts: cuts.length, removedTicks: plan.removedTicks, splits, steps, name: resultName, elapsedSeconds };
}

module.exports = { applyNativeCut, applyPlan, readItems };
