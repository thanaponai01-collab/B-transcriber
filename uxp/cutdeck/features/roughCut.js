// Owns the rough cut job lifecycle (capture, prepare, follow, native apply) and job persistence.
// The helper analyses an XML export of the sequence; the cuts are applied natively to a copy
// (timeline/nativeCut.js). The XML *output* route is retired (HANDOFF_CUTDECK_NATIVE_ROUGH_CUT Phase 6).
// Must not know: the DOM, UI panels, Adjustment Layer or Effects logic.

const workflow = require("../workflow.js");
const { applyNativeCut } = require("../timeline/nativeCut.js");
const { activeProjectAndSequence } = require("../host/project.js");
const { TICKS_PER_SECOND } = require("../host/ticks.js");

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
    if (job.output !== "native") {
      // Started before the XML output route was retired; there is no cut list to apply.
      clearJob();
      throw new Error("That job was started with the old XML Rough Cut, which is retired. Start a new Rough Cut.");
    }
    await nativeCut(job);
  }

  // The cuts are applied natively to a copy of the analysed sequence.
  async function nativeCut(job) {
    const { project, sequence } = await activeProjectAndSequence(ppro, {
      sequenceErrorMessage: `Open "${job.context.sequence_name}" to cut it, then Resume.`,
    });
    if (sequence.guid.toString() !== job.context.sequence_id) {
      throw new Error(`Open "${job.context.sequence_name}" to cut it, then Resume.`);
    }
    ctl.setStatus("Cutting a copy of your sequence in Premiere…", "busy");
    const r = await applyNativeCut(ppro, project, sequence, job.cuts, job.result_name);
    clearJob();
    const seconds = Number(r.removedTicks * 10n / TICKS_PER_SECOND) / 10;
    ctl.setStatus(`${r.cuts} cuts · ${seconds.toFixed(1)} seconds removed.\nOpened ${r.name}`
      + (r.splits ? `\n${r.splits} clips were split: the pieces' audio is not linked to their video (select both to move them).` : "")
      + `\nChecked clip by clip. Undo takes ${r.steps} Ctrl+Z; your original sequence is untouched.`, "ready");
  }

  async function doCut() {
    // A pending job is finished first, never silently replaced: the cut button resumes it, so
    // recovery never depends on the job banner being visible.
    if (readSavedJob()) {
      ctl.setStatus("Finishing the previous job first…", "busy");
      await doResume();
      return;
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
    clearJob();
    ctl.setStatus("Previous job dismissed. Any running analysis continues in the helper.", "ready");
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
