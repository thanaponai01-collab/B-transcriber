/* Host operations kept separate from UI so identity and import behavior can be tested. */
const { CUTDECK_BIN_NAME, getOrCreateBin, activeProjectAndSequence } = require("./host/project.js");
const VERSION = "cutdeck-xml-2";
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

// Kept as an alias for tests and backward compatibility; delegates to host/project.js
const getOrCreateCutDeckBin = (project) => getOrCreateBin(project, [CUTDECK_BIN_NAME]);

async function importResult(ppro, job, previousAttempt, markAttempt) {
  const project = await ppro.Project.getActiveProject();
  if (!project || guid(project) !== job.context.project_id) {
    throw new Error("Return to the original project, then resume this job to open the result.");
  }
  const before = await project.getSequences();
  if (!before.some((s) => guid(s) === job.context.sequence_id)) {
    throw new Error("The source sequence is no longer in this project. The result XML is saved for recovery.");
  }
  const existing = before.filter((s) => s.name === job.result_name && guid(s) !== job.context.sequence_id);
  let result;
  if (existing.length === 1) {
    result = existing[0];
  } else {
    if (previousAttempt || existing.length > 1) {
      throw new Error("A previous import could not be confirmed. Check the Project panel before importing again. Result: " + job.output_path);
    }
    const ids = new Set(before.map(guid));
    markAttempt();
    const targetBin = await getOrCreateCutDeckBin(project);
    const imported = await project.importFiles([job.output_path], true, targetBin, false);
    if (!imported) throw new Error("Premiere did not confirm the XML import. Check the Project panel. Result: " + job.output_path);
    const after = await project.getSequences();
    const matches = after.filter((s) => !ids.has(guid(s)) && s.name === job.result_name);
    if (matches.length !== 1) throw new Error("Could not identify the imported sequence. Check the Project panel for " + job.result_name);
    result = matches[0];
  }
  if (!await project.openSequence(result) || !await project.setActiveSequence(result)) {
    throw new Error("Result imported. Open this sequence from the Project panel: " + job.result_name);
  }
  return result;
}

module.exports = { VERSION, capture, prepare, importResult, getOrCreateCutDeckBin };
