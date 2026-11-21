/* General Premiere control for agents: the small, typed operations a person does by hand
   (read the timeline, open a sequence, park the playhead, select, move, trim, remove, place,
   add effects and transitions, set any effect parameter or keyframe, mute a track, remove
   markers, import, save, grab a frame). Each one is a handler of the panel driver
   (features/driver.js); the helper validates arguments first (cutdeck/driver_commands.py).
   The full route map, including what UXP cannot do: docs/PREMIERE_CONTROL_MAP.md.

   A clip is named by an id "V<track>@<start_ticks>" / "A<track>@<start_ticks>" (track 1-based,
   as Premiere shows it; start in sequence ticks), the same id read_timeline prints. Edits run as
   ONE transaction (one Ctrl+Z) and re-read what they changed.

   APIs, each a line of reference/adobe/api/premierepro.txt (status rows in docs/PREMIERE_FACTS.md):
   Project.getSequences/getActiveSequence/openSequence/setActiveSequence/getRootItem/importFiles/
   save/name/path; Sequence.getPlayerPosition/setPlayerPosition/createSetInPointAction/
   createSetOutPointAction/clearSelection/setSelection/getFrameSize/getTimebase/getInPoint/
   getOutPoint/getEndTime/getProjectItem/get{Video,Audio}Track(Count); {Video,Audio}Track.name/
   isMuted/setMute/getTrackItems; {Video,Audio}ClipTrackItem.getName/getStartTime/getEndTime/
   getInPoint/getOutPoint/getSpeed/isDisabled/getIsSelected/isAdjustmentLayer/getProjectItem/
   getComponentChain/createMoveAction/createSetInPointAction/createSetOutPointAction/
   createSetDisabledAction/createSetNameAction; VideoClipTrackItem.createAddVideoTransitionAction;
   AddTransitionOptions constructor + setApplyToStart/setDuration (docs ppro-reference/classes/
   addtransitionoptions.md "Constructor"; samples premiere-api/src/transition.ts);
   TransitionFactory.createVideoTransition/getVideoTransitionMatchNames; VideoFilterFactory.
   createComponent/getMatchNames/getDisplayNames; AudioFilterFactory.createComponentByDisplayName/
   getDisplayNames; {Video,Audio}ComponentChain.getComponentCount/getComponentAtIndex/
   createAppendComponentAction; Component.getMatchName/getDisplayName/getParamCount/getParam;
   ComponentParam.displayName/getStartValue/isTimeVarying/getKeyframeListAsTickTimes/
   createKeyframe/createSetValueAction/createSetTimeVaryingAction/createAddKeyframeAction;
   Keyframe.position; SequenceEditor.getEditor/createOverwriteItemAction/
   createInsertProjectItemAction/createRemoveItemsAction; TrackItemSelection.createEmptySelection/
   addItem (setSelection pattern: samples premiere-api/src/sequence.ts); Markers.getMarkers (static
   and instance)/createRemoveMarkerAction; Marker.getName/getStart/getDuration/getComments/getType/
   getColorIndex; ClipProjectItem.cast/getMediaFilePath; Exporter.exportSequenceFrame;
   uxp.storage.localFileSystem.getTemporaryFolder (reference/adobe/api/uxp.txt). */

const { runTransaction, asBinLike, activeProject, sequenceNamed, projectAndSequenceNamed, openAndActivate } = require("../host/project.js");
const { getTrackClipItems, isTrackItemSelected, trackItemName } = require("../host/trackItems.js");
const { unwrapKeyframeValue, toParamValue } = require("../host/components.js");
const { toTicks } = require("../host/ticks.js");
const { waitForFile } = require("../host/files.js");
const { projectItemMediaPath } = require("../host/sequenceRead.js");

const CLIP_ID = /^([VA])(\d+)@(\d+)$/;

const clipId = (kind, track, start) => `${kind === "video" ? "V" : "A"}${track + 1}@${start}`;

function parseClipId(id) {
  const m = CLIP_ID.exec(String(id || ""));
  if (!m || Number(m[2]) < 1) throw new Error(`"${id}" is not a clip id like V1@0 or A2@5.`);
  return { kind: m[1] === "V" ? "video" : "audio", track: Number(m[2]) - 1, start: m[3] };
}

const tick = (ppro, ticks) => ppro.TickTime.createWithTicks(String(ticks));
const ticksOf = (t) => toTicks(t).toString();

const track = (seq, kind, index) => (kind === "video" ? seq.getVideoTrack(index) : seq.getAudioTrack(index));
const trackCount = (seq, kind) => (kind === "video" ? seq.getVideoTrackCount() : seq.getAudioTrackCount());

// The track item an id names, read fresh (references go stale across transactions).
async function findClip(ppro, seq, id) {
  const ref = parseClipId(id);
  if (ref.track >= await trackCount(seq, ref.kind)) throw new Error(`${id}: the sequence has no track ${String(id).split("@")[0]}.`);
  for (const item of await getTrackClipItems(await track(seq, ref.kind, ref.track), ppro)) {
    if (ticksOf(await item.getStartTime()) === ref.start) return { ...ref, id: String(id), item };
  }
  throw new Error(`${id}: no clip starts at ${ref.start} ticks on that track.`);
}

async function paramValue(param) {
  try { return unwrapKeyframeValue(await param.getStartValue()); } catch (_) { return null; }
}

async function readChain(item, withParams) {
  const chain = await item.getComponentChain();
  if (!chain) return [];
  const out = [];
  for (let c = 0; c < chain.getComponentCount(); c++) {
    const comp = chain.getComponentAtIndex(c);
    const entry = { index: c, match_name: await comp.getMatchName(), name: await comp.getDisplayName() };
    if (withParams) {
      entry.params = [];
      for (let p = 0; p < comp.getParamCount(); p++) {
        const param = comp.getParam(p);
        let keyframes = 0;
        try { keyframes = param.isTimeVarying() ? (param.getKeyframeListAsTickTimes() || []).length : 0; } catch (_) {}
        entry.params.push({ index: p, name: param.displayName, value: await paramValue(param), keyframes });
      }
    }
    out.push(entry);
  }
  return out;
}

// Null, never a throw: list_project and projectItemForMedia walk bins and sequences too.
async function mediaOf(ppro, projectItem) {
  try { return await projectItemMediaPath(ppro, projectItem); } catch (_) { return null; }
}

async function readClip(ppro, kind, t, item, effects) {
  const [start, end, inPoint, outPoint] = await Promise.all([item.getStartTime(), item.getEndTime(), item.getInPoint(), item.getOutPoint()]);
  const startTicks = ticksOf(start);
  const clip = {
    id: clipId(kind, t, startTicks), name: await trackItemName(item),
    start_ticks: startTicks, end_ticks: ticksOf(end), in_ticks: ticksOf(inPoint), out_ticks: ticksOf(outPoint),
    disabled: await item.isDisabled(), selected: await isTrackItemSelected(item),
  };
  try { clip.speed = await item.getSpeed(); } catch (_) {}
  if (kind === "video") { try { clip.adjustment_layer = await item.isAdjustmentLayer(); } catch (_) {} }
  clip.media = await mediaOf(ppro, await item.getProjectItem());
  if (effects) clip.effects = await readChain(item, effects === "params");
  return clip;
}

async function readMarkers(ppro, seq) {
  const markers = await ppro.Markers.getMarkers(seq);
  return (markers.getMarkers() || []).map((m) => ({
    name: m.getName(), start_ticks: ticksOf(m.getStart()), duration_ticks: ticksOf(m.getDuration()),
    comments: m.getComments(), type: m.getType(), color_index: m.getColorIndex(),
  }));
}

/* read_timeline: the tracks and clips of a sequence, its marks, playhead and markers.
   effects: false | "names" (component chain) | "params" (every parameter's start value).
   tracks: only these ("V1", "A2"); from_ticks / to_ticks: only clips overlapping that span, so a
   4,700-clip sequence can be read a piece at a time. */
async function readTimeline(ppro, { sequence: name = null, effects = false, tracks: only = null,
  from_ticks: from = null, to_ticks: to = null } = {}) {
  const { project, sequence: seq } = await projectAndSequenceNamed(ppro, name);
  const active = await project.getActiveSequence();
  const size = await seq.getFrameSize();
  const out = {
    name: seq.name, sequence_id: String(seq.guid), active: !!active && String(active.guid) === String(seq.guid),
    width: size.width, height: size.height, ticks_per_frame: String(await seq.getTimebase()),
    in_ticks: ticksOf(await seq.getInPoint()), out_ticks: ticksOf(await seq.getOutPoint()),
    end_ticks: ticksOf(await seq.getEndTime()), playhead_ticks: ticksOf(await seq.getPlayerPosition()),
    tracks: [], markers: await readMarkers(ppro, seq),
  };
  for (const kind of ["video", "audio"]) {
    const count = await trackCount(seq, kind);
    for (let t = 0; t < count; t++) {
      if (only && !only.includes(`${kind === "video" ? "V" : "A"}${t + 1}`)) continue;
      const tr = await track(seq, kind, t);
      const clips = [];
      for (const item of await getTrackClipItems(tr, ppro)) {
        if (from !== null && toTicks(await item.getEndTime()) <= BigInt(from)) continue;
        if (to !== null && toTicks(await item.getStartTime()) >= BigInt(to)) continue;
        clips.push(await readClip(ppro, kind, t, item, effects));
      }
      let muted = null;
      try { muted = await tr.isMuted(); } catch (_) {}
      out.tracks.push({ id: `${kind === "video" ? "V" : "A"}${t + 1}`, kind, name: tr.name, muted, clips });
    }
  }
  return out;
}

// A bin's children, or null when `item` is not a bin (FolderItem.cast, host/project.js asBinLike).
async function binItems(item) {
  try {
    const bin = asBinLike(item);
    return bin && typeof bin.getItems === "function" ? (await bin.getItems()) || [] : null;
  } catch (_) { return null; }
}

/* list_project: the project, its sequences, and its bin tree (clips with their media file). */
async function listProject(ppro, { depth = 8 } = {}) {
  const project = await activeProject(ppro);
  const active = await project.getActiveSequence();
  const sequences = (await project.getSequences()).map((s) => ({ name: s.name, sequence_id: String(s.guid),
    active: !!active && String(active.guid) === String(s.guid) }));
  const walk = async (children, level) => {
    const items = [];
    for (const it of children) {
      const entry = { name: it.name };
      const media = await mediaOf(ppro, it);
      if (media) entry.media = media;
      else {
        const sub = level < depth ? await binItems(it) : null;
        if (sub) { entry.bin = true; entry.items = await walk(sub, level + 1); }
      }
      items.push(entry);
    }
    return items;
  };
  return { name: project.name, path: project.path, sequences, items: await walk((await binItems(await project.getRootItem())) || [], 1) };
}

async function openSequence(ppro, { sequence: name }) {
  const { project, sequence } = await projectAndSequenceNamed(ppro, name);
  const { opened, activated } = await openAndActivate(project, sequence);
  const now = await project.getActiveSequence();
  return { name: sequence.name, opened, activated, active: !!now && String(now.guid) === String(sequence.guid) };
}

async function setPlayhead(ppro, { sequence: name = null, ticks }) {
  const { sequence } = await projectAndSequenceNamed(ppro, name);
  const set = await sequence.setPlayerPosition(tick(ppro, ticks));
  return { name: sequence.name, set, playhead_ticks: ticksOf(await sequence.getPlayerPosition()) };
}

async function setInOut(ppro, { sequence: name = null, in_ticks: inTicks = null, out_ticks: outTicks = null }) {
  const { project, sequence } = await projectAndSequenceNamed(ppro, name);
  runTransaction(project, "CutDeck: set In/Out", (compound) => {
    if (inTicks !== null && !compound.addAction(sequence.createSetInPointAction(tick(ppro, inTicks)))) throw new Error("addAction(In) returned false");
    if (outTicks !== null && !compound.addAction(sequence.createSetOutPointAction(tick(ppro, outTicks)))) throw new Error("addAction(Out) returned false");
  });
  return { name: sequence.name, in_ticks: ticksOf(await sequence.getInPoint()), out_ticks: ticksOf(await sequence.getOutPoint()) };
}

/* select_clips: replace the timeline selection with `clips` (ids); [] clears it. */
async function selectClips(ppro, { sequence: name = null, clips }) {
  const { sequence } = await projectAndSequenceNamed(ppro, name);
  const found = [];
  for (const id of clips) found.push(await findClip(ppro, sequence, id));
  await sequence.clearSelection();
  let set = true;
  if (found.length) {
    ppro.TrackItemSelection.createEmptySelection((selection) => {
      for (const f of found) selection.addItem(f.item, true);
      set = sequence.setSelection(selection); // a selection is valid only inside its callback
    });
  }
  const selected = [];
  for (const f of found) if (await isTrackItemSelected(f.item)) selected.push(f.id);
  return { name: sequence.name, set, selected };
}

/* edit_clips: a list of {clip, op, ...} done in ONE transaction. ops: move {dt_ticks} (relative;
   linked audio does NOT follow, move it too), trim_in {in_ticks} / trim_out {out_ticks} (media
   time: head trim moves start and In together), enable, disable, rename {name}, remove {ripple}.
   Returns the touched tracks as they read after the edit. */
async function editClips(ppro, { sequence: name = null, edits }) {
  const { project, sequence } = await projectAndSequenceNamed(ppro, name);
  const targets = [];
  for (const e of edits) targets.push({ ...e, ...(await findClip(ppro, sequence, e.clip)) });
  const editor = ppro.SequenceEditor.getEditor(sequence);
  runTransaction(project, "CutDeck: edit clips", (compound) => {
    const add = (action, what) => { if (!compound.addAction(action)) throw new Error(`addAction(${what}) returned false`); };
    for (const t of targets) {
      if (t.op === "move") add(t.item.createMoveAction(tick(ppro, t.dt_ticks)), `move ${t.id}`);
      else if (t.op === "trim_in") add(t.item.createSetInPointAction(tick(ppro, t.in_ticks)), `trim_in ${t.id}`);
      else if (t.op === "trim_out") add(t.item.createSetOutPointAction(tick(ppro, t.out_ticks)), `trim_out ${t.id}`);
      else if (t.op === "enable" || t.op === "disable") add(t.item.createSetDisabledAction(t.op === "disable"), `${t.op} ${t.id}`);
      else if (t.op === "rename") add(t.item.createSetNameAction(t.name), `rename ${t.id}`);
      else if (t.op !== "remove") throw new Error(`Unknown op ${t.op}`);
    }
    // Plain removes: one per media type (PREMIERE_FACTS "createRemoveItemsAction(sel, ripple=false,
    // mediaType)"). Ripple removes: ONE action over video and audio together (MediaType.ANY); a
    // ripple per media type shifted later clips twice (PREMIERE_FACTS "ripple=true", live 2026-11-21).
    const removeGroups = [
      ["video", false, ppro.Constants.MediaType.VIDEO],
      ["audio", false, ppro.Constants.MediaType.AUDIO],
      [null, true, ppro.Constants.MediaType.ANY],
    ];
    for (const [kind, ripple, mediaType] of removeGroups) {
      const group = targets.filter((t) => t.op === "remove" && !!t.ripple === ripple && (kind === null || t.kind === kind));
      if (!group.length) continue;
      let added = false;
      ppro.TrackItemSelection.createEmptySelection((selection) => {
        for (const t of group) selection.addItem(t.item, true);
        added = compound.addAction(editor.createRemoveItemsAction(selection, ripple, mediaType));
      });
      if (!added) throw new Error(`addAction(remove${ripple ? " ripple" : ` ${kind}`}) returned false`);
    }
  });
  const tracksAfter = [];
  for (const kind of ["video", "audio"]) {
    for (const t of new Set(targets.filter((x) => x.kind === kind).map((x) => x.track))) {
      const clips = [];
      for (const item of await getTrackClipItems(await track(sequence, kind, t), ppro)) clips.push(await readClip(ppro, kind, t, item, false));
      tracksAfter.push({ id: `${kind === "video" ? "V" : "A"}${t + 1}`, clips });
    }
  }
  return { name: sequence.name, edits: targets.length, tracks_after: tracksAfter };
}

// The project item whose media file is `path`, searching every bin (null when absent).
async function projectItemForMedia(ppro, project, path) {
  const norm = (p) => String(p).replace(/\//g, "\\").replace(/^\\\\\?\\/, "").toLowerCase();
  const want = norm(path);
  const walk = async (children) => {
    for (const it of children) {
      const media = await mediaOf(ppro, it);
      if (media && norm(media) === want) return it;
      if (!media) {
        const sub = await binItems(it);
        const hit = sub && await walk(sub);
        if (hit) return hit;
      }
    }
    return null;
  };
  return walk((await binItems(await project.getRootItem())) || []);
}

/* place_media: put a media file (imported first if no project item uses it) or a sequence (`nest`)
   on the timeline at `at_ticks`, video on track `v`, audio on track `a` (0-based; an index equal to
   the track count creates that track, one new track per call). mode overwrite (default; covers and
   splits what is there) or insert (ripples later clips). CATCH: audio -1 is not "no audio", it
   lands on A1 (PREMIERE_FACTS "audio track index -1"). */
async function placeMedia(ppro, { sequence: name = null, media = null, nest = null, at_ticks: at, v, a, mode = "overwrite" }) {
  const { project, sequence } = await projectAndSequenceNamed(ppro, name);
  let item;
  if (nest) {
    item = await (await sequenceNamed(project, nest)).getProjectItem();
  } else {
    item = await projectItemForMedia(ppro, project, media);
    if (!item) {
      if (!(await project.importFiles([media], true, await project.getRootItem(), false))) throw new Error(`Import of ${media} failed.`);
      item = await projectItemForMedia(ppro, project, media);
      if (!item) throw new Error(`${media} was imported but no project item for it was found.`);
    }
  }
  const editor = ppro.SequenceEditor.getEditor(sequence);
  runTransaction(project, `CutDeck: ${mode} ${nest || media}`, (compound) => {
    const action = mode === "insert"
      ? editor.createInsertProjectItemAction(item, tick(ppro, at), v, a, false)
      : editor.createOverwriteItemAction(item, tick(ppro, at), v, a);
    if (!compound.addAction(action)) throw new Error(`addAction(${mode}) returned false`);
  });
  const placed = [];
  for (const [kind, index] of [["video", v], ["audio", a]]) {
    if (index < 0 || index >= await trackCount(sequence, kind)) continue;
    for (const it of await getTrackClipItems(await track(sequence, kind, index), ppro)) {
      if (ticksOf(await it.getStartTime()) === String(at)) placed.push(await readClip(ppro, kind, index, it, false));
    }
  }
  // A committed transaction is no proof (PREMIERE_FACTS "SRT insert / overwrite actions"): nesting
  // 1080x1920 30 fps "TT editing" into a 1920x1080 25 fps sequence committed and placed nothing.
  if (!placed.length) throw new Error(`Premiere accepted the ${mode} but nothing landed at ${at} on V${v + 1}/A${a + 1}.`);
  return { name: sequence.name, mode, placed };
}

async function listEffects(ppro) {
  const safe = async (f) => { try { return await f(); } catch (e) { return { error: (e && e.message) || String(e) }; } };
  const [matchNames, displayNames] = await Promise.all([safe(() => ppro.VideoFilterFactory.getMatchNames()), safe(() => ppro.VideoFilterFactory.getDisplayNames())]);
  const video = Array.isArray(matchNames)
    ? matchNames.map((m, i) => ({ match_name: m, name: Array.isArray(displayNames) ? displayNames[i] : null })) : matchNames;
  return {
    video_effects: video,
    audio_effects: await safe(() => ppro.AudioFilterFactory.getDisplayNames()),
    video_transitions: await safe(() => ppro.TransitionFactory.getVideoTransitionMatchNames()),
  };
}

/* add_effect: append a video effect (match name) or an audio effect (display name) to each clip.
   Set its parameters afterwards with set_param (PREMIERE_FACTS "VideoFilterFactory.createComponent
   result": insert, commit, re-fetch). Returns each clip's component chain after. */
async function addEffect(ppro, { sequence: name = null, clips, effect }) {
  const { project, sequence } = await projectAndSequenceNamed(ppro, name);
  const found = [];
  for (const id of clips) found.push(await findClip(ppro, sequence, id));
  const staged = [];
  for (const f of found) {
    const component = f.kind === "video" ? await ppro.VideoFilterFactory.createComponent(effect)
      : await ppro.AudioFilterFactory.createComponentByDisplayName(effect, f.item);
    if (!component) throw new Error(`${f.id}: Premiere has no ${f.kind} effect "${effect}" (see list_effects).`);
    staged.push({ f, component, chain: await f.item.getComponentChain() });
  }
  runTransaction(project, `CutDeck: add ${effect}`, (compound) => {
    for (const s of staged) if (!compound.addAction(s.chain.createAppendComponentAction(s.component))) throw new Error(`addAction(add ${effect} to ${s.f.id}) returned false`);
  });
  const result = [];
  for (const f of found) result.push({ clip: f.id, effects: await readChain((await findClip(ppro, sequence, f.id)).item, false) });
  return { name: sequence.name, effect, clips: result };
}

/* set_param: set one component parameter on a clip. component: chain index (video: 0 Opacity,
   1 Motion) or a match name; param: index. value: number, boolean, string or [x, y] (Position is
   normalised to the sequence frame). at_ticks (MEDIA time, as keyframes are): add a keyframe there
   instead, turning keyframing on first in its own transaction. Reads the value back. */
async function setParam(ppro, { sequence: name = null, clip, component, param: paramIndex, value, at_ticks: at = null }) {
  const { project, sequence } = await projectAndSequenceNamed(ppro, name);
  const resolve = async () => {
    const { item } = await findClip(ppro, sequence, clip);
    const chain = await item.getComponentChain();
    let comp = null;
    if (typeof component === "number") comp = component < chain.getComponentCount() ? chain.getComponentAtIndex(component) : null;
    else {
      for (let c = 0; c < chain.getComponentCount() && !comp; c++) {
        const candidate = chain.getComponentAtIndex(c);
        if ((await candidate.getMatchName()) === component) comp = candidate;
      }
    }
    if (!comp) throw new Error(`${clip}: no component ${JSON.stringify(component)}.`);
    if (paramIndex >= comp.getParamCount()) throw new Error(`${clip}: component ${JSON.stringify(component)} has ${comp.getParamCount()} params.`);
    return comp.getParam(paramIndex);
  };
  let param = await resolve();
  if (at === null) {
    runTransaction(project, `CutDeck: set ${param.displayName}`, (compound) => {
      if (!compound.addAction(param.createSetValueAction(param.createKeyframe(toParamValue(ppro, value)), true))) throw new Error("addAction(set value) returned false");
    });
  } else {
    if (!param.isTimeVarying()) {
      runTransaction(project, `CutDeck: keyframe ${param.displayName} on`, (compound) => {
        if (!compound.addAction(param.createSetTimeVaryingAction(true))) throw new Error("addAction(time varying) returned false");
      });
      param = await resolve();
    }
    runTransaction(project, `CutDeck: keyframe ${param.displayName}`, (compound) => {
      const keyframe = param.createKeyframe(toParamValue(ppro, value));
      keyframe.position = tick(ppro, at);
      if (!compound.addAction(param.createAddKeyframeAction(keyframe))) throw new Error("addAction(keyframe) returned false");
    });
  }
  const fresh = await resolve();
  let keyframes = [];
  try { keyframes = fresh.isTimeVarying() ? (fresh.getKeyframeListAsTickTimes() || []).map(ticksOf) : []; } catch (_) {}
  return { clip, param: fresh.displayName, value: await paramValue(fresh), keyframes_ticks: keyframes };
}

/* add_transition: a video transition (match name from list_effects) on each clip's start or end. */
async function addTransition(ppro, { sequence: name = null, clips, transition, duration_ticks: duration = null, at_start: atStart = false }) {
  const { project, sequence } = await projectAndSequenceNamed(ppro, name);
  const staged = [];
  for (const id of clips) {
    const f = await findClip(ppro, sequence, id);
    if (f.kind !== "video") throw new Error(`${id}: transitions go on video clips only.`);
    staged.push({ f, transition: await ppro.TransitionFactory.createVideoTransition(transition) });
  }
  runTransaction(project, `CutDeck: add ${transition}`, (compound) => {
    for (const s of staged) {
      const options = new ppro.AddTransitionOptions();
      options.setApplyToStart(!!atStart);
      if (duration !== null) options.setDuration(tick(ppro, duration));
      if (!compound.addAction(s.f.item.createAddVideoTransitionAction(s.transition, options))) throw new Error(`addAction(transition on ${s.f.id}) returned false`);
    }
  });
  return { name: sequence.name, transition, clips: staged.map((s) => s.f.id) };
}

/* set_track_mute: mute or unmute track V<n>/A<n>. Each call is its own History entry
   ("Disable/Enable Track Output", PREMIERE_FACTS "Measuring a Graphic's text box ... setMute"). */
async function setTrackMute(ppro, { sequence: name = null, track: id, muted }) {
  const { sequence } = await projectAndSequenceNamed(ppro, name);
  const m = /^([VA])(\d+)$/.exec(String(id));
  if (!m) throw new Error(`"${id}" is not a track like V1 or A2.`);
  const kind = m[1] === "V" ? "video" : "audio";
  const index = Number(m[2]) - 1;
  if (index < 0 || index >= await trackCount(sequence, kind)) throw new Error(`The sequence has no track ${id}.`);
  const tr = await track(sequence, kind, index);
  const set = await tr.setMute(!!muted);
  return { name: sequence.name, track: id, set, muted: await tr.isMuted() };
}

/* remove_markers: remove every sequence marker that starts at one of `starts_ticks`. */
async function removeMarkers(ppro, { sequence: name = null, starts_ticks: starts }) {
  const { project, sequence } = await projectAndSequenceNamed(ppro, name);
  const markers = await ppro.Markers.getMarkers(sequence);
  const want = new Set(starts.map(String));
  const hit = (markers.getMarkers() || []).filter((m) => want.has(ticksOf(m.getStart())));
  if (hit.length) {
    runTransaction(project, "CutDeck: remove markers", (compound) => {
      for (const m of hit) if (!compound.addAction(markers.createRemoveMarkerAction(m))) throw new Error("addAction(remove marker) returned false");
    });
  }
  return { name: sequence.name, removed: hit.length, markers: await readMarkers(ppro, sequence) };
}

async function importFiles(ppro, { paths }) {
  const project = await activeProject(ppro);
  const imported = await project.importFiles(paths, true, await project.getRootItem(), false);
  const items = [];
  for (const p of paths) items.push({ path: p, in_project: !!(await projectItemForMedia(ppro, project, p)) });
  return { imported, items };
}

async function saveProject(ppro) {
  const project = await activeProject(ppro);
  return { saved: await project.save(), path: project.path };
}

/* export_frame: the sequence at `ticks` (default: the playhead) as a PNG at its own frame size
   (PREMIERE_FACTS: a 1080x1920 frame at 1920x1080 comes out pillarboxed), in the panel's temp
   folder. Waits for the file: exportSequenceFrame resolves before it exists (PREMIERE_FACTS). */
async function exportFrame(ppro, { sequence: name = null, ticks = null }) {
  const { sequence } = await projectAndSequenceNamed(ppro, name);
  const folder = await require("uxp").storage.localFileSystem.getTemporaryFolder();
  const at = ticks === null ? await sequence.getPlayerPosition() : tick(ppro, ticks);
  const size = await sequence.getFrameSize();
  const file = `cutdeck-frame-${Date.now()}.png`;
  if (!(await ppro.Exporter.exportSequenceFrame(sequence, at, file, folder.nativePath, size.width, size.height))) {
    throw new Error("exportSequenceFrame returned false");
  }
  const bytes = await waitForFile(folder, file, { timeoutMs: 20000, intervalMs: 50, stablePolls: 3 });
  return { name: sequence.name, ticks: ticksOf(at), width: size.width, height: size.height,
    path: `${String(folder.nativePath).replace(/[\\/]$/, "")}\\${file}`, bytes };
}

function controlHandlers(ppro) {
  return {
    read_timeline: (args) => readTimeline(ppro, args),
    list_project: (args) => listProject(ppro, args),
    open_sequence: (args) => openSequence(ppro, args),
    set_playhead: (args) => setPlayhead(ppro, args),
    set_in_out: (args) => setInOut(ppro, args),
    select_clips: (args) => selectClips(ppro, args),
    edit_clips: (args) => editClips(ppro, args),
    place_media: (args) => placeMedia(ppro, args),
    list_effects: () => listEffects(ppro),
    add_effect: (args) => addEffect(ppro, args),
    set_param: (args) => setParam(ppro, args),
    add_transition: (args) => addTransition(ppro, args),
    set_track_mute: (args) => setTrackMute(ppro, args),
    remove_markers: (args) => removeMarkers(ppro, args),
    import_files: (args) => importFiles(ppro, args),
    save_project: () => saveProject(ppro),
    export_frame: (args) => exportFrame(ppro, args),
  };
}

module.exports = { controlHandlers, parseClipId, clipId };
