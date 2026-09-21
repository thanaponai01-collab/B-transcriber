/* Host operations kept separate from UI so identity and import behavior can be tested. */
const VERSION = "cutdeck-xml-1";
const guid = (object) => object.guid.toString();

async function capture(ppro) {
  const project = await ppro.Project.getActiveProject();
  if (!project) throw new Error("Open a Premiere project first.");
  const sequence = await project.getActiveSequence();
  if (!sequence) throw new Error("Open a sequence and set timeline In/Out marks.");
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

// Rough cut and multi-cam sync share the whole host sequence; only the prepare request differs.
async function exportAndStart(ppro, rpc, snapshot, prepareType, options, save) {
  await rpc({ type: "hello", version: VERSION });
  const job = await rpc({ type: prepareType, ...snapshot.context, ...options });
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

const prepare = (ppro, rpc, snapshot, options, save) =>
  exportAndStart(ppro, rpc, snapshot, "prepare", options, save);
const prepareSync = (ppro, rpc, snapshot, options, save) =>
  exportAndStart(ppro, rpc, snapshot, "prepare_sync", options, save);

const CUTDECK_BIN_NAME = "CutDeck";

// Finds (or creates once) the project's top-level CutDeck bin, so rough-cut and
// sync results land organized in the Project panel instead of at the root.
// Idempotent: only creates when a bin with this name doesn't already exist.
//
// Premiere's UXP object references can invalidate across an await boundary —
// uxp/spike18_split_probe/README.md hit "The script object is no longer
// valid" from a track-item reference held across a couple of awaits before a
// transaction. Every use of `root` below re-fetches it immediately first
// rather than reusing one held across the executeTransaction call, closing
// the same gap that bit that spike.
async function getOrCreateCutDeckBin(project) {
  const existing = (await (await project.getRootItem()).getItems())
    .find((item) => item.name === CUTDECK_BIN_NAME);
  if (existing) return existing;

  const root = await project.getRootItem();
  const ok = project.executeTransaction((compound) => {
    if (!compound.addAction(root.createBinAction(CUTDECK_BIN_NAME, false))) {
      throw new Error("addAction(createBin) returned false");
    }
  }, `Create ${CUTDECK_BIN_NAME} bin`);
  if (!ok) throw new Error(`Could not create the ${CUTDECK_BIN_NAME} bin in this project.`);

  const bin = (await (await project.getRootItem()).getItems())
    .find((item) => item.name === CUTDECK_BIN_NAME);
  if (!bin) throw new Error(`${CUTDECK_BIN_NAME} bin was created but could not be found afterward.`);
  return bin;
}

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

module.exports = { VERSION, capture, prepare, prepareSync, importResult, getOrCreateCutDeckBin };
