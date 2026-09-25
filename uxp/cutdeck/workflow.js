/* Host operations kept separate from UI so identity and import behavior can be tested.

   Rough Cut input (docs/arch-design-helper-v2.md move 6): the audio tracks are read natively and
   sent to the helper, which writes the FCP7 subset its analysis reads; nothing is exported.
   Adobe APIs read here: Sequence.getAudioTrackCount/getAudioTrack, AudioTrack.isMuted,
   AudioClipTrackItem.getStartTime/getInPoint/getOutPoint/isDisabled/getProjectItem,
   ClipProjectItem.getMediaFilePath (reference/adobe/api/premierepro.txt:54-88,131,567-568).
   getStartTime/getInPoint/getOutPoint (media-relative) and getMediaFilePath are proven live
   (PREMIERE_FACTS "Track items", "Project items"); isMuted and audio isDisabled are not yet. */
const { activeProjectAndSequence } = require("./host/project.js");
const { toTicks } = require("./host/ticks.js");
const { getTrackClipItems } = require("./host/trackItems.js");
const { mediaPath } = require("./timeline/nativeSync.js");
const VERSION = "cutdeck-xml-5";
const guid = (object) => object.guid.toString();

async function capture(ppro) {
  const { project, sequence } = await activeProjectAndSequence(ppro, {
    sequenceErrorMessage: "Open a sequence and set timeline In/Out marks.",
  });
  const start = await sequence.getInPoint();
  const end = await sequence.getOutPoint();
  const duration = await sequence.getEndTime();
  if (!start || !end || !Number.isFinite(start.seconds) || !Number.isFinite(end.seconds) ||
      start.seconds < 0 || end.seconds <= start.seconds || end.seconds > duration.seconds) {
    throw new Error("Set valid timeline In/Out marks inside the sequence.");
  }
  return { project, sequence, inSeconds: start.seconds, outSeconds: end.seconds,
    context: { project_id: guid(project), sequence_id: guid(sequence), sequence_name: sequence.name,
      in_ticks: start.ticks, out_ticks: end.ticks, end_ticks: duration.ticks,
      ticks_per_frame: await sequence.getTimebase(), audio_track_count: await sequence.getAudioTrackCount() } };
}

/* A state read that fails counts as "on": a clip is left in the analysis rather than dropped. */
async function isOff(read) {
  try { return (await read()) === true; } catch (_) { return false; }
}

/* Every audio track's clips: file, sequence start, source In/Out (ticks as strings), on/off. */
async function readAudioTracks(ppro, sequence, snapshotContext) {
  const tracks = [];
  for (let t = 0; t < snapshotContext.audio_track_count; t++) {
    const track = await sequence.getAudioTrack(t);
    const clips = [];
    for (const item of track ? await getTrackClipItems(track, ppro) : []) {
      let path = null;
      try { path = await mediaPath(ppro, item); } catch (_) { /* nested sequence: no file */ }
      clips.push({ path, enabled: !(await isOff(() => item.isDisabled())),
        start_ticks: toTicks(await item.getStartTime()).toString(),
        in_ticks: toTicks(await item.getInPoint()).toString(),
        out_ticks: toTicks(await item.getOutPoint()).toString() });
    }
    tracks.push({ enabled: !(track && await isOff(() => track.isMuted())), clips });
  }
  return { ticks_per_frame: snapshotContext.ticks_per_frame, end_ticks: snapshotContext.end_ticks,
    audio_tracks: tracks };
}

async function prepare(ppro, rpc, snapshot, options, save) {
  await rpc({ type: "hello", version: VERSION });
  const sequence = await readAudioTracks(ppro, snapshot.sequence, snapshot.context);
  const job = await rpc({ type: "prepare", ...snapshot.context, ...options, sequence });
  // The helper wrote the source from this read, so the job can start (and Resume can start it
  // after a lost reply). `exported` keeps its name: saved jobs from before move 6 carry it.
  job.exported = true;
  save(job);
  const started = await rpc({ type: "start", job_id: job.job_id });
  save({ ...job, ...started });
  return started;
}

module.exports = { VERSION, capture, prepare, readAudioTracks };
