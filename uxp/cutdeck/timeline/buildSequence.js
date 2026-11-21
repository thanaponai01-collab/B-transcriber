/* build_sequence: build a new sequence from an item list, on a cleared copy of a base sequence.
   HKS build plan step 1e (docs/HKS_BUILD_PLAN.md). The base is never edited: it is cloned
   (its own transaction), the clone is cleared and stays closed while it is built (PREMIERE_FACTS
   "compound.addAction while the target sequence is open": BROKEN at scale), and every item is
   read back against the plan at the end.

   Args: { project (the .prproj the build is for: anything else open is refused before any edit),
   base, name, items, save (opt-in: save the project after the build) }.
   Item: { id, media (file path) | like: {kind, track, start_ticks} (an item of the base whose
   project item to use: adjustment layers have no file), in_ticks, out_ticks, at_ticks,
   v (video track index | null), a (audio track index | null), motion {PARAM_INDEX field: value},
   level (linear Volume Level), blur {blurriness} }.
   A side that is null still lands (Premiere places what the media has) on a scratch track past
   the base's last track; scratch tracks are cleared at the end.

   APIs (reference/adobe/api/premierepro.txt; PREMIERE_FACTS rows from the HKS spike 2026-11-21):
   Project.path (reads with the Windows extended prefix \\?\, PREMIERE_FACTS "Project.path"),
   Project.save (declared, not yet run live),
   Sequence.createCloneAction (own transaction), ProjectItem.createSetNameAction,
   ProjectItem.getId, ClipProjectItem.cast + createSetInOutPointsAction (own transaction: an overwrite in the same
   compound reads the old marks), SequenceEditor.createOverwriteItemAction (pass the plain
   ProjectItem; an index equal to the track count creates the track),
   TrackItemSelection.createEmptySelection + createRemoveItemsAction(sel, false, type),
   AudioClipTrackItem.getComponentChain (Volume [1] Level, linear), VideoFilterFactory.createComponent
   + VideoComponentChain.createAppendComponentAction (re-fetch after commit), ComponentParam
   createKeyframe / createSetValueAction. */

const { runTransaction } = require("../host/project.js");
const { readSequence } = require("../host/sequenceRead.js");
const { toTicks, TICKS_PER_SECOND } = require("../host/ticks.js");
const { applyMotionValues } = require("../transform/apply.js");

const BLUR = "AE.ADBE Gaussian Blur 2";
const FRAME_TICKS = TICKS_PER_SECOND / 25n; // tolerance unit for the read-back (25 fps sequences)

const norm = (path) => String(path || "").replace(/\//g, "\\").toLowerCase();
const projectFile = (path) => norm(path).replace(/^\\\\\?\\/, ""); // drop the \\?\ prefix
const secs = (ticks) => Number(ticks) / Number(TICKS_PER_SECOND);
const abs = (x) => (x < 0n ? -x : x);

async function namedSequence(ppro, project, name) {
  for (const seq of await project.getSequences()) {
    if (seq.name !== name) continue;
    const read = await readSequence(ppro, seq, { paths: true });
    if (read.video.length || read.audio.length) return { seq, read };
  }
  throw new Error(`No sequence "${name}" with clips.`);
}

function removeAll(ppro, project, editor, items, mediaType, label) {
  if (!items.length) return;
  runTransaction(project, label, (compound) => {
    let added = false;
    ppro.TrackItemSelection.createEmptySelection((selection) => {
      for (const it of items) selection.addItem(it, true);
      added = compound.addAction(editor.createRemoveItemsAction(selection, false, mediaType));
    });
    if (!added) throw new Error(`addAction(${label}) returned false`);
  });
}

async function buildSequence(ppro, { project: projectPath, base, name, items, save = false }, log = () => {}) {
  const t0 = Date.now();
  const timings = {};
  const lap = (phase) => { timings[phase] = Date.now() - t0; log(`${phase} at ${timings[phase]} ms`); };
  const project = await ppro.Project.getActiveProject();
  if (!project || projectFile(project.path) !== projectFile(projectPath)) {
    throw new Error(`The open project is ${project ? project.path : "none"}, not ${projectPath}: nothing was built.`);
  }
  const tick = (t) => ppro.TickTime.createWithTicks(BigInt(t).toString());

  // Resolve every project item before anything is edited.
  const { seq: baseSeq, read: baseRead } = await namedSequence(ppro, project, base);
  const byPath = new Map();
  for (const c of [...baseRead.video, ...baseRead.audio]) if (c.path && c.projectItem) byPath.set(norm(c.path), c.projectItem);
  const like = (ref) => [...baseRead.video, ...baseRead.audio].find((c) => c.kind === ref.kind && c.track === ref.track
    && abs(c.start - BigInt(ref.start_ticks)) <= FRAME_TICKS / 2n);
  const plan = items.map((it) => {
    const { like: ref, in_ticks: inTicks, out_ticks: outTicks, at_ticks: atTicks } = it;
    const found = it.media ? byPath.get(norm(it.media)) : (like(ref) || {}).projectItem;
    if (!found) throw new Error(`Item ${it.id}: no project item for ${it.media || JSON.stringify(ref)} in "${base}".`);
    return { ...it, projectItem: found, key: found.getId(), in: BigInt(inTicks), out: BigInt(outTicks), at: BigInt(atTicks) };
  });
  lap("resolved");

  // Clone, rename, clear. The clone is not opened.
  const before = new Set((await project.getSequences()).map((s) => s.guid.toString()));
  runTransaction(project, `CutDeck build: copy ${base}`, (c) => {
    if (!c.addAction(baseSeq.createCloneAction())) throw new Error("addAction(copy sequence) returned false");
  });
  const created = (await project.getSequences()).filter((s) => !before.has(s.guid.toString()));
  if (created.length !== 1) throw new Error(`Copying gave ${created.length} new sequences.`);
  const seq = created[0];
  const seqItem = await seq.getProjectItem();
  runTransaction(project, "CutDeck build: name", (c) => {
    if (!c.addAction(seqItem.createSetNameAction(name))) throw new Error("addAction(rename) returned false");
  });
  const editor = ppro.SequenceEditor.getEditor(seq);
  const fresh = await readSequence(ppro, seq, { paths: false });
  removeAll(ppro, project, editor, [...fresh.video, ...fresh.audio].map((c) => c.item), ppro.Constants.MediaType.ANY, "CutDeck build: clear");
  const scratch = { v: fresh.videoTracks, a: fresh.audioTracks };
  lap("cleared");

  // Place: In/Out (only when it changes) in one transaction, the overwrite in the next.
  const marks = new Map(); // ProjectItem id -> {clip, in, out} before the first change, to restore
  const current = new Map();
  // Restored on a throw too: a second run would read changed marks as the originals.
  const restoreMarks = () => {
    if (!marks.size) return;
    runTransaction(project, "CutDeck build: restore source marks", (c) => {
      for (const m of marks.values()) {
        if (!c.addAction(m.clip.createSetInOutPointsAction(m.in, m.out))) throw new Error("restoring a source In/Out was refused");
      }
    });
  };
  try {
    for (let i = 0; i < plan.length; i++) {
      const it = plan[i];
      const clip = ppro.ClipProjectItem.cast(it.projectItem);
      if (!marks.has(it.key)) {
        marks.set(it.key, { clip, in: await clip.getInPoint(ppro.Constants.MediaType.VIDEO), out: await clip.getOutPoint(ppro.Constants.MediaType.VIDEO) });
      }
      const now = current.get(it.key);
      if (!now || now.in !== it.in || now.out !== it.out) {
        runTransaction(project, `CutDeck build: marks ${it.id}`, (c) => {
          if (!c.addAction(clip.createSetInOutPointsAction(tick(it.in), tick(it.out)))) throw new Error(`set In/Out refused (${it.id})`);
        });
        current.set(it.key, { in: it.in, out: it.out });
      }
      runTransaction(project, `CutDeck build: place ${it.id}`, (c) => {
        const v = it.v === null || it.v === undefined ? scratch.v : it.v;
        const a = it.a === null || it.a === undefined ? scratch.a : it.a;
        if (!c.addAction(editor.createOverwriteItemAction(it.projectItem, tick(it.at), v, a))) throw new Error(`place refused (${it.id})`);
      });
      if ((i + 1) % 50 === 0) log(`placed ${i + 1} of ${plan.length}`);
    }
  } catch (e) {
    try { restoreMarks(); } catch (r) { log(`restoring source marks failed too: ${r.message}`); }
    throw e;
  }
  restoreMarks();
  lap("placed");

  let after = await readSequence(ppro, seq, { paths: false });
  removeAll(ppro, project, editor, after.video.filter((c) => c.track >= scratch.v).map((c) => c.item), ppro.Constants.MediaType.VIDEO, "CutDeck build: clear scratch video");
  removeAll(ppro, project, editor, after.audio.filter((c) => c.track >= scratch.a).map((c) => c.item), ppro.Constants.MediaType.AUDIO, "CutDeck build: clear scratch audio");
  after = await readSequence(ppro, seq, { paths: false });
  lap("scratch cleared");

  // Match each plan side to what landed (same track, start within half a frame).
  const find = (kind, track, at) => (kind === "video" ? after.video : after.audio)
    .find((c) => c.track === track && abs(c.start - at) <= FRAME_TICKS / 2n);
  const mismatches = [];
  const landed = [];
  for (const it of plan) {
    for (const [kind, track] of [["video", it.v], ["audio", it.a]]) {
      if (track === null || track === undefined) continue;
      const got = find(kind, track, it.at);
      const want = { start: it.at, end: it.at + (it.out - it.in), in: it.in };
      if (!got) { mismatches.push({ id: it.id, kind, track, problem: "missing", at: secs(it.at) }); continue; }
      const off = { start: abs(got.start - want.start), end: abs(got.end - want.end), in: abs(got.inPoint - want.in) };
      const worst = [off.start, off.end, off.in].reduce((m, x) => (x > m ? x : m), 0n);
      if (worst > FRAME_TICKS) {
        mismatches.push({ id: it.id, kind, track, at: secs(it.at), off_s: { start: secs(off.start), end: secs(off.end), in: secs(off.in) } });
      }
      landed.push({ it, kind, got });
    }
  }
  lap("read back");

  // Motion, all clips in one transaction (transform/apply.js).
  const motion = landed.filter((l) => l.kind === "video" && l.it.motion);
  if (motion.length) {
    await applyMotionValues(ppro, project, "CutDeck build: motion",
      motion.map((l) => ({ item: l.got.item, name: l.it.id, values: l.it.motion })));
  }
  lap("motion");

  // Audio levels, one transaction: Volume component, param 1 Level (linear).
  const levelled = landed.filter((l) => l.kind === "audio" && typeof l.it.level === "number");
  const levelParams = [];
  for (const l of levelled) {
    const chain = await l.got.item.getComponentChain();
    let param = null;
    for (let i = 0; i < chain.getComponentCount() && !param; i++) {
      const comp = chain.getComponentAtIndex(i);
      if ((await comp.getDisplayName()) === "Volume") param = comp.getParam(1);
    }
    if (!param) throw new Error(`No Volume Level on ${l.it.id}.`);
    levelParams.push({ param, value: l.it.level });
  }
  if (levelParams.length) {
    runTransaction(project, "CutDeck build: levels", (c) => {
      for (const { param, value } of levelParams) {
        if (!c.addAction(param.createSetValueAction(param.createKeyframe(value), true))) throw new Error("level refused");
      }
    });
  }
  lap("levels");

  // Blur: append Gaussian Blur to each, commit, then set Blurriness (the factory's component has no params).
  const blurred = landed.filter((l) => l.kind === "video" && l.it.blur);
  if (blurred.length) {
    const chains = [];
    for (const l of blurred) chains.push({ l, chain: await l.got.item.getComponentChain(), comp: await ppro.VideoFilterFactory.createComponent(BLUR) });
    runTransaction(project, "CutDeck build: blur", (c) => {
      for (const { chain, comp } of chains) if (!c.addAction(chain.createAppendComponentAction(comp))) throw new Error("append blur refused");
    });
    const params = [];
    for (const l of blurred) {
      const chain = await l.got.item.getComponentChain();
      for (let i = 0; i < chain.getComponentCount(); i++) {
        const comp = chain.getComponentAtIndex(i);
        if ((await comp.getMatchName()) === BLUR) params.push({ param: comp.getParam(0), value: l.it.blur.blurriness });
      }
    }
    runTransaction(project, "CutDeck build: blurriness", (c) => {
      for (const { param, value } of params) if (!c.addAction(param.createSetValueAction(param.createKeyframe(value), true))) throw new Error("blurriness refused");
    });
  }
  lap("blur");

  const saved = save ? await project.save() : false;

  return {
    sequence: name,
    items: plan.length,
    placed: { video: after.video.length, audio: after.audio.length },
    motion: motion.length,
    levels: levelParams.length,
    blur: blurred.length,
    mismatches: mismatches.length,
    first_mismatches: mismatches.slice(0, 40),
    saved,
    timings_ms: timings,
  };
}

module.exports = { buildSequence };
