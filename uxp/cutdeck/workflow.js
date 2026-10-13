/* Host operations kept separate from UI so identity and import behavior can be tested.

   Rough Cut input (docs/arch-design-helper-v2.md move 6): the audio tracks are read natively and
   sent to the helper as sequence.json; nothing is exported.
   Adobe APIs read here: Sequence.getAudioTrackCount/getAudioTrack, AudioTrack.isMuted,
   AudioClipTrackItem.getStartTime/getInPoint/getOutPoint/isDisabled/getSpeed/getProjectItem,
   ClipProjectItem.getMediaFilePath (reference/adobe/api/premierepro.txt:54-88,131,567-568).
   getStartTime/getInPoint/getOutPoint (media-relative) and getMediaFilePath are proven live
   (PREMIERE_FACTS "Track items", "Project items"); isMuted and audio isDisabled are not yet. */
const { activeProjectAndSequence } = require("./host/project.js");
const { toTicks } = require("./host/ticks.js");
const { getTrackClipItems } = require("./host/trackItems.js");
const { mediaPath } = require("./host/sequenceRead.js");
const VERSION = "cutdeck-6";
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
    // Every clip of the track is read at once (as nativeSync.listClips does): one awaited call
    // after another made this read grow with ~8 host round trips per clip.
    const clips = await Promise.all((track ? await getTrackClipItems(track, ppro) : []).map(async (item) => {
      let path = null;
      try { path = await mediaPath(ppro, item); } catch (_) { /* nested sequence: no file */ }
      // Sent only when it is not 100%; a read that fails counts as normal speed, like isOff above.
      let speed = 1;
      try { speed = Number(await item.getSpeed()); } catch (_) { /* not reported */ }
      const [disabled, start, inPoint, outPoint] = await Promise.all([
        isOff(() => item.isDisabled()), item.getStartTime(), item.getInPoint(), item.getOutPoint()]);
      return { path, enabled: !disabled,
        start_ticks: toTicks(start).toString(),
        in_ticks: toTicks(inPoint).toString(),
        out_ticks: toTicks(outPoint).toString(),
        ...(Number.isFinite(speed) && speed > 0 && speed !== 1 ? { speed } : {}) };
    }));
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

// Only analysis inputs matter. Host enumeration order may change after a fresh read.
function audioSnapshotSignature(sequence) {
  return JSON.stringify({ ticks_per_frame: String(sequence.ticks_per_frame), end_ticks: String(sequence.end_ticks),
    audio_tracks: sequence.audio_tracks.map((track) => ({ enabled: track.enabled,
      clips: track.clips.map((clip) => JSON.stringify([clip.path, clip.enabled, String(clip.start_ticks),
        String(clip.in_ticks), String(clip.out_ticks), clip.speed === undefined ? 1 : clip.speed])).sort() })) });
}

async function assertSourceAudioUnchanged(ppro, source, expected) {
  const current = await readAudioTracks(ppro, source, {
    audio_track_count: await source.getAudioTrackCount(),
    ticks_per_frame: await source.getTimebase(), end_ticks: toTicks(await source.getEndTime()).toString(),
  });
  if (audioSnapshotSignature(current) !== audioSnapshotSignature(expected)) {
    const error = new Error("The source audio or sequence duration changed since analysis. Start a new Rough Cut.");
    error.staleSource = true;
    throw error;
  }
}

module.exports = { VERSION, capture, prepare, readAudioTracks, assertSourceAudioUnchanged };
