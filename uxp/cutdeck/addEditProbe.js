/* "Test Native Add Edit": one native Add Edit to All Tracks on a copy of the active sequence,
   through the CutDeck Cutter Probe Control Surface plugin (tools/native-cutter-spike). UXP has no
   razor on 26.x (PREMIERE_FACTS "razor / split … ABSENT"); the plugin runs one fixed command and
   cannot be told where to cut, so this panel binds the target and checks the result:
   plan in docs/research/cutdeck-native-cutter-2026-10-16.md, "Plan: one Add Edit".

   APIs, all declared in reference/adobe/api/premierepro.txt (26.5.1): Sequence.createCloneAction,
   ProjectItem.createSetNameAction, Project.openSequence / setActiveSequence / getActiveSequence /
   getSequences, Sequence.setPlayerPosition / getPlayerPosition / getZeroPoint / getTimebase / guid,
   Video/AudioClipTrackItem.getIsSelected, TickTime.createWithTicks (PREMIERE_FACTS: WORKS); the
   timeline read is host/sequenceRead.js. setPlayerPosition and getZeroPoint have no live facts row
   yet: the playhead is read back, and the plugin refuses unless Premiere's displayed timecode is
   the one computed here, so a wrong guess about either stops the test instead of cutting elsewhere.
   The helper request is `native_split_request` (cutdeck/native_split.py). Your sequence is not edited.

   "Check Add Edit" re-reads the copy afterwards: which pieces are selected (click one piece first:
   linked pieces select together) and whether the copy matches the before or after read
   (press Ctrl+Z or Ctrl+Shift+Z first). */

const { runTransaction, activeProjectAndSequence } = require("./host/project.js");
const { TICKS_PER_SECOND, toTicks, makeTickTime } = require("./host/ticks.js");
const { readSequence } = require("./host/sequenceRead.js");

const CUT_FRAME = 120n;
const MIN_FRAMES = 240n;
let last = null; // the latest run, for "Check Add Edit"

const rowOf = (c) => ({ kind: c.kind, track: c.track, start: c.start, end: c.end, inPoint: c.inPoint, path: c.path || null });
const key = (r) => `${r.kind}|${r.track}|${r.start}|${r.end}|${r.inPoint}|${r.path}`;
const where = (r) => `${r.kind} track ${r.track + 1}`;

async function readRows(ppro, seq) {
  const s = await readSequence(ppro, seq);
  return [...s.video, ...s.audio].map((c) => ({ ...rowOf(c), item: c.item }));
}

/* Premiere's SMPTE display for a whole-frame time at a whole-number frame rate. */
function smpte(frames, fps) {
  const pad = (n) => String(n).padStart(2, "0");
  const seconds = frames / fps;
  return `${pad(seconds / 3600n)}:${pad((seconds / 60n) % 60n)}:${pad(seconds % 60n)}:${pad(frames % fps)}`;
}

/* The one shape this test accepts: one video clip and its audio, all spanning the same time. */
function checkFixture(rows, tpf) {
  const video = rows.filter((r) => r.kind === "video");
  const audio = rows.filter((r) => r.kind === "audio");
  if (video.length !== 1 || !audio.length) return "Open a sequence with exactly one video clip and its audio.";
  const [v] = video;
  if (audio.some((a) => a.start !== v.start || a.end !== v.end)) return "The audio must start and end with the video clip.";
  if ((v.end - v.start) / tpf < MIN_FRAMES) return `The clip must be at least ${MIN_FRAMES} frames long.`;
  return null;
}

/* Every clip that spans `at` must become exactly [start, at) and [at, end) of the same media,
   with the source time continuing; every other clip must be unchanged. */
function verifySplit(before, after, at) {
  const problems = [];
  const remaining = new Map();
  for (const r of after) remaining.set(key(r), (remaining.get(key(r)) || 0) + 1);
  const take = (r, label) => {
    const k = key(r);
    if (remaining.get(k)) remaining.set(k, remaining.get(k) - 1);
    else problems.push(`missing ${label} on ${where(r)}: ${r.start}-${r.end} in ${r.inPoint}`);
  };
  let crossing = 0;
  for (const r of before) {
    if (r.start < at && at < r.end) {
      crossing += 1;
      take({ ...r, end: at }, "left piece");
      take({ ...r, start: at, inPoint: r.inPoint + (at - r.start) }, "right piece");
    } else take(r, "unchanged clip");
  }
  for (const [k, n] of remaining) for (let i = 0; i < n; i++) problems.push(`unexpected clip ${k.replace(/\|/g, " ")}`);
  if (after.length !== before.length + crossing) problems.push(`${after.length} clips after, expected ${before.length + crossing}`);
  return problems;
}

const sameRows = (a, b) => verifySplit(a, b, -1n).length === 0;

async function probeAddEdit(ppro, { rpc } = {}) {
  const report = { verdict: "error", sequence: null, copyName: null, cutTicks: null, expectedTimecode: null, problems: [] };
  try {
    if (typeof rpc !== "function") throw new Error("The helper connection is missing.");
    const tickTime = makeTickTime(ppro);
    if (!tickTime) throw new Error("TickTime.createWithTicks is missing on this build.");
    const { project, sequence: source } = await activeProjectAndSequence(ppro);
    report.sequence = source.name;
    const tpf = toTicks(await source.getTimebase());
    if (tpf <= 0n || TICKS_PER_SECOND % tpf !== 0n) {
      report.verdict = "refused";
      report.problems = ["The sequence frame rate is not a whole number of frames per second (the timecode check needs one)."];
      return report;
    }
    const fps = TICKS_PER_SECOND / tpf;
    const sourceRows = await readRows(ppro, source);
    const shape = checkFixture(sourceRows, tpf);
    if (shape) { report.verdict = "refused"; report.problems = [shape]; return report; }
    const clip = sourceRows.find((r) => r.kind === "video");
    const at = clip.start + CUT_FRAME * tpf;
    const zero = toTicks(await source.getZeroPoint());
    if ((zero + at) % tpf !== 0n) { report.verdict = "refused"; report.problems = ["The sequence start time is not on a frame."]; return report; }
    report.cutTicks = at.toString();
    report.expectedTimecode = smpte((zero + at) / tpf, fps);

    const beforeIds = new Set((await project.getSequences()).map((s) => s.guid.toString()));
    runTransaction(project, "CutDeck: copy sequence (Add Edit test)", (compound) => {
      if (!compound.addAction(source.createCloneAction())) throw new Error("addAction(copy sequence) returned false");
    });
    const created = (await project.getSequences()).filter((s) => !beforeIds.has(s.guid.toString()));
    if (created.length !== 1) throw new Error(`Copying the sequence gave ${created.length} new sequences`);
    const copy = created[0];
    report.copyName = `CutDeck AddEdit Probe ${Date.now().toString(36)}`;
    const copyItem = await copy.getProjectItem();
    runTransaction(project, "CutDeck: name Add Edit test", (compound) => {
      if (!compound.addAction(copyItem.createSetNameAction(report.copyName))) throw new Error("addAction(rename) returned false");
    });

    // Bind: the copy is the active sequence and its playhead is on the cut frame, both read back.
    await project.openSequence(copy);
    await project.setActiveSequence(copy);
    await copy.setPlayerPosition(tickTime(at));
    const bound = await project.getActiveSequence();
    if (!bound || bound.guid.toString() !== copy.guid.toString()) throw new Error("The copy did not become the active sequence.");
    if (toTicks(await copy.getPlayerPosition()) !== at) throw new Error("The playhead did not land on the cut frame.");
    const before = await readRows(ppro, copy);
    if (!sameRows(before, sourceRows)) throw new Error("The copy differs from your sequence.");
    for (const r of before) {
      if (await r.item.getIsSelected()) {
        report.verdict = "refused";
        report.problems = ["Deselect every clip first: Add Edit can act on selected clips only."];
        return report;
      }
    }

    report.native = await rpc({ type: "native_split_request", expected_timecode: report.expectedTimecode });
    last = { copyGuid: copy.guid.toString(), at, before, after: null };
    if (!report.native || report.native.status !== "executed") {
      report.verdict = "not-run";
      return report;
    }
    const still = await project.getActiveSequence();
    if (!still || still.guid.toString() !== copy.guid.toString()) report.problems.push("The active sequence changed during the cut.");
    if (toTicks(await copy.getPlayerPosition()) !== at) report.problems.push("The playhead moved during the cut.");
    const after = await readRows(ppro, copy);
    last.after = after;
    report.problems.push(...verifySplit(before, after, at));
    if (!sameRows(await readRows(ppro, source), sourceRows)) report.problems.push("Your sequence changed.");
    report.verdict = report.problems.length ? "mismatch" : "exact";
  } catch (error) {
    report.verdict = "error";
    report.error = (error && error.message) || String(error);
  }
  return report;
}

/* After the user clicks a piece, or presses Ctrl+Z / Ctrl+Shift+Z, in the copy. */
async function checkAddEdit(ppro) {
  const report = { verdict: "error", state: null, selected: [], linked: null };
  try {
    if (!last) { report.verdict = "no-run"; return report; }
    const { project } = await activeProjectAndSequence(ppro, { requireSequence: false });
    const copy = (await project.getSequences()).find((s) => s.guid.toString() === last.copyGuid);
    if (!copy) { report.verdict = "no-copy"; return report; }
    const rows = await readRows(ppro, copy);
    report.state = sameRows(rows, last.before) ? "before" : last.after && sameRows(rows, last.after) ? "after" : "neither";
    const selected = [];
    for (const r of rows) if (await r.item.getIsSelected()) selected.push(r);
    report.selected = selected.map((r) => `${where(r)} ${r.start < last.at ? "left" : "right"}`);
    const video = selected.filter((r) => r.kind === "video");
    if (report.state === "after" && video.length === 1) {
      const left = video[0].start < last.at;
      const sideAudio = rows.filter((r) => r.kind === "audio" && (r.start < last.at) === left);
      const selectedAudio = selected.filter((r) => r.kind === "audio");
      report.linked = selectedAudio.length === sideAudio.length && selectedAudio.every((r) => (r.start < last.at) === left);
    }
    report.verdict = "read";
  } catch (error) {
    report.verdict = "error";
    report.error = (error && error.message) || String(error);
  }
  return report;
}

function formatAddEditReport(r) {
  const lines = [];
  if (r.verdict === "exact") lines.push(`Native Add Edit cut every track exactly at ${r.expectedTimecode}; nothing else changed.`);
  else if (r.verdict === "mismatch") {
    lines.push(`Native Add Edit did NOT match the expected split: ${r.problems.length} problem(s).`);
    for (const p of r.problems.slice(0, 10)) lines.push(`  ${p}`);
  } else if (r.verdict === "not-run") {
    const n = r.native || {};
    lines.push(`Not cut: the plugin answered ${n.status || "nothing"}${n.reason ? ` (${n.reason})` : ""}.`);
    if (n.time_before) lines.push(`Premiere showed ${n.time_before}; expected ${r.expectedTimecode}.`);
    if (n.message) lines.push(n.message);
  } else if (r.verdict === "refused") lines.push(`Not run: ${r.problems[0]}`);
  else lines.push(`Add Edit test stopped: ${r.error}`);
  if (r.copyName) lines.push(`Test copy: "${r.copyName}". Your sequence was not edited.`);
  if (r.verdict === "exact" || r.verdict === "mismatch") {
    lines.push("Next: click the left video piece, then Check Add Edit (links). Then Ctrl+Z and Check Add Edit (undo).");
  }
  return lines.join("\n");
}

function formatCheckReport(r) {
  if (r.verdict === "no-run") return "Run Test Native Add Edit first.";
  if (r.verdict === "no-copy") return "The Add Edit test copy is gone.";
  if (r.verdict === "error") return `Check stopped: ${r.error}`;
  const state = { before: "matches the read BEFORE the cut (undone)", after: "matches the read AFTER the cut", neither: "matches neither read" }[r.state];
  const lines = [`Test copy ${state}.`];
  lines.push(r.selected.length ? `Selected: ${r.selected.join(", ")}.` : "Nothing selected.");
  if (r.linked !== null) lines.push(r.linked ? "Links kept: the audio on the same side selected with the video." : "Links NOT kept: the selected audio does not match the video piece.");
  return lines.join("\n");
}

module.exports = { probeAddEdit, checkAddEdit, formatAddEditReport, formatCheckReport, verifySplit, smpte, checkFixture,
  _reset: () => { last = null; } };
