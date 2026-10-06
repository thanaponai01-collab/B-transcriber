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
   Five undo steps plus one per extra 3,000-action batch, said in the status line. */

const { runTransaction, getOrCreateBin, asBinLike, CUTDECK_BIN_NAME, ROUGH_CUTS_BIN_NAME } = require("../host/project.js");
const { TICKS_PER_SECOND, toTicks } = require("../host/ticks.js");
const { readSequence } = require("./nativeSync.js");
const { cutsToTicks, planCutApply, verifyReadBack, shiftFor, createFastShiftFor, isInsideCut, overlapsCut } = require("./cutPlanApply.js");

const CLONE_GAP = 2n * TICKS_PER_SECOND;
const MOVE_BATCH = 3000;
const SPLIT_BATCH = 3000;

const kindOf = (c) => c.kind; // "video" | "audio" from readSequence
const itemKey = (c) => `${kindOf(c)}|${c.track}|${c.start}`;
const asPlanItem = (c, extra = {}) => ({ id: itemKey(c), name: c.path ? String(c.path).split(/[\\/]/).pop() : "clip",
  mediaType: kindOf(c), track: c.track, startTicks: c.start, endTicks: c.end, inTicks: c.inPoint, ...extra });

/* Everything the planner's whole-plan refusal needs, read from the host. The refusal only
   looks at clips a cut lands inside, so speed/reversed/nested/multicam (up to 5 host calls
   each) are read for those alone; `cuts: null` skips them and the transitions entirely, for
   a read-back that only needs positions. */
async function readItems(ppro, seq, cuts) {
  const s = await readSequence(ppro, seq);
  const items = [];
  for (const c of [...s.video, ...s.audio]) {
    let speed = 1, reversed = false, isNested = false, isMulticam = false;
    if (!cuts || !overlapsCut(c.start, c.end, cuts)) { items.push(asPlanItem(c, { raw: c })); continue; }
    try { speed = await c.item.getSpeed(); } catch (_) { /* not reported: treat as normal */ }
    try { reversed = !!(await c.item.isSpeedReversed()); } catch (_) { /* idem */ }
    try {
      const pi = ppro.ClipProjectItem && ppro.ClipProjectItem.cast ? ppro.ClipProjectItem.cast(await c.item.getProjectItem()) : await c.item.getProjectItem();
      if (pi && typeof pi.isSequence === "function") isNested = !!(await pi.isSequence());
      if (pi && typeof pi.isMulticamClip === "function") isMulticam = !!(await pi.isMulticamClip());
    } catch (_) { /* graphics / adjustment layers have no clip project item */ }
    items.push(asPlanItem(c, { speed, reversed, isNested, isMulticam, raw: c }));
  }
  const transitions = [];
  if (!cuts) return { items, transitions, videoTracks: s.videoTracks, audioTracks: s.audioTracks };
  const type = ppro.Constants.TrackItemType.TRANSITION;
  for (const [kind, count, get] of [["video", s.videoTracks, (i) => seq.getVideoTrack(i)], ["audio", s.audioTracks, (i) => seq.getAudioTrack(i)]]) {
    for (let t = 0; t < count; t++) {
      const track = await get(t);
      const found = track ? (await track.getTrackItems(type, false)) || [] : [];
      if (!found.length) continue;
      const trackTransitions = await Promise.all(found.map(async (x) => {
        const [startTick, endTick] = await Promise.all([x.getStartTime(), x.getEndTime()]);
        return {
          id: `${kind}-transition-${t}`,
          name: "transition",
          mediaType: kind,
          track: t,
          isTransition: true,
          startTicks: toTicks(startTick),
          endTicks: toTicks(endTick),
          inTicks: 0n,
        };
      }));
      transitions.push(...trackTransitions);
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
async function applyPlan(ppro, project, copy, items, cuts, tpf, timed = (_, fn) => fn()) {
  const tick = (n) => ppro.TickTime.createWithTicks(n.toString());
  const editor = () => ppro.SequenceEditor.getEditor(copy);
  // Actions must be CREATED inside the transaction callback — built outside it, Premiere throws
  // "The script object is no longer valid." (live run 2026-09-24). So each step passes a list
  // of builders, not actions.
  const tx = (label, builders, { allowPartial = false } = {}) => {
    if (!builders.length) return { steps: 0, count: 0 };
    const ed = editor();
    let completed = 0;
    timed(label, () => runTransaction(project, `CutDeck: ${label}`, (compound) => {
      const len = builders.length;
      for (let i = 0; i < len; i++) {
        const build = builders[i];
        let action, added;
        // Live 2026-09-24: one clone of 7,650 in the razor step came back undefined and the same
        // cut list went through on a rerun, so an empty result is asked for once more (still inside
        // this callback, as required) before failing. The read-back still checks every piece.
        for (let attempt = 0; attempt < 2 && !action; attempt++) {
          try { action = build(ed); } catch (e) {
            if (allowPartial && i > 0 && e.message && e.message.includes("is no longer valid")) {
              // Stale handle mid-batch (live 2026-10-06, action 179 of 3000): commit what succeeded
              // so far; the caller re-reads the copy and continues with fresh handles.
              return;
            }
            const where = `${label}: action ${i + 1} of ${len}${build.what ? ` (${build.what})` : ""}`;
            throw new Error(`${where} failed to build: ${e.message}`);
          }
        }
        if (!action) {
          const where = `${label}: action ${i + 1} of ${len}${build.what ? ` (${build.what})` : ""}`;
          throw new Error(`${where}: Premiere returned no action (${action}), twice`);
        }
        try { added = compound.addAction(action); } catch (e) {
          const where = `${label}: action ${i + 1} of ${len}${build.what ? ` (${build.what})` : ""}`;
          throw new Error(`${where} was refused: ${e.message}`);
        }
        if (!added) {
          const where = `${label}: action ${i + 1} of ${len}${build.what ? ` (${build.what})` : ""}`;
          throw new Error(`${where}: addAction returned false`);
        }
        completed++;
      }
    }));
    return { steps: completed > 0 ? 1 : 0, count: completed };
  };
  // Positions only. The two reads after the razor see every piece (~8,700 on a 1,735-cut run,
  // 16 s live), so they read just what their step uses.
  const read = (fields = {}) => timed("reads", () => readSequence(ppro, copy, { paths: false, ...fields }));
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
    const dt = tick(park - it.startTicks);
    return (ed) => (ed || editor()).createCloneTrackItemAction(src.item, dt, 0, 0, false, false);
  })).steps;
  seq = await read();
  steps += tx("trim razor fillers", [...sourceOf.keys()].map((key) => {
    const f = findIn(seq, key, park);
    if (!f) throw new Error(`razor filler on ${key.replace("|", " track ")} did not land`);
    const dt = tick(f.inPoint + tpf);
    return () => f.item.createSetOutPointAction(dt);
  })).steps;

  // 3. razor: one filler clone per cut edge. Batched like step 5 (live 2026-10-01: a 55 s commit and
  // stale handles on a 16k-action run), each batch from a fresh read; the filler stays at `park`.
  const cutAt = [];
  for (const [key, at] of edges) for (const p of at) cutAt.push([key, p]);
  seq = null;
  for (let from = 0; from < cutAt.length; from += SPLIT_BATCH) {
    seq = await read();
    const fillers = new Map();
    const razor = cutAt.slice(from, from + SPLIT_BATCH).map(([key, p]) => {
      if (!fillers.has(key)) {
        const f = findIn(seq, key, park);
        if (!f || f.end - f.start !== tpf) throw new Error(`razor filler on ${key.replace("|", " track ")} is not one frame long`);
        fillers.set(key, f);
      }
      const f = fillers.get(key);
      const dt = tick(p - park);
      return Object.assign((ed) => (ed || editor()).createCloneTrackItemAction(f.item, dt, 0, 0, false, false),
        { what: `${key.replace("|", " track ")}, filler from ${f.path || "no media"}, edge at ${Number(p) / Number(TICKS_PER_SECOND)}s, offset ${p - park}` });
    });
    steps += tx("split at cut edges", razor).steps;
  }

  // 4. remove everything inside a cut, and the fillers — per media type.
  seq = await read({ inPoint: false });
  const inside = (c) => c.start >= park || isInsideCut(c.start, c.end, cuts);
  let doomed = all(seq).filter(inside);
  if (doomed.length) {
    steps += 1;
    const MT = ppro.Constants.MediaType;
    const ed = editor();
    timed("remove cut pieces", () => runTransaction(project, "CutDeck: remove cut pieces", (compound) => {
      for (const kind of ["video", "audio"]) {
        const these = doomed.filter((c) => c.kind === kind);
        if (!these.length) continue;
        let added = false;
        ppro.TrackItemSelection.createEmptySelection((selection) => {
          for (const c of these) selection.addItem(c.item, true);
          added = compound.addAction(ed.createRemoveItemsAction(selection, false, kind === "video" ? MT.VIDEO : MT.AUDIO));
        });
        if (!added) throw new Error(`addAction(remove ${kind}) returned false`);
      }
    }));
    doomed.length = 0;
    doomed = null;
  }

  // 5. close the gaps, left to right so nothing lands on a piece not yet moved away.
  seq = await read({ end: false, inPoint: false });
  const fastShift = createFastShiftFor(cuts);
  // Live 2026-10-01: one transaction of 16,506 moves failed at action 13,845 with "script object is
  // no longer valid" (handles read minutes earlier). So the moves go in batches, each from a fresh
  // read. A piece not yet moved still sits at its original start, so it is found by lane + start.
  // Live 2026-10-06: handles can still go stale mid-batch (e.g. action 179 of 3000). allowPartial
  // commits what succeeded so far, then the next iteration re-reads for fresh handles.
  const moves = all(seq).map((c) => ({ key: `${lane(c)}|${c.start}`, start: c.start, by: fastShift(c.start) })).filter((m) => m.by > 0n)
    .sort((x, y) => (x.start < y.start ? -1 : x.start > y.start ? 1 : 0));
  let at = 0;
  while (at < moves.length) {
    if (at > 0) seq = await read({ end: false, inPoint: false });
    const fresh = new Map();
    for (const c of all(seq)) {
      const k = `${lane(c)}|${c.start}`;
      const list = fresh.get(k);
      if (list) list.push(c);
      else fresh.set(k, [c]);
    }
    const batch = moves.slice(at, at + MOVE_BATCH);
    const builders = batch.map(({ key, by, start }) => {
      const list = fresh.get(key);
      const c = list && list.shift();
      if (!c) throw new Error(`close gaps: clip at ${key.replace("|", " track ")} vanished`);
      const dt = tick(-by);
      return Object.assign(() => c.item.createMoveAction(dt), {
        what: `${key.replace("|", " track ")}, shift ${-by} ticks from start ${start}`,
      });
    });
    const res = tx("close gaps", builders, { allowPartial: true });
    steps += res.steps;
    if (res.count < batch.length) console.log(`CutDeck close gaps: handle went stale after ${res.count} of ${batch.length} moves (moves done ${at + res.count} of ${moves.length})`);
    if (res.count === 0) {
      throw new Error(`close gaps: stalled at move ${at + 1} of ${moves.length}`);
    }
    at += res.count;
  }
  moves.length = 0;
  seq = null;
  return steps;
}

/* The whole Route A: copy, plan, apply, verify, open. Throws before any edit on a refusal. */
async function applyNativeCut(ppro, project, source, cutsJson, resultName) {
  // Seconds per step, summed by label, so a slow run shows where its time went.
  const timings = {};
  // Works for sync steps (transactions: errors must throw where they happen) and async reads.
  const timed = (label, fn) => {
    const t = Date.now();
    const done = () => { timings[label] = (timings[label] || 0) + (Date.now() - t) / 1000; };
    let out;
    try { out = fn(); } catch (e) { done(); throw e; }
    if (out && typeof out.then === "function") return out.finally(done);
    done();
    return out;
  };
  const cuts = cutsToTicks(cutsJson, await source.getTimebase());
  const before = await timed("read source", () => readItems(ppro, source, cuts));
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
  try {
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
    // The copy is a clone of the source, so the source read stands in for it; applyPlan finds
    // each item on the copy by position and throws if one is not there.
    const items = before.items;
    const plan = planCutApply(items, cuts);
    let steps, actual;
    try {
      steps = await applyPlan(ppro, project, copy, items, cuts, toTicks(await copy.getTimebase()), timed);
      actual = (await timed("read-back", () => readItems(ppro, copy, null))).items;
    } finally {
      await timed("open copy", async () => {
        await project.openSequence(copy);
        await project.setActiveSequence(copy);
      });
    }
    const elapsedSeconds = (Date.now() - started) / 1000;
    const problems = verifyReadBack(items, plan, actual);
    before.items = null;
    before.transitions = null;
    actual = null;
    if (problems.length) {
      // The message names only the first problem; the console gets all of them, so a failed run
      // shows whether clips are missing (overwritten) or misplaced, and on which lanes.
      const kinds = problems.reduce((n, p) => { const k = p.split(" ")[0]; n[k] = (n[k] || 0) + 1; return n; }, {});
      console.log("CutDeck read-back mismatches", kinds, problems);
      throw new Error(`The cut copy "${resultName}" does not match the plan (${problems.length} problem(s); first: ${problems[0]}). `
        + "It is left open for inspection; your original sequence is untouched.");
    }
    const splits = plan.edits.filter((e) => e.op === "split").length;
    console.log("CutDeck rough cut timings (s):", timings);
    return { cuts: cuts.length, removedTicks: plan.removedTicks, splits, steps, name: resultName, elapsedSeconds, timings };
  } catch (error) {
    // A half-cut copy must not pass for the result, nor collide with the next attempt's name.
    try {
      runTransaction(project, "CutDeck: mark failed copy", (compound) => {
        compound.addAction(copyItem.createSetNameAction(`${resultName} (FAILED)`));
      });
    } catch (_) { /* the error below is the one that matters */ }
    error.copyCreated = true;
    throw error;
  }
}

module.exports = { applyNativeCut, applyPlan, readItems };
