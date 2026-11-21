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
   level (linear Volume Level), blur {blurriness}, import (optional, default false) }.
   import: true = `media` is a file no sequence uses yet (a still PNG for a frame hold, a title
   PNG); it is imported into CutDeck > Frame Holds before anything is read (see below).
   Stills: Premiere places a still one frame short of out - in (live 2026-11-21, 26-74 and 60
   frame stills read back one frame short), so a caller that needs a still to end on an exact
   frame asks for one frame more, or lays a last piece ending on that frame.
   disable_tracks (optional) {video: [index], audio: [index]}: every clip on those tracks of the
   built sequence is disabled at the end, like the layers a user keeps but switches off
   (VideoClipTrackItem / AudioClipTrackItem.createSetDisabledAction, one transaction).
   mark_whole (optional, default false): set the built sequence's In/Out to 0 .. its last item's
   end, so an In/Out export covers the whole build; the clone otherwise keeps the base's marks
   (Sequence.createSetInPointAction / createSetOutPointAction, read back with getIn/OutPoint).

   into (optional, default false): edit `base` itself instead of a cleared clone (`name` must equal
   `base`). Used on a fresh cut copy (cut_copy) so every synced layer, effect and disabled state
   the user built is kept. Extra steps, in this order, before placing items:
     settings_from: name of a sequence whose settings (frame size) to apply
       (Sequence.getSettings + createSetSettingsAction);
     steps: [{op, from_ticks, to_ticks, dt_ticks?}], run in order, each on every clip of every
       track whose start is in [from, to), each its own transaction:
       lift: remove without ripple, leaving a hole (createRemoveItemsAction, ripple false);
       clone: copy each clip by dt onto its own track, overwriting (createCloneTrackItemAction,
         isInsert false; effects kept, pieces unlinked; the disabled state is not relied on);
       move: shift by dt (createMoveAction, relative), far end first. Live 2026-11-21: a block
         moved backward past other clips rendered black on video (audio fine), so bring a later
         block forward with clone + lift instead.
   and after placing:
     restyle: [{kind, track, from_ticks, to_ticks, enabled?, motion?}]: clips on that track whose
       start is in [from, to) are enabled/disabled and get the Motion values.
   media_from (optional): more sequence names whose clips' project items items may use.
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
const { asBinLike } = require("../host/project.js");
const { getOrCreateFrameHoldBin, locateAndOrganizeImportedHoldItem, FRAME_HOLD_BIN_NAME } = require("./frameHold.js");

const BLUR = "AE.ADBE Gaussian Blur 2";
const FRAME_TICKS = TICKS_PER_SECOND / 25n; // tolerance unit for the read-back (25 fps sequences)

const norm = (path) => String(path || "").replace(/\//g, "\\").toLowerCase();
const projectFile = (path) => norm(path).replace(/^\\\\\?\\/, ""); // drop the \\?\ prefix
const secs = (ticks) => Number(ticks) / Number(TICKS_PER_SECOND);
const abs = (x) => (x < 0n ? -x : x);

/* allowEmpty: the base and the settings donor may be an empty sequence (a fresh 9:16 one made by
   create_sequence); items then find their media through media_from. */
async function namedSequence(ppro, project, name, allowEmpty = false) {
  let empty = null;
  for (const seq of await project.getSequences()) {
    if (seq.name !== name) continue;
    const read = await readSequence(ppro, seq, { paths: true });
    if (read.video.length || read.audio.length) return { seq, read };
    empty = empty || { seq, read };
  }
  if (allowEmpty && empty) return empty;
  throw new Error(`No sequence "${name}" with clips.`);
}

/* Read-only lookup of an imported file in CutDeck > Frame Holds by its name (Premiere names the
   item after the file, with or without the extension). Never edits the project, so it is safe
   to call after sequences have been read. Null when it is not there. */
async function holdBinItem(project, fileName) {
  const bin = asBinLike(await getOrCreateFrameHoldBin(project));
  const stem = fileName.replace(/\.[^.]+$/, "");
  const items = (bin && typeof bin.getItems === "function" && (await bin.getItems())) || [];
  return items.find((it) => it.type !== 2 && (it.name === fileName || it.name === stem)) || null;
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

/* A failed build says where it stopped. `into` steps edit the base itself and are not undone on a
   throw, so a retry on the same copy runs them twice (live 2026-11-21: the hook was lifted twice and
   the end moved back twice, 2.47 s lost). When any step already ran, the error says to build again
   on a fresh copy. */
async function buildSequence(ppro, args, log = () => {}) {
  const state = { phase: "start", stepsDone: 0 };
  try {
    return await buildSequenceInner(ppro, args, log, state);
  } catch (e) {
    const total = (args.steps || []).length;
    const warn = state.stepsDone
      ? ` ${state.stepsDone} of ${total} steps were already applied to "${args.base}": build again on a fresh copy, never on this one.`
      : "";
    const err = new Error(`${e.message} (build stopped after phase "${state.phase}".${warn})`);
    err.cause = e;
    throw err;
  }
}

async function buildSequenceInner(ppro, { project: projectPath, base, name, items, save = false, disable_tracks: disableTracks = null, mark_whole: markWhole = false,
  into = false, settings_from: settingsFrom = null, steps = [], restyle = [], media_from: mediaFrom = [] }, log, state) {
  const t0 = Date.now();
  const timings = {};
  const lap = (phase) => { timings[phase] = Date.now() - t0; state.phase = phase; log(`${phase} at ${timings[phase]} ms`); };
  const project = await ppro.Project.getActiveProject();
  if (!project || projectFile(project.path) !== projectFile(projectPath)) {
    throw new Error(`The open project is ${project ? project.path : "none"}, not ${projectPath}: nothing was built.`);
  }
  const tick = (t) => ppro.TickTime.createWithTicks(BigInt(t).toString());

  /* `import: true` items are files no sequence uses yet: still PNGs standing in for frame holds
     (made outside Premiere from a broadcast frame) and burned-in titles. The UXP API cannot
     freeze a frame or make a Graphic on the timeline, so a build brings the file in itself.
     Order matters: any project change (importFiles, or the "move into bin" transaction that
     locateAndOrganizeImportedHoldItem may run) invalidates script objects read before it ("The
     script object is no longer valid", live 2026-11-21, twice). So every import and bin move
     happens here, before anything is read; after the reads below, imported items are only
     looked up read-only (holdBinItem). A file already in the bin is reused, never imported twice. */
  const importNames = new Map(); // norm(path) -> file name
  for (const path of new Set(items.filter((it) => it.media && it.import).map((it) => it.media))) {
    const fileName = path.split(/[\\/]/).pop();
    if (!(await holdBinItem(project, fileName))) {
      const rawBin = await getOrCreateFrameHoldBin(project);
      const ok = await project.importFiles([path], true, rawBin, false);
      const placed = await locateAndOrganizeImportedHoldItem(project, rawBin, asBinLike(rawBin), fileName, path, ppro);
      if (!ok || !placed) throw new Error(`Import of ${path} failed (importFiles ${ok}): nothing was built.`);
    }
    importNames.set(norm(path), fileName);
  }
  if (importNames.size) lap("imported");

  // Resolve every project item before anything is edited.
  if (into && name !== base) throw new Error(`into edits "${base}" itself: name must be "${base}" too.`);
  const { seq: baseSeq, read: baseRead } = await namedSequence(ppro, project, base, true);
  const byPath = new Map();
  for (const [key, fileName] of importNames) {
    const item = await holdBinItem(project, fileName);
    if (!item) throw new Error(`${fileName} is not in CutDeck > ${FRAME_HOLD_BIN_NAME} after import: nothing was built.`);
    byPath.set(key, item);
  }
  for (const c of [...baseRead.video, ...baseRead.audio]) if (c.path && c.projectItem) byPath.set(norm(c.path), c.projectItem);
  for (const other of mediaFrom) {
    const { read } = await namedSequence(ppro, project, other);
    for (const c of [...read.video, ...read.audio]) if (c.path && c.projectItem && !byPath.has(norm(c.path))) byPath.set(norm(c.path), c.projectItem);
  }
  const like = (ref) => [...baseRead.video, ...baseRead.audio].find((c) => c.kind === ref.kind && c.track === ref.track
    && abs(c.start - BigInt(ref.start_ticks)) <= FRAME_TICKS / 2n);
  const plan = items.map((it) => {
    const { like: ref, in_ticks: inTicks, out_ticks: outTicks, at_ticks: atTicks } = it;
    const found = it.media ? byPath.get(norm(it.media)) : (like(ref) || {}).projectItem;
    if (!found) throw new Error(`Item ${it.id}: no project item for ${it.media || JSON.stringify(ref)} in "${base}".`);
    return { ...it, projectItem: found, key: found.getId(), in: BigInt(inTicks), out: BigInt(outTicks), at: BigInt(atTicks) };
  });
  lap("resolved");

  let seq, editor, scratch;
  if (into) {
    seq = baseSeq;
    editor = ppro.SequenceEditor.getEditor(seq);
    if (settingsFrom) {
      const { seq: from } = await namedSequence(ppro, project, settingsFrom, true);
      const settings = await from.getSettings();
      runTransaction(project, `CutDeck build: settings from ${settingsFrom}`, (c) => {
        if (!c.addAction(seq.createSetSettingsAction(settings))) throw new Error("settings refused");
      });
    }
    lap("settings");
    for (const st of steps) {
      const from = BigInt(st.from_ticks), to = BigInt(st.to_ticks), dt = BigInt(st.dt_ticks || "0");
      const now = await readSequence(ppro, seq, { paths: false });
      const inRange = (c) => c.start >= from && c.start < to;
      const span = `${secs(from)}-${secs(to)} s`;
      if (st.op === "lift") {
        removeAll(ppro, project, editor, now.video.filter(inRange).map((c) => c.item), ppro.Constants.MediaType.VIDEO, `CutDeck build: lift video ${span}`);
        removeAll(ppro, project, editor, now.audio.filter(inRange).map((c) => c.item), ppro.Constants.MediaType.AUDIO, `CutDeck build: lift audio ${span}`);
      } else if (st.op === "clone") {
        const items = [...now.video, ...now.audio].filter(inRange);
        runTransaction(project, `CutDeck build: clone ${span} by ${secs(dt)} s`, (c) => {
          for (const { item } of items) {
            if (!c.addAction(editor.createCloneTrackItemAction(item, tick(dt), 0, 0, false, false))) throw new Error("clone refused");
          }
        });
      } else if (st.op === "move") {
        const moving = [...now.video, ...now.audio].filter(inRange)
          .sort((a, b) => (dt > 0n ? (b.start > a.start ? 1 : -1) : (a.start > b.start ? 1 : -1)));
        runTransaction(project, `CutDeck build: move ${span} by ${secs(dt)} s`, (c) => {
          for (const { item } of moving) if (!c.addAction(item.createMoveAction(tick(dt)))) throw new Error("move refused");
        });
      } else {
        throw new Error(`Unknown step ${st.op}`);
      }
      state.stepsDone += 1;
    }
    lap("steps");
    // Scratch past every track an item names, so clearing it never touches a placed side.
    const now = await readSequence(ppro, seq, { paths: false });
    const top = (key, n) => plan.reduce((m, it) => (Number.isInteger(it[key]) && it[key] + 1 > m ? it[key] + 1 : m), n);
    scratch = { v: top("v", now.videoTracks), a: top("a", now.audioTracks) };
  } else {
    // Clone, rename, clear. The clone is not opened.
    const before = new Set((await project.getSequences()).map((s) => s.guid.toString()));
    runTransaction(project, `CutDeck build: copy ${base}`, (c) => {
      if (!c.addAction(baseSeq.createCloneAction())) throw new Error("addAction(copy sequence) returned false");
    });
    const created = (await project.getSequences()).filter((s) => !before.has(s.guid.toString()));
    if (created.length !== 1) throw new Error(`Copying gave ${created.length} new sequences.`);
    seq = created[0];
    const seqItem = await seq.getProjectItem();
    runTransaction(project, "CutDeck build: name", (c) => {
      if (!c.addAction(seqItem.createSetNameAction(name))) throw new Error("addAction(rename) returned false");
    });
    editor = ppro.SequenceEditor.getEditor(seq);
    const fresh = await readSequence(ppro, seq, { paths: false });
    removeAll(ppro, project, editor, [...fresh.video, ...fresh.audio].map((c) => c.item), ppro.Constants.MediaType.ANY, "CutDeck build: clear");
    scratch = { v: fresh.videoTracks, a: fresh.audioTracks };
  }
  lap("cleared");

  // The settings and step transactions above changed the project: take fresh handles for the
  // imported items, read-only, so a placement never uses one that went stale.
  for (const it of plan) {
    if (!it.import) continue;
    const item = await holdBinItem(project, it.media.split(/[\\/]/).pop());
    if (!item) throw new Error(`Item ${it.id}: ${it.media} left CutDeck > ${FRAME_HOLD_BIN_NAME} during the build.`);
    it.projectItem = item;
  }

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

  // Restyle clips already on the sequence (into mode): enable/disable, Motion.
  let restyled = 0;
  if (restyle.length) {
    const now = await readSequence(ppro, seq, { paths: false });
    const enables = [];
    const motions = [];
    for (const r of restyle) {
      const from = BigInt(r.from_ticks), to = BigInt(r.to_ticks);
      const hit = (r.kind === "video" ? now.video : now.audio).filter((c) => c.track === r.track && c.start >= from && c.start < to);
      for (const c of hit) {
        if (typeof r.enabled === "boolean") enables.push({ item: c.item, disabled: !r.enabled });
        if (r.motion && r.kind === "video") motions.push({ item: c.item, name: `restyle V${r.track + 1}@${secs(c.start)}`, values: r.motion });
      }
      restyled += hit.length;
    }
    if (enables.length) {
      runTransaction(project, "CutDeck build: restyle enable", (c) => {
        for (const e of enables) if (!c.addAction(e.item.createSetDisabledAction(e.disabled))) throw new Error("enable refused");
      });
    }
    if (motions.length) await applyMotionValues(ppro, project, "CutDeck build: restyle motion", motions);
    after = await readSequence(ppro, seq, { paths: false });
  }
  lap("restyled");

  // Disable whole tracks (layers kept but switched off), one transaction.
  const off = disableTracks ? [
    ...after.video.filter((c) => (disableTracks.video || []).includes(c.track)),
    ...after.audio.filter((c) => (disableTracks.audio || []).includes(c.track)),
  ] : [];
  if (off.length) {
    runTransaction(project, "CutDeck build: disable tracks", (c) => {
      for (const { item } of off) if (!c.addAction(item.createSetDisabledAction(true))) throw new Error("disable refused");
    });
  }
  lap("disabled");

  let marked = null;
  if (markWhole) {
    const end = [...after.video, ...after.audio].reduce((m, c) => (c.end > m ? c.end : m), 0n);
    runTransaction(project, "CutDeck build: In/Out", (c) => {
      if (!c.addAction(seq.createSetInPointAction(tick(0n))) || !c.addAction(seq.createSetOutPointAction(tick(end)))) {
        throw new Error("setting In/Out refused");
      }
    });
    marked = { in_s: secs(BigInt((await seq.getInPoint()).ticks)), out_s: secs(BigInt((await seq.getOutPoint()).ticks)) };
  }
  lap("marked");

  const saved = save ? await project.save() : false;

  return {
    sequence: name,
    items: plan.length,
    placed: { video: after.video.length, audio: after.audio.length },
    motion: motion.length,
    levels: levelParams.length,
    blur: blurred.length,
    disabled: off.length,
    restyled,
    marked,
    mismatches: mismatches.length,
    first_mismatches: mismatches.slice(0, 40),
    saved,
    timings_ms: timings,
  };
}

module.exports = { buildSequence };
