/* Host operations kept separate from UI so identity and import behavior can be tested. */
const { activeProjectAndSequence } = require("./host/project.js");
const VERSION = "cutdeck-xml-3";
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

async function prepare(ppro, rpc, snapshot, options, save) {
  await rpc({ type: "hello", version: VERSION });
  const job = await rpc({ type: "prepare", ...snapshot.context, ...options });
  save(job);
  if (!ppro.ProjectConverter || typeof ppro.ProjectConverter.exportAsFinalCutProXML !== "function") {
    throw new Error("This Premiere build does not expose XML export. CutDeck requires Premiere 26.2 or later.");
  }
  const ok = await ppro.ProjectConverter.exportAsFinalCutProXML(snapshot.sequence, job.source_path, true);
  if (!ok) throw new Error("Premiere could not export the sequence. No rough cut was started.");
  // Record successful export before starting, allowing recovery from a lost start response.
  job.exported = true;
  save(job);
  // The helper only settles output_path once it can read the export, so keep the
  // recovery entry on the started job rather than the prepared one.
  const started = await rpc({ type: "start", job_id: job.job_id });
  save({ ...job, ...started });
  return started;
}

module.exports = { VERSION, capture, prepare };
