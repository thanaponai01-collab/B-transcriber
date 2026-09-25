/* Native multi-cam Sync (docs/HANDOFF_CUTDECK_NATIVE_SYNC.md step 2B). The helper matches the
   clips by audio (`plan_sync`); this places them in Premiere, with no XML round trip:

     1. refuse a sequence already named *_Synced; read every clip off the timeline
     2. ask the helper where each clip belongs
     3. copy the sequence to <name>_Synced (its own transaction: the copy must be found first)
     4. in ONE transaction (one Ctrl+Z): remove every item from the copy, then place each clip's
        whole file on its own V/A tracks at its planned start
     5. read the copy back and check every clip landed where, and as long as, it should

   Every Premiere call is declared in @adobe/premierepro 26.2.1's premierepro.d.ts. Proven live by
   the "Test Sync Moves" probe (syncProbe.js): getMediaFilePath, Sequence.createCloneAction,
   createSetNameAction, createOverwriteItemAction (V + all audio land linked; an index equal to
   the track count creates the track), one transaction undone by one Ctrl+Z. NOT yet run live:
   TrackItemSelection.createEmptySelection/addItem + createRemoveItemsAction, several overwrites
   onto not-yet-existing tracks in one transaction, overwrite at a between-frames time, and -1 as
   the unused track index. The read-back is what catches any of those going wrong, on the copy. */

const { runTransaction, activeProjectAndSequence, getOrCreateBin, asBinLike, CUTDECK_BIN_NAME, SYNCED_BIN_NAME } = require("../host/project.js");
const { TICKS_PER_SECOND, toTicks } = require("../host/ticks.js");
const { getTrackClipItems } = require("../host/trackItems.js");

const SYNCED_SUFFIX = "_Synced";

const baseName = (p) => String(p || "").split(/[\\/]/).pop();

async function listClips(ppro, seq, kind, { end = true, inPoint = true } = {}) {
  const video = kind === "video";
  const count = await (video ? seq.getVideoTrackCount() : seq.getAudioTrackCount());
  const clips = [];
  for (let t = 0; t < count; t++) {
    const track = await (video ? seq.getVideoTrack(t) : seq.getAudioTrack(t));
    const items = track ? await getTrackClipItems(track, ppro) : [];
    if (!items.length) continue;
    const trackClips = await Promise.all(items.map(async (item) => {
      const [startTick, endTick, inPointTick] = await Promise.all([
        item.getStartTime(),
        end ? item.getEndTime() : null,
        inPoint ? item.getInPoint() : null,
      ]);
      return {
        item,
        kind,
        track: t,
        start: toTicks(startTick),
        end: end ? toTicks(endTick) : undefined,
        inPoint: inPoint ? toTicks(inPointTick) : undefined,
      };
    }));
    clips.push(...trackClips);
  }
  return { count, clips };
}

async function mediaPath(ppro, item) {
  const projectItem = typeof item.getProjectItem === "function" ? await item.getProjectItem() : null;
  const clip = ppro && ppro.ClipProjectItem && ppro.ClipProjectItem.cast ? ppro.ClipProjectItem.cast(projectItem) : projectItem;
  return clip && typeof clip.getMediaFilePath === "function" ? (await clip.getMediaFilePath()) || null : null;
}

async function mediaInfo(ppro, item) {
  const projectItem = typeof item.getProjectItem === "function" ? await item.getProjectItem() : null;
  const clip = ppro && ppro.ClipProjectItem && ppro.ClipProjectItem.cast ? ppro.ClipProjectItem.cast(projectItem) : projectItem;
  const path = clip && typeof clip.getMediaFilePath === "function" ? (await clip.getMediaFilePath()) || null : null;
  const targetItem = clip || projectItem;
  let colorLabel = null;
  if (typeof item.getColorLabelIndex === "function") {
    try { colorLabel = await item.getColorLabelIndex(); } catch (_) {}
  }
  if (colorLabel === null && targetItem && typeof targetItem.getColorLabelIndex === "function") {
    try { colorLabel = await targetItem.getColorLabelIndex(); } catch (_) {}
  }
  if (colorLabel === null && projectItem && typeof projectItem.getColorLabelIndex === "function") {
    try { colorLabel = await projectItem.getColorLabelIndex(); } catch (_) {}
  }
  return { projectItem: projectItem || clip, path, colorLabel };
}

/* Every clip item on the sequence, each with the file behind it (null when it has none).
   `paths: false` skips the file lookup (2 host calls per clip) for reads that only need
   positions — c.path is then undefined; `end: false` / `inPoint: false` likewise skip those
   (1 call each per clip). */
async function readSequence(ppro, seq, { paths = true, end = true, inPoint = true } = {}) {
  const [video, audio] = await Promise.all([
    listClips(ppro, seq, "video", { end, inPoint }),
    listClips(ppro, seq, "audio", { end, inPoint }),
  ]);
  if (paths) {
    const allClips = [...video.clips, ...audio.clips];
    const cache = new Map();
    for (const c of allClips) {
      try {
        let info = cache.get(c.item);
        if (!info) {
          info = await mediaInfo(ppro, c.item);
          cache.set(c.item, info);
        }
        c.path = info.path;
        c.projectItem = info.projectItem;
        c.colorLabel = info.colorLabel;
      } catch (_) {
        c.path = null;
        c.projectItem = null;
        c.colorLabel = null;
      }
    }
    cache.clear();
  }
  return { videoTracks: video.count, audioTracks: audio.count, video: video.clips, audio: audio.clips };
}

const unitKey = (c) => `${c.path}|${c.start}|${c.inPoint}`;

/* A camera clip = one video item plus every audio item from the same file at the same start and
   source In. The API cannot read links, so this is how they are grouped. */
function groupUnits(video, audio) {
  const audioByKey = new Map();
  for (const a of audio) {
    if (!a.path) continue;
    if (!audioByKey.has(unitKey(a))) audioByKey.set(unitKey(a), []);
    audioByKey.get(unitKey(a)).push(a);
  }
  return video.filter((v) => v.path).map((v) => ({ video: v, audio: audioByKey.get(unitKey(v)) || [] }));
}

/* Every clip on the timeline, in timeline order: camera clips (video + its audio) and recorder
   clips (audio items no video claims). Items with no media file are listed, not synced. */
function groupClips(seq) {
  const units = groupUnits(seq.video, seq.audio);
  const claimed = new Set(units.map((u) => unitKey(u.video)));
  const recorders = new Map();
  for (const a of seq.audio) {
    if (!a.path || claimed.has(unitKey(a))) continue;
    if (!recorders.has(unitKey(a))) recorders.set(unitKey(a), { video: null, audio: [] });
    recorders.get(unitKey(a)).audio.push(a);
  }
  const first = (u) => u.video || u.audio[0];
  const clips = [...units, ...recorders.values()]
    .sort((x, y) => (first(x).start < first(y).start ? -1 : first(x).start > first(y).start ? 1
      : Number(!x.video) - Number(!y.video) || first(x).track - first(y).track))
    .map((u, i) => {
      const f = first(u);
      const colorLabel = (f && f.colorLabel !== null && f.colorLabel !== undefined)
        ? f.colorLabel
        : (u.audio && u.audio[0] && u.audio[0].colorLabel !== undefined ? u.audio[0].colorLabel : null);
      return {
        ...u,
        id: `c${i}`,
        key: unitKey(f),
        path: f.path,
        projectItem: f.projectItem || (u.audio && u.audio[0] && u.audio[0].projectItem) || null,
        colorLabel: colorLabel !== undefined ? colorLabel : null,
        name: baseName(f.path),
        duration: f.end - f.start,
      };
    });
  const skipped = [...seq.video, ...seq.audio].filter((c) => !c.path);
  return { clips, skipped };
}

/* A synced clip gets its own tracks: the next video track if it has video, and as many audio
   tracks as it has audio items (a stereo or multi-channel clip keeps all of them). Clips that
   could not be synced lie flat on the first tracks instead, one after another in time (the plan
   spaces them). -1 = no track. */
function assignTracks(clips, synced) {
  let v = 0;
  let a = 0;
  return clips.map((c, i) => {
    if (!synced[i]) return { video: c.video ? 0 : -1, audio: c.audio.length ? 0 : -1 };
    const tracks = { video: c.video ? v++ : -1, audio: c.audio.length ? a : -1 };
    a += c.audio.length;
    return tracks;
  });
}

/* Planned seconds -> ticks. Video starts on a whole frame (Premiere puts video on frames); an
   audio-only clip keeps the exact tick, so a recorder can sit between two frames. */
function startTicks(seconds, hasVideo, ticksPerFrame) {
  const ticks = BigInt(Math.round(seconds * Number(TICKS_PER_SECOND)));
  if (!hasVideo) return ticks;
  return ((ticks + ticksPerFrame / 2n) / ticksPerFrame) * ticksPerFrame;
}

/* The helper pushes the job's progress (rpc.watch); nothing polls. */
async function waitForPlan(rpc, clips, deps) {
  const say = (job) => deps.onStatus(`Matching audio… ${(job.progress && job.progress.stage) || ""}`.trim());
  let job = await rpc({ type: "plan_sync", clips: clips.map((c) => ({
    id: c.id, path: c.path, duration_s: Number(c.duration) / Number(TICKS_PER_SECOND) })) });
  if (job.state === "running") {
    say(job);
    job = await rpc.watch(job.job_id, (update) => { if (update.state === "running") say(update); });
  }
  if (job.state !== "ready" || !job.plan) throw new Error(job.message || `Sync matching ended as ${job.state}.`);
  return job.plan;
}

async function copySequence(project, source, name, targets = []) {
  const beforeIds = new Set((await project.getSequences()).map((s) => s.guid.toString()));
  runTransaction(project, "CutDeck Sync: copy sequence", (compound) => {
    if (!compound.addAction(source.createCloneAction())) throw new Error("addAction(copy sequence) returned false");
  });
  const created = (await project.getSequences()).filter((s) => !beforeIds.has(s.guid.toString()));
  if (created.length !== 1) throw new Error(`Copying the sequence gave ${created.length} new sequences; stopped before placing anything.`);
  const copy = created[0];
  const item = await copy.getProjectItem();
  const sourceItem = typeof source.getProjectItem === "function" ? await source.getProjectItem() : null;
  const sourceColor = sourceItem && typeof sourceItem.getColorLabelIndex === "function"
    ? await sourceItem.getColorLabelIndex()
    : null;
  runTransaction(project, "CutDeck Sync: name copy", (compound) => {
    if (!compound.addAction(item.createSetNameAction(name))) throw new Error("addAction(rename) returned false");
    if (sourceColor !== null && typeof item.createSetColorLabelAction === "function") {
      compound.addAction(item.createSetColorLabelAction(sourceColor));
    }
    for (const t of targets) {
      if (t.clip && t.clip.colorLabel !== null && t.clip.colorLabel !== undefined && t.projectItem) {
        if (typeof t.projectItem.createSetColorLabelAction === "function") {
          const act = t.projectItem.createSetColorLabelAction(t.clip.colorLabel);
          if (act) compound.addAction(act);
        }
      }
    }
  });
  // File it under CutDeck > Synced, the same move nativeCut.js uses for Rough Cuts
  // (FolderItem.createMoveItemAction d.ts:1271, ProjectItem.getParentBin d.ts:2515).
  const bin = asBinLike(await getOrCreateBin(project, [CUTDECK_BIN_NAME, SYNCED_BIN_NAME]));
  runTransaction(project, "CutDeck Sync: file copy", (compound) => {
    const parent = asBinLike(item.getParentBin());
    if (!compound.addAction(parent.createMoveItemAction(item, bin))) throw new Error("addAction(move to bin) returned false");
  });
  return copy.guid.toString();
}

async function findSequence(project, id) {
  const seq = (await project.getSequences()).find((s) => s.guid.toString() === id);
  if (!seq) throw new Error("The synced copy disappeared from the project.");
  return seq;
}

/* One transaction: clear the copy, then place every clip from its file. */
async function placeAll(ppro, project, copy, targets) {
  for (const t of targets) {
    if (!t.projectItem) {
      const lead = t.clip && (t.clip.video || (t.clip.audio && t.clip.audio[0]));
      if (lead && lead.item && typeof lead.item.getProjectItem === "function") {
        t.projectItem = await lead.item.getProjectItem();
      }
    }
  }
  const now = await readSequence(ppro, copy, { paths: false, end: false, inPoint: false });
  const editor = ppro.SequenceEditor.getEditor(copy);
  const tick = (n) => ppro.TickTime.createWithTicks(n.toString());
  runTransaction(project, "CutDeck Sync", (compound) => {
    // The selection is only valid while its callback runs (live 2026-09-23: "The script object
    // is no longer valid"; Adobe's eslint-plugin-premierepro rule no-empty-selection-escape),
    // so it is filled and turned into the remove action in there, synchronously.
    let cleared = false;
    ppro.TrackItemSelection.createEmptySelection((selection) => {
      for (const c of [...now.video, ...now.audio]) selection.addItem(c.item, true);
      cleared = compound.addAction(editor.createRemoveItemsAction(selection, false, ppro.Constants.MediaType.ANY));
    });
    if (!cleared) throw new Error("addAction(clear copy) returned false");
    for (const m of targets) {
      if (m.clip && m.clip.colorLabel !== null && m.clip.colorLabel !== undefined && m.projectItem) {
        if (typeof m.projectItem.createSetColorLabelAction === "function") {
          const act = m.projectItem.createSetColorLabelAction(m.clip.colorLabel);
          if (act) compound.addAction(act);
        }
      }
      if (!compound.addAction(editor.createOverwriteItemAction(m.projectItem, tick(m.start), m.tracks.video, m.tracks.audio))) {
        throw new Error(`addAction(place ${m.clip.name}) returned false`);
      }
    }
  });
  now.video.length = 0;
  now.audio.length = 0;
}

/* What landed, against what was planned. Problems are named per clip; nothing is fixed up. */
function checkPlacement(after, targets, ticksPerFrame) {
  const problems = [];
  const expected = new Set();
  for (const t of targets) {
    const { clip, tracks, start, mediaTicks } = t;
    const v = tracks.video >= 0 ? after.video.find((c) => c.track === tracks.video && c.path === clip.path) : null;
    const a = tracks.audio < 0 ? [] : after.audio.filter((c) => c.path === clip.path
      && c.track >= tracks.audio && c.track < tracks.audio + clip.audio.length);
    const lead = v || a[0];
    if (!lead || (tracks.video >= 0 && !v)) { problems.push(`${clip.name} did not land`); continue; }
    [v, ...a].filter(Boolean).forEach((c) => expected.add(c));
    const off = lead.start - start;
    if (off > 1n || off < -1n) problems.push(`${clip.name} landed ${off} ticks off its planned start`);
    if (a.length !== clip.audio.length) problems.push(`${clip.name} has ${a.length} audio clip(s), the original had ${clip.audio.length}`);
    if (mediaTicks !== null && mediaTicks - (lead.end - lead.start) > ticksPerFrame) {
      problems.push(`${clip.name} is shorter than its file: check its In/Out marks in the Source Monitor`);
    }
  }
  const leftover = [...after.video, ...after.audio].filter((c) => !expected.has(c)).length;
  if (leftover) problems.push(`${leftover} other item(s) are on the copy that should not be`);
  return problems;
}

const REASON = { no_audio: "no audio", unmatched: "matched nothing", silent: "silent audio", too_short: "too short" };

function formatReport(name, plan, clips, skipped, problems) {
  const byId = new Map(clips.map((c) => [c.id, c]));
  const placed = plan.placements.filter((p) => p.status === "anchor" || p.status === "synced");
  const back = plan.placements.filter((p) => !placed.includes(p));
  const lines = [`${placed.length} synced in ${plan.sessions} session${plan.sessions === 1 ? "" : "s"}.`
    + (back.length ? ` ${back.length} at the back: ${back.map((p) => `${byId.get(p.id).name} ${REASON[p.status] || p.status}`).join(", ")}.` : "")];
  const drifting = placed.filter((p) => p.reason);
  if (drifting.length) lines.push(drifting.map((p) => `${byId.get(p.id).name} ${p.reason}.`).join(" "));
  if (skipped.length) lines.push(`Skipped ${skipped.length} item(s) with no media file (titles, graphics, nests).`);
  if (problems.length) lines.push(`CHECK THE COPY — ${problems.length} problem(s):`, ...problems.map((p) => `  ${p}`));
  lines.push(`Opened ${name}. Ctrl+Z once undoes the placing.`);
  return lines.join("\n");
}

/* deps: { rpc, ensureHelper, onStatus }. Returns { text, problems }. */
async function syncSequence(ppro, deps) {
  const { project, sequence: source } = await activeProjectAndSequence(ppro, {
    sequenceErrorMessage: "Open the sequence with your camera and recorder clips first.",
  });
  if (String(source.name).endsWith(SYNCED_SUFFIX)) {
    throw new Error(`"${source.name}" is already a synced copy. Open the original sequence and run Sync on that.`);
  }
  await deps.ensureHelper();

  deps.onStatus("Reading the timeline's clips…");
  const { clips, skipped } = groupClips(await readSequence(ppro, source));
  if (!clips.length) throw new Error("No clips with a media file on this sequence. Nothing to sync.");
  const plan = await waitForPlan(deps.rpc, clips, deps);

  const ticksPerFrame = toTicks(await source.getTimebase());
  const byId = new Map(plan.placements.map((p) => [p.id, p]));
  const tracks = assignTracks(clips, clips.map((c) => {
    const p = byId.get(c.id);
    return !!p && (p.status === "anchor" || p.status === "synced");
  }));
  const targets = clips.map((clip, i) => {
    const p = byId.get(clip.id);
    if (!p) throw new Error(`The helper returned no place for ${clip.name}.`);
    return { clip, projectItem: clip.projectItem || null, tracks: tracks[i], start: startTicks(p.start_s, !!clip.video, ticksPerFrame),
      mediaTicks: p.media_duration_s === null || p.media_duration_s === undefined ? null
        : BigInt(Math.round(p.media_duration_s * Number(TICKS_PER_SECOND))) };
  });

  const name = `${source.name}${SYNCED_SUFFIX}`;
  deps.onStatus(`Placing ${clips.length} clips in ${name}…`);
  const copyId = await copySequence(project, source, name, targets);
  await placeAll(ppro, project, await findSequence(project, copyId), targets);

  // References go stale across transactions (#18): fetch the copy again before reading it.
  const copy = await findSequence(project, copyId);
  const placedClips = await readSequence(ppro, copy);
  const problems = checkPlacement(placedClips, targets, ticksPerFrame);

  // Restore clip color label if any placed clip (e.g. V1) reverted to default color
  const colorFixActions = [];
  for (const c of [...placedClips.video, ...placedClips.audio]) {
    const isVid = c.kind === "video";
    const t = targets.find((tgt) => (isVid ? tgt.tracks.video === c.track : tgt.tracks.audio <= c.track && c.track < tgt.tracks.audio + tgt.clip.audio.length) && tgt.clip.path === c.path);
    if (t && t.clip.colorLabel !== null && t.clip.colorLabel !== undefined && c.colorLabel !== t.clip.colorLabel) {
      if (typeof c.item.createSetColorLabelAction === "function") {
        const act = c.item.createSetColorLabelAction(t.clip.colorLabel);
        if (act) colorFixActions.push(act);
      }
      if (c.projectItem && typeof c.projectItem.createSetColorLabelAction === "function") {
        const act = c.projectItem.createSetColorLabelAction(t.clip.colorLabel);
        if (act) colorFixActions.push(act);
      }
    }
  }
  if (colorFixActions.length > 0) {
    runTransaction(project, "CutDeck Sync: restore clip colors", (compound) => {
      for (const act of colorFixActions) {
        if (act) compound.addAction(act);
      }
    });
  }

  await project.openSequence(copy);
  await project.setActiveSequence(copy);
  const report = formatReport(name, plan, clips, skipped, problems);
  targets.length = 0;
  clips.length = 0;
  return { text: report, problems };
}

module.exports = { syncSequence, readSequence, mediaPath, groupUnits, groupClips, assignTracks, startTicks,
  checkPlacement, formatReport, SYNCED_SUFFIX, TICKS_PER_SECOND, baseName };
