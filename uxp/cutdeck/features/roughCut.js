// Owns the XML rough cut job lifecycle (capture, prepare, follow, import) and job persistence.
// Must not know: the DOM, UI panels, Adjustment Layer or Effects logic.

const workflow = require("../workflow.js");

const KEY = "cutdeck.xml.lastJob";

function lastJob(storage) {
  if (!storage) return null;
  try {
    return JSON.parse(storage.getItem(KEY) || "null");
  } catch (_) {
    return null;
  }
}

function createRoughCutFeature({
  ppro,
  ctl,
  rpc,
  ensureHelper,
  storage = typeof localStorage !== "undefined" ? localStorage : null,
  pollDelay = 1500,
  progressText = () => "Processing sequence in helper… Cuts stay inside marked In/Out.",
}) {
  function readSavedJob() {
    return lastJob(storage);
  }

  function save(job) {
    if (storage) storage.setItem(KEY, JSON.stringify(job));
    ctl.state.job = { id: job.job_id, state: job.state };
    ctl.render();
  }

  function clearJob() {
    if (storage) storage.removeItem(KEY);
    ctl.state.job = null;
    ctl.render();
  }

  async function doRefresh() {
    const snap = await workflow.capture(ppro);
    const count = snap.context.audio_track_count;
    ctl.state.sequence = {
      name: snap.context.sequence_name,
      inSeconds: snap.inSeconds,
      outSeconds: snap.outSeconds,
      audioTrackCount: count,
    };
    if (ctl.state.audioTrack !== null && ctl.state.audioTrack >= count) {
      ctl.state.audioTrack = null;
    }
    ctl.render();
    return snap;
  }

  async function follow(job) {
    while (job.state === "running") {
      ctl.setStatus(progressText(job), "busy");
      await new Promise((resolve) => setTimeout(resolve, pollDelay));
      job = await rpc({ type: "status", job_id: job.job_id });
    }
    if (job.state === "failed") {
      clearJob();
      ctl.setStatus(job.message, "error");
      throw new Error(job.message);
    }
    if (job.state === "no_cuts") {
      clearJob();
      ctl.setStatus("No cuts found inside this range. Your sequence is unchanged.", "ready");
      return;
    }
    if (job.state !== "ready") {
      ctl.setStatus("Job error: " + job.state, "error");
      throw new Error("Job is not ready: " + job.state);
    }
    ctl.setStatus("Opening your rough cut in Premiere…", "busy");
    const saved = readSavedJob() || {};
    await workflow.importResult(
      ppro,
      job,
      saved.importAttempted,
      () => save({ ...saved, ...job, importAttempted: true })
    );
    clearJob();
    const note = job.output_note ? `\n${job.output_note}` : "";
    ctl.setStatus(
      `${job.report.cuts_applied} cuts · ${(job.report.removed_ms / 1000).toFixed(1)} seconds removed.`
      + `\nOpened ${job.result_name}\nSaved ${job.output_path}${note}`,
      "ready"
    );
  }

  async function doCut() {
    if (readSavedJob()) {
      throw new Error("Resume the previous job before starting another rough cut.");
    }
    if (ensureHelper) await ensureHelper();
    const snap = await doRefresh();
    ctl.setStatus("Preparing your sequence…", "busy");
    const job = await workflow.prepare(
      ppro,
      rpc,
      snap,
      { audio_track: ctl.state.audioTrack, asr: ctl.state.cutMode === "protected" },
      save
    );
    await follow(job);
  }

  async function doResume() {
    const saved = readSavedJob();
    if (!saved) return;
    if (ensureHelper) await ensureHelper();
    await rpc({ type: "hello", version: workflow.VERSION });
    let job;
    try {
      job = await rpc({ type: "status", job_id: saved.job_id });
    } catch (error) {
      if (error.message && error.message.startsWith("Unknown job")) clearJob();
      throw error;
    }
    if (job.state === "prepared") {
      if (!saved.exported) {
        clearJob();
        ctl.setStatus("The previous export did not finish. Start a new rough cut.", "ready");
        return;
      }
      job = await rpc({ type: "start", job_id: saved.job_id });
    }
    await follow(job);
  }

  async function doDismiss() {
    const saved = readSavedJob();
    clearJob();
    ctl.setStatus(
      "Previous job dismissed. Any running analysis continues in the helper. Saved result location:\n"
      + (saved ? saved.output_path : ""),
      "ready"
    );
  }

  return {
    onRefresh: () => ctl.act(async () => {
      await doRefresh();
      ctl.setStatus("Range ready", "ready");
    }),
    onCut: () => ctl.act(doCut),
    onResumeJob: () => ctl.act(doResume),
    onDismissJob: () => ctl.act(doDismiss),
    onCutMode: (mode) => {
      ctl.state.cutMode = mode;
      ctl.render();
    },
    // Exposed helpers
    refresh: doRefresh,
    follow,
    lastJob: readSavedJob,
    save,
    clearJob,
  };
}

module.exports = {
  createRoughCutFeature,
  lastJob,
  KEY,
};
