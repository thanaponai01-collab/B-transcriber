// Owns "Thai Transcript": our ASR as the selected clip's Premiere transcript, so the Text panel,
// text-based editing and Create captions work on it. Premiere's speech-to-text has no Thai.
// Must not know: the DOM, how the helper transcribes or builds the JSON.
//
// APIs (reference/adobe/api/premierepro.txt; call pattern from Adobe's sample
// reference/adobe/samples/sample-panels/premiere-api/src/transcript.ts + projectPanel.ts):
// Project.getActiveProject, ProjectUtils.getSelection, ProjectItemSelection.getItems,
// ClipProjectItem.cast/isSequence/getMediaFilePath, Transcript.importFromJSON,
// Transcript.createImportTextSegmentsAction inside lockedAccess + executeTransaction
// (host/project.js runTransaction). Transcript.hasTranscript is NOT IN 26.2.1 (manifest
// minVersion 26.2.0), so it is feature-detected.

const { runTransaction } = require("../host/project.js");

function createTranscriptFeature({ ppro, ctl, rpc, ensureHelper, lastJob }) {
  async function selectedClip(project) {
    const selection = await ppro.ProjectUtils.getSelection(project);
    const items = (selection && (await selection.getItems())) || [];
    const clips = [];
    for (const item of items) {
      const clip = ppro.ClipProjectItem.cast(item);
      if (clip && !(await clip.isSequence())) clips.push(clip);
    }
    if (clips.length !== 1) throw new Error("Select one clip (not a sequence) in the Project panel, then try again.");
    return clips[0];
  }

  function hadTranscript(clip) {
    if (typeof ppro.Transcript.hasTranscript !== "function") return null;
    try { return ppro.Transcript.hasTranscript(clip); } catch (_) { return null; }
  }

  async function doImport() {
    if (lastJob && lastJob()) {
      throw new Error("Resume or dismiss the previous job before starting another operation.");
    }
    const project = await ppro.Project.getActiveProject();
    if (!project) throw new Error("Open a Premiere project first.");
    const clip = await selectedClip(project);
    const mediaPath = await clip.getMediaFilePath();
    if (!mediaPath) throw new Error(`"${clip.name}" has no media file to transcribe.`);

    await ensureHelper();
    ctl.setStatus(`Transcribing ${clip.name}…`, "busy");
    const started = await rpc({ type: "submit_transcribe", media_path: mediaPath });
    const job = await rpc.watch(started.job_id);
    if (job.state !== "ready") throw new Error(job.message || "Transcription failed.");
    const reply = await rpc({ type: "premiere_transcript", job_id: job.job_id });

    const before = hadTranscript(clip);
    runTransaction(project, "Import Thai Transcript", (compound) => {
      const action = ppro.Transcript.createImportTextSegmentsAction(
        ppro.Transcript.importFromJSON(reply.transcript), clip);
      if (!action || !compound.addAction(action)) throw new Error("Premiere refused the transcript import.");
    });
    const replaced = before ? " (replaced its earlier transcript)" : "";
    ctl.setStatus(`Thai transcript on ${clip.name}${replaced}: ${reply.segments} segments, ` +
      `${reply.words} words. Open Window > Text.`, "ready");
    return reply;
  }

  return {
    onImportTranscript: () => ctl.act(doImport),
    doImport,
  };
}

module.exports = { createTranscriptFeature };
