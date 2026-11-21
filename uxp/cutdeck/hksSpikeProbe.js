/* HKS build plan Phase 1: timeline-building spike (docs/HKS_BUILD_PLAN.md 1a-1d).
   One probe per unknown. Every probe refuses to run unless the active project is the spike copy
   (test_projects/hks_spike/hks_spike.prproj), works on clones of the 20261120 sequences, reads
   its result back and, where a picture is the proof, exports a frame next to the project
   (CutDeck/ folder) for Python to compare. Nothing here is product code.

   APIs, each confirmed in reference/adobe/api/premierepro.txt (PREMIERE_FACTS rows named where
   one exists): Project.getActiveProject / getSequences / path / createSequenceFromMedia,
   Sequence.createCloneAction (CATCH: own transaction) / getProjectItem / getEndTime,
   ProjectItem.createSetNameAction, ClipProjectItem.cast / createSetInOutPointsAction /
   getInPoint / getOutPoint, SequenceEditor.getEditor / createOverwriteItemAction (WORKS) /
   createCloneTrackItemAction (CATCH) / createRemoveItemsAction (WORKS),
   TrackItemSelection.createEmptySelection, VideoClipTrackItem.createSetEndAction /
   getComponentChain / getProjectItem, AudioClipTrackItem.getComponentChain / getName,
   VideoFilterFactory.createComponent (CATCH: re-fetch after commit),
   VideoComponentChain.createAppendComponentAction, Component.getParam / getParamCount /
   getDisplayName / getMatchName, ComponentParam.createKeyframe / createSetValueAction /
   getStartValue / displayName, Exporter.exportSequenceFrame (CATCH: resolves before the file). */

const { runTransaction } = require("./host/project.js");
const { readSequence } = require("./host/sequenceRead.js");
const { toTicks, TICKS_PER_SECOND } = require("./host/ticks.js");
const { waitForFile } = require("./host/files.js");
const { unwrapKeyframeValue } = require("./host/components.js");
const { getHoldExportFolder } = require("./timeline/frameHold.js");
const { applyMotionValues } = require("./transform/apply.js");
const { readTransform } = require("./transform/params.js");

const SPIKE_PROJECT = /hks_spike\.prproj$/i;
const YT = "1 YOUTUBE D1";
const FOOTAGE = "HKS Facebook 201169 Full.mp4";
const BGM = "[BGM]Where Everything Began.wav";

const secs = (ticks) => Number(ticks) / Number(TICKS_PER_SECOND);
const ticksOf = (s) => BigInt(Math.round(s * Number(TICKS_PER_SECOND)));
const baseName = (p) => String(p || "").split(/[\\/]/).pop();

// Premiere's own errors ("Invalid parameter.") don't say which call failed: every transaction
// goes through tx(), and each probe's error names the last step it reached.
let lastStep = "start";
const step = (name) => { lastStep = name; };
function tx(project, label, build) {
  step(label);
  try {
    runTransaction(project, label, build);
  } catch (e) {
    throw new Error(`${label}: ${e.message || e}`);
  }
}
const guarded = (fn) => async (ppro) => {
  lastStep = "start";
  try {
    return await fn(ppro);
  } catch (e) {
    throw new Error(`${e.message || e} [last step: ${lastStep}]`);
  }
};

async function spikeProject(ppro) {
  const project = await ppro.Project.getActiveProject();
  if (!project || !SPIKE_PROJECT.test(String(project.path || ""))) {
    throw new Error(`Refused: the active project is "${project && project.path}", not the hks_spike.prproj copy.`);
  }
  return project;
}

// The named sequence with clips (the project also holds empty template copies of the same name).
async function sequenceNamed(ppro, project, name) {
  for (const seq of await project.getSequences()) {
    if (seq.name !== name) continue;
    const read = await readSequence(ppro, seq, { paths: false });
    if (read.video.length) return seq;
  }
  throw new Error(`No sequence "${name}" with clips in the spike project.`);
}

async function cloneAs(project, source, name) {
  const before = new Set((await project.getSequences()).map((s) => s.guid.toString()));
  tx(project, `HKS spike: copy ${source.name}`, (compound) => {
    if (!compound.addAction(source.createCloneAction())) throw new Error("addAction(copy sequence) returned false");
  });
  const created = (await project.getSequences()).filter((s) => !before.has(s.guid.toString()));
  if (created.length !== 1) throw new Error(`Copying gave ${created.length} new sequences.`);
  const item = await created[0].getProjectItem();
  tx(project, "HKS spike: name copy", (compound) => {
    if (!compound.addAction(item.createSetNameAction(name))) throw new Error("addAction(rename) returned false");
  });
  return created[0];
}

const plain = (clips) => clips.map((c) => ({ track: c.track + 1, start: secs(c.start), end: secs(c.end), in: secs(c.inPoint) }));
const key = (c) => `${c.kind}|${c.track}|${c.start}|${c.end}|${c.inPoint}`;

async function exportFrame(ppro, project, seq, at, name) {
  const { folder, folderPath } = await getHoldExportFolder(project);
  const ok = await ppro.Exporter.exportSequenceFrame(seq, ppro.TickTime.createWithTicks(ticksOf(at).toString()),
    name, folderPath, 1920, 1080);
  if (!ok) throw new Error(`exportSequenceFrame(${name}) returned false`);
  await waitForFile(folder, name, { timeoutMs: 20000, intervalMs: 50, stablePolls: 3 });
  return `${folderPath}\\${name}`;
}

function selectAndRemove(ppro, project, editor, items, mediaType, label) {
  tx(project, label, (compound) => {
    let added = false;
    ppro.TrackItemSelection.createEmptySelection((selection) => {
      for (const it of items) selection.addItem(it, true);
      added = compound.addAction(editor.createRemoveItemsAction(selection, false, mediaType));
    });
    if (!added) throw new Error(`addAction(${label}) returned false`);
  });
}

async function components(chain) {
  const out = [];
  for (let i = 0; i < chain.getComponentCount(); i++) {
    const c = chain.getComponentAtIndex(i);
    const params = [];
    for (let p = 0; p < c.getParamCount(); p++) {
      const param = c.getParam(p);
      let value = null;
      try { value = unwrapKeyframeValue(await param.getStartValue()); } catch (e) { value = `error: ${e.message || e}`; }
      params.push({ index: p, name: param.displayName, value });
    }
    out.push({ index: i, component: c, displayName: await c.getDisplayName(), matchName: await c.getMatchName(), params });
  }
  return out;
}
const describe = (comps) => comps.map(({ component, ...rest }) => rest);

/* 1a: a source range, video only, as a cover on a new top track, then an insert zoom. */
const COVER = { srcIn: 600, srcOut: 604, at: 100, scale: 300, position: { x: 0.45, y: 0.4 } };

async function probeCover(ppro) {
  const project = await spikeProject(ppro);
  const copy = await cloneAs(project, await sequenceNamed(ppro, project, YT), "HKS spike 1a cover");
  const editor = ppro.SequenceEditor.getEditor(copy);
  const tick = (s) => ppro.TickTime.createWithTicks(ticksOf(s).toString());
  step("read copy");
  const before = await readSequence(ppro, copy, { paths: true });
  const lead = before.video.find((c) => baseName(c.path) === FOOTAGE);
  if (!lead) throw new Error(`No ${FOOTAGE} clip on the copy.`);
  step("source project item");
  const projectItem = await lead.item.getProjectItem();
  const clipItem = ppro.ClipProjectItem.cast(projectItem);
  step("source marks");
  const marks = { in: await clipItem.getInPoint(ppro.Constants.MediaType.VIDEO), out: await clipItem.getOutPoint(ppro.Constants.MediaType.VIDEO) };
  const vTrack = before.videoTracks;
  const report = { step: "1a", sequence: copy.name, cover: COVER, videoTrack: vTrack + 1 };

  // In/Out on the project item first, in its own transaction (PREMIERE_FACTS "State inside one compound").
  tx(project, "HKS spike 1a: source range", (c) => {
    if (!c.addAction(clipItem.createSetInOutPointsAction(tick(COVER.srcIn), tick(COVER.srcOut)))) throw new Error("set In/Out refused");
  });
  // Live 2026-11-21: audio index -1 is accepted but lands the audio on A1, over the dialogue.
  // So the audio goes to a new empty track (index = track count) and is removed from there.
  try {
    tx(project, "HKS spike 1a: place on new tracks", (c) => {
      if (!c.addAction(editor.createOverwriteItemAction(projectItem, tick(COVER.at), vTrack, before.audioTracks))) throw new Error("refused");
    });
  } finally {
    tx(project, "HKS spike 1a: restore source marks", (c) => {
      c.addAction(clipItem.createSetInOutPointsAction(marks.in, marks.out));
    });
  }

  let after = await readSequence(ppro, copy, { paths: false });
  const old = new Set([...before.video, ...before.audio].map(key));
  const newVideo = after.video.filter((c) => !old.has(key(c)));
  const newAudio = after.audio.filter((c) => !old.has(key(c)));
  report.placedVideo = plain(newVideo);
  report.placedAudio = plain(newAudio);
  if (newAudio.some((c) => c.track < before.audioTracks)) throw new Error(`Audio landed on an existing track: ${JSON.stringify(report.placedAudio)}`);
  if (newAudio.length) {
    selectAndRemove(ppro, project, editor, newAudio.map((c) => c.item), ppro.Constants.MediaType.AUDIO, "HKS spike 1a: drop placed audio");
    after = await readSequence(ppro, copy, { paths: false });
  }
  const audioNow = new Set(after.audio.map(key));
  report.audioUnchanged = before.audio.every((c) => audioNow.has(key(c))) && after.audio.length === before.audio.length;
  if (newVideo.length !== 1) throw new Error(`Expected one placed video item, found ${newVideo.length}: ${JSON.stringify(report)}`);

  const placed = newVideo[0];
  step("read motion");
  report.motionBefore = await readTransform(placed.item);
  await applyMotionValues(ppro, project, "HKS spike 1a: insert zoom", [{ item: placed.item, name: "cover", values: { scale: COVER.scale, position: COVER.position } }]);
  report.motionAfter = await readTransform(placed.item);
  const frame = secs(placed.start) + 1;
  step("export frame");
  report.frame = { at: frame, sourceAt: secs(placed.inPoint) + 1, file: await exportFrame(ppro, project, copy, frame, "hks1a_cover.png") };
  return report;
}

/* 1b: a blur limited to a box, two ways. A: clone a mask-limited YT blur item (V8) into a gap.
   B: the same Adjustment Layer project item placed fresh, Gaussian Blur appended, Motion crop. */
const BLUR = { cloneFrom: 290.96, shift: 80, track: 10, freshAt: 380, freshLen: 4,
  crop: { cropLeft: 0, cropTop: 0, cropRight: 72, cropBottom: 82 }, blurriness: 60 };

async function probeBlur(ppro) {
  const project = await spikeProject(ppro);
  const copy = await cloneAs(project, await sequenceNamed(ppro, project, YT), "HKS spike 1b blur");
  const editor = ppro.SequenceEditor.getEditor(copy);
  const tick = (s) => ppro.TickTime.createWithTicks(ticksOf(s).toString());
  const report = { step: "1b", sequence: copy.name, blur: BLUR };
  const before = await readSequence(ppro, copy, { paths: false });
  const source = before.video.find((c) => c.track === 7 && Math.abs(secs(c.start) - BLUR.cloneFrom) < 0.02);
  if (!source) throw new Error(`No V8 blur item at ${BLUR.cloneFrom} s.`);
  const target = BLUR.track;
  if (before.video.some((c) => c.track === target)) throw new Error(`V${target + 1} is not empty on the copy.`);
  const cloneAt = BLUR.cloneFrom + BLUR.shift;
  report.before = {
    clone: await exportFrame(ppro, project, copy, cloneAt + 1, "hks1b_before_clone.png"),
    fresh: await exportFrame(ppro, project, copy, BLUR.freshAt + 1, "hks1b_before_fresh.png"),
  };

  // A: clone (an Action, not the item: re-read to find it, PREMIERE_FACTS createCloneTrackItemAction).
  tx(project, "HKS spike 1b: clone blur", (c) => {
    if (!c.addAction(editor.createCloneTrackItemAction(source.item, tick(BLUR.shift), target - source.track, 0, false, false))) throw new Error("clone refused");
  });
  let after = await readSequence(ppro, copy, { paths: false });
  const clone = after.video.filter((c) => c.track === target);
  report.clone = plain(clone);
  report.cloneComponents = clone.length ? describe(await components(await clone[0].item.getComponentChain())) : null;

  // B: fresh Adjustment Layer, video only, trimmed, Gaussian Blur appended then set, Motion crop.
  const alItem = await source.item.getProjectItem();
  tx(project, "HKS spike 1b: place adjustment layer", (c) => {
    if (!c.addAction(editor.createOverwriteItemAction(alItem, tick(BLUR.freshAt), target, -1))) throw new Error("place refused");
  });
  after = await readSequence(ppro, copy, { paths: false });
  const fresh = after.video.find((c) => c.track === target && Math.abs(secs(c.start) - BLUR.freshAt) < 0.02);
  if (!fresh) throw new Error(`The fresh adjustment layer did not land: ${JSON.stringify(plain(after.video.filter((c) => c.track === target)))}`);
  tx(project, "HKS spike 1b: trim adjustment layer", (c) => {
    if (!c.addAction(fresh.item.createSetEndAction(tick(BLUR.freshAt + BLUR.freshLen)))) throw new Error("trim refused");
  });
  const blur = await ppro.VideoFilterFactory.createComponent("AE.ADBE Gaussian Blur 2");
  const chain = await fresh.item.getComponentChain();
  tx(project, "HKS spike 1b: append Gaussian Blur", (c) => {
    if (!c.addAction(chain.createAppendComponentAction(blur))) throw new Error("append refused");
  });
  const comps = await components(await fresh.item.getComponentChain());
  const gb = comps.find((c) => c.matchName === "AE.ADBE Gaussian Blur 2");
  if (!gb) throw new Error(`Gaussian Blur not in the chain: ${JSON.stringify(describe(comps))}`);
  tx(project, "HKS spike 1b: blurriness", (c) => {
    const p = gb.component.getParam(0);
    if (!c.addAction(p.createSetValueAction(p.createKeyframe(BLUR.blurriness), true))) throw new Error("blurriness refused");
  });
  await applyMotionValues(ppro, project, "HKS spike 1b: crop box", [{ item: fresh.item, name: "blur box", values: BLUR.crop }]);
  after = await readSequence(ppro, copy, { paths: false });
  report.fresh = plain(after.video.filter((c) => c.track === target));
  report.freshComponents = describe(await components(await fresh.item.getComponentChain()));
  report.freshMotion = await readTransform(fresh.item);
  report.after = {
    clone: await exportFrame(ppro, project, copy, cloneAt + 1, "hks1b_after_clone.png"),
    fresh: await exportFrame(ppro, project, copy, BLUR.freshAt + 1, "hks1b_after_fresh.png"),
  };
  return report;
}

/* 1c: audio clip Level. The saved value v is linear: dB = 20*log10(v) + 15 (read offline on
   20261120's 22 BGM pieces). One sequence per level from the BGM file; Python renders each with
   export_sequence and measures the loudness difference. */
const LEVELS = [null, -12, -24, -33];
const levelValue = (db) => Math.pow(10, (db - 15) / 20);

async function probeVolume(ppro) {
  const project = await spikeProject(ppro);
  const yt = await readSequence(ppro, await sequenceNamed(ppro, project, YT), { paths: true });
  const bgm = yt.audio.find((c) => baseName(c.path) === BGM);
  if (!bgm) throw new Error(`No ${BGM} clip in ${YT}.`);
  const bgmItem = ppro.ClipProjectItem.cast(await bgm.item.getProjectItem());
  const report = { step: "1c", ytBgmComponents: describe(await components(await bgm.item.getComponentChain())), sequences: [] };
  for (const db of LEVELS) {
    const name = `HKS spike 1c ${db === null ? "untouched" : `${db} dB`}`;
    const seq = await project.createSequenceFromMedia(name, [bgmItem]);
    const read = await readSequence(ppro, seq, { paths: false });
    const entry = { name, db, audioClips: read.audio.length };
    report.sequences.push(entry);
    if (!read.audio.length) continue;
    const clip = read.audio[0];
    const comps = await components(await clip.item.getComponentChain());
    entry.before = describe(comps);
    if (db === null) continue;
    const vol = comps.find((c) => c.displayName === "Volume");
    const level = vol && vol.params.find((p) => p.name === "Level");
    if (!level) { entry.error = "no Volume > Level"; continue; }
    entry.written = levelValue(db);
    tx(project, `HKS spike 1c: ${db} dB`, (c) => {
      const p = vol.component.getParam(level.index);
      if (!c.addAction(p.createSetValueAction(p.createKeyframe(entry.written), true))) throw new Error("level refused");
    });
    entry.after = describe(await components(await clip.item.getComponentChain()));
  }
  return report;
}

/* 1d: duplicate a sequence (the 3-min reel = the FB copy) and nest one sequence into another
   (the 1-min square into the reel frame): the sequence's project item placed with
   createOverwriteItemAction, as a nested clip. */
async function probeNest(ppro) {
  const project = await spikeProject(ppro);
  const square = await sequenceNamed(ppro, project, "3 SQUARE SELECT D1");
  const fb = await sequenceNamed(ppro, project, "2 FACEBOOK D1");
  const reel = await sequenceNamed(ppro, project, "4 REEL SIZE D1");
  const report = { step: "1d" };
  const dup = await cloneAs(project, fb, "HKS spike 1d FB duplicate");
  const [fbRead, dupRead] = [await readSequence(ppro, fb, { paths: false }), await readSequence(ppro, dup, { paths: false })];
  const shape = async (seq, r) => ({ video: r.video.length, audio: r.audio.length, end: secs(toTicks(await seq.getEndTime())) });
  report.duplicate = { name: dup.name, fb: await shape(fb, fbRead), copy: await shape(dup, dupRead) };

  const reelCopy = await cloneAs(project, reel, "HKS spike 1d reel");
  const editor = ppro.SequenceEditor.getEditor(reelCopy);
  const before = await readSequence(ppro, reelCopy, { paths: false });
  const squareItem = await square.getProjectItem();
  tx(project, "HKS spike 1d: nest square", (c) => {
    if (!c.addAction(editor.createOverwriteItemAction(squareItem, ppro.TickTime.createWithTicks("0"), before.videoTracks, before.audioTracks))) throw new Error("nest refused");
  });
  const after = await readSequence(ppro, reelCopy, { paths: false });
  const old = new Set([...before.video, ...before.audio].map(key));
  const placed = [];
  for (const c of [...after.video, ...after.audio].filter((c) => !old.has(key(c)))) {
    placed.push({ kind: c.kind, track: c.track + 1, start: secs(c.start), end: secs(c.end), name: await c.item.getName() });
  }
  report.nest = { reel: reelCopy.name, squareEnd: secs(toTicks(await square.getEndTime())), placed,
    frame: await exportFrame(ppro, project, reelCopy, 10, "hks1d_reel.png") };
  return report;
}

/* 1e: after a build_sequence run (cutdeck/hks_build.py), which sequence is active (the build must
   not have opened its clone), and the same frame of the original and of the build, at 50 s: under
   a V8 clock blur with no film damage. The two PNGs are diffed offline. */
const BUILD = { name: "HKS build 1e run3", at: 50 };

async function probeReplay(ppro) {
  const project = await spikeProject(ppro);
  const active = await project.getActiveSequence();
  const built = await sequenceNamed(ppro, project, BUILD.name);
  return { step: "1e", active: active ? active.name : null, built: built.name, at: BUILD.at,
    original: await exportFrame(ppro, project, await sequenceNamed(ppro, project, YT), BUILD.at, "hks1e_original.png"),
    build: await exportFrame(ppro, project, built, BUILD.at, "hks1e_build.png") };
}

const formatReport = (report) => JSON.stringify(report, (k, v) => (typeof v === "bigint" ? v.toString() : v), 2);

module.exports = { probeCover: guarded(probeCover), probeBlur: guarded(probeBlur),
  probeVolume: guarded(probeVolume), probeNest: guarded(probeNest), probeReplay: guarded(probeReplay), formatReport, levelValue, SPIKE_PROJECT };
