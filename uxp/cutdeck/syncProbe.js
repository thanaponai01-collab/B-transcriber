/* Native Sync probe ("Test Sync Moves"). Answers, from the real host, what the native Sync
   button needs before it is built (plan agreed 2026-09-23: one V/A track pair per clip, placed
   in Premiere, no XML):

     1. can every clip's media file path be read? (the helper matches audio from the files)
     2. does createCloneTrackItemAction put a clip on a NEW track and bring its linked audio,
        with the same number of audio clips (no merge, no duplicate)?
        First live run (2026-09-24): NO — the clone copies the video only. So the probe also
        tries route C (clone the audio clips on their own; lands, but unlinked) and
     3. does an audio clip accept a start between two frames? (the two-mic echo fix)
     4. route B: does placing the clip from its file (overwrite, like a drag from the bin) land
        video and all its audio together, where the user can check the link?
     5. how long do 100 clones take in one transaction? (one Undo should remove them all)

   NOT read-only, but it never edits the user's sequence: it copies the active sequence first
   (Sequence.createCloneAction), renames the copy "... — CutDeck sync test", and edits only that.
   Every API used is declared in @adobe/premierepro 26.2.1's premierepro.d.ts. Links are not
   readable through the API at all, so the report ends by asking the user to click the copy.

   Like capabilityProbe.js, nothing here throws at the caller: a failed call is a finding. */

const { attempt, finding, formatFindings } = require("./capabilityProbe.js");
const { runTransaction } = require("./host/project.js");
const { TICKS_PER_SECOND, toTicks } = require("./host/ticks.js");
// Shared with native Sync, which owns them.
const { readSequence, groupUnits, baseName } = require("./timeline/nativeSync.js");

const SPEED_CLONES = 100;
const TEST_SUFFIX = " — CutDeck sync test";

const startingAt = (clips, start) => clips.filter((c) => c.start === start);
const trackList = (clips) => [...new Set(clips.map((c) => c.track + 1))].join(", ");

/* What a half-frame move of an audio clip did, from where it started and where it is now. */
function classifySubframe(before, after, ticksPerFrame) {
  const moved = after - before;
  if (moved === ticksPerFrame / 2n) return "between-frames";
  if (moved === 0n) return "ignored";
  if (moved % ticksPerFrame === 0n) return "snapped";
  return "other";
}

async function probeSyncMoves(ppro, deps = {}) {
  const now = deps.now || (() => Date.now());
  const findings = [];
  const add = (...args) => { findings.push(finding(...args)); return findings[findings.length - 1]; };
  const stop = () => ({ probe: "sync-moves", complete: false, findings, verdict: null });
  const tick = (n) => ppro.TickTime.createWithTicks(n.toString());

  const projectRead = await attempt("getActiveProject", () => ppro.Project.getActiveProject());
  if (!projectRead.ok || !projectRead.value) {
    add("project", "Is a project open?", "no", projectRead.ok ? null : projectRead);
    return stop();
  }
  const project = projectRead.value;
  const seqRead = await attempt("getActiveSequence", () => project.getActiveSequence());
  if (!seqRead.ok || !seqRead.value) {
    add("sequence", "Is a sequence open?", "no", seqRead.ok ? null : seqRead);
    return stop();
  }
  const source = seqRead.value;
  if (String(source.name).endsWith(TEST_SUFFIX)) {
    add("sequence", "Is this your own sequence?", "no — this is a test copy. Open your original sequence and run again.");
    return stop();
  }

  // 1. Read the original: every clip, and the file behind it.
  const origRead = await attempt("read original", () => readSequence(ppro, source));
  if (!origRead.ok) { add("read", "Can the sequence's clips be read?", "no", origRead); return stop(); }
  const orig = origRead.value;
  const all = [...orig.video, ...orig.audio];
  const unreadable = all.filter((c) => !c.path).length;
  add("read", "Can every clip's media file be read? (Sync matches audio from the files)",
    unreadable ? `${all.length - unreadable} of ${all.length} — ${unreadable} have no readable file` : `yes — all ${all.length} clips`,
    { videoClips: orig.video.length, audioClips: orig.audio.length,
      example: all.find((c) => c.path) ? all.find((c) => c.path).path : null });

  const unit = groupUnits(orig.video, orig.audio).find((u) => u.audio.length > 0);
  if (!unit) {
    add("unit", "Is there a camera clip with its audio to test on?", "no — put at least one camera clip with its audio on this timeline");
    return stop();
  }
  const channels = unit.audio.length;
  add("unit", "Which clip will be tested?",
    `${baseName(unit.video.path)} on V${unit.video.track + 1} — 1 video + ${channels} audio clip(s) on A${trackList(unit.audio)}`);

  // Copy the sequence; everything below edits the copy only.
  const beforeIds = new Set((await project.getSequences()).map((s) => s.guid.toString()));
  const copyRead = await attempt("createCloneAction", () => runTransaction(project, "CutDeck sync test: copy sequence", (compound) => {
    if (!compound.addAction(source.createCloneAction())) throw new Error("addAction(copy sequence) returned false");
  }));
  const created = copyRead.ok ? (await project.getSequences()).filter((s) => !beforeIds.has(s.guid.toString())) : [];
  if (created.length !== 1) {
    add("copy", "Can the sequence be copied, so your original stays untouched?",
      copyRead.ok ? `unclear — ${created.length} new sequences appeared; stopped` : "no", copyRead.ok ? null : copyRead);
    return stop();
  }
  const copy = created[0];
  const testName = `${source.name}${TEST_SUFFIX}`;
  const renamed = await attempt("rename copy", async () => {
    const item = await copy.getProjectItem();
    runTransaction(project, "CutDeck sync test: name copy", (compound) => {
      if (!compound.addAction(item.createSetNameAction(testName))) throw new Error("addAction(rename) returned false");
    });
  });
  await attempt("open copy", async () => { await project.openSequence(copy); await project.setActiveSequence(copy); });
  add("copy", "Can the sequence be copied, so your original stays untouched?",
    `yes — "${renamed.ok ? testName : copy.name}"`, renamed.ok ? null : { rename: renamed.error });

  const c0Read = await attempt("read copy", () => readSequence(ppro, copy));
  const c0 = c0Read.ok ? c0Read.value : null;
  const cu = c0 && groupUnits(c0.video, c0.audio)
    .find((u) => u.video.track === unit.video.track && u.video.start === unit.video.start && u.video.path === unit.video.path);
  if (!cu) { add("copy-read", "Does the copy hold the same clip?", "no — stopped", c0Read.ok ? null : c0Read); return stop(); }

  const ticksPerFrame = toTicks(await copy.getTimebase());
  const endTicks = toTicks(await copy.getEndTime());
  const toFrame = (t) => ((t + ticksPerFrame - 1n) / ticksPerFrame) * ticksPerFrame;
  const target = toFrame(endTicks + TICKS_PER_SECOND);
  const offset = target - cu.video.start;
  const firstAudioTrack = Math.min(...cu.audio.map((a) => a.track));
  // `item` is re-read before each transaction: references fetched before one can go stale (#18).
  const cloneAction = (item, vOffset, aOffset, timeOffset, alignToVideo = true) => ppro.SequenceEditor.getEditor(copy)
    .createCloneTrackItemAction(item, tick(timeOffset), vOffset, aOffset, alignToVideo, false);
  const findSource = (seq) => seq.video.find((c) => c.track === cu.video.track && c.start === cu.video.start);

  // 2. Clone the clip to one past the last video and audio track, after the sequence end.
  const vOffset = c0.videoTracks - cu.video.track;
  const aOffset = c0.audioTracks - firstAudioTrack;
  const cloneRead = await attempt("createCloneTrackItemAction", () => runTransaction(project, "CutDeck sync test: clone to new track", (compound) => {
    if (!compound.addAction(cloneAction(cu.video.item, vOffset, aOffset, offset))) throw new Error("addAction(clone clip) returned false");
  }));
  const c1 = await readSequence(ppro, copy);
  const landedV = startingAt(c1.video, target);
  const landedA = startingAt(c1.audio, target);
  const newTrack = c1.videoTracks > c0.videoTracks;
  add("clone", "Clone the clip's video onto a NEW track — did it land?",
    !cloneRead.ok ? "no — the clone call failed"
      : landedV.length ? `yes — V${landedV[0].track + 1}${newTrack ? " (a new track was created)" : " (no new track was created; it landed on an existing one)"}`
        : "no — nothing landed",
    { videoTracksBefore: c0.videoTracks, videoTracksAfter: c1.videoTracks, error: cloneRead.ok ? null : cloneRead.error });
  const audioAnswer = landedA.length === channels ? `yes — ${channels} audio clip(s) on A${trackList(landedA)}, same as the original`
    : landedA.length === 0 ? "no — only the video was copied"
      : landedA.length > channels ? `DUPLICATED — ${landedA.length} audio clips, the original has ${channels}`
        : `PARTIAL — ${landedA.length} of ${channels} audio clips`;
  add("audio", "Did its audio come along, with the same number of audio clips?", audioAnswer,
    { originalAudioTracks: trackList(cu.audio), audioTracksBefore: c0.audioTracks, audioTracksAfter: c1.audioTracks });

  if (!landedV.length) return { probe: "sync-moves", complete: false, findings, verdict: "clone-failed" };

  // 2b. Route C: when the clone left the audio behind, clone each audio clip on its own.
  let audioHere = landedA;
  let separateAudio = null;
  if (!landedA.length) {
    const fresh = await readSequence(ppro, copy);
    const sources = cu.audio.map((a) => fresh.audio.find((c) => c.track === a.track && c.start === a.start)).filter(Boolean);
    const sepRead = await attempt("clone audio", () => runTransaction(project, "CutDeck sync test: clone audio", (compound) => {
      for (const a of sources) {
        if (!compound.addAction(cloneAction(a.item, 0, c0.audioTracks - firstAudioTrack, offset, false))) throw new Error("addAction(clone audio) returned false");
      }
    }));
    audioHere = startingAt((await readSequence(ppro, copy)).audio, target);
    separateAudio = sepRead.ok && audioHere.length === channels;
    add("audio-separate", "Route C — clone the audio clips on their own: did they land?",
      separateAudio ? `yes — ${channels} audio clip(s) on A${trackList(audioHere)} (NOT linked to the video)`
        : sepRead.ok ? `${audioHere.length} of ${channels} landed` : "no — the call failed",
      { audioTracksNow: (await copy.getAudioTrackCount()), error: sepRead.ok ? null : sepRead.error });
  }

  // 3. Move the copied audio by half a frame and read back where Premiere put it.
  let subframe = null;
  if (audioHere.length) {
    const a = audioHere[0];
    const moveRead = await attempt("createMoveAction", () => runTransaction(project, "CutDeck sync test: half-frame audio", (compound) => {
      if (!compound.addAction(a.item.createMoveAction(tick(ticksPerFrame / 2n)))) throw new Error("addAction(move) returned false");
    }));
    const c2 = await readSequence(ppro, copy);
    const near = (clips, track) => clips.find((c) => c.track === track && c.start >= target && c.start <= target + ticksPerFrame);
    const aAfter = near(c2.audio, a.track);
    const vAfter = near(c2.video, landedV[0].track);
    subframe = moveRead.ok && aAfter ? classifySubframe(target, aAfter.start, ticksPerFrame) : "failed";
    const answers = { "between-frames": "yes — it sits between two frames", ignored: "no — it did not move",
      snapped: "no — it snapped to a whole frame", other: "moved by an unexpected amount", failed: "no — the move failed" };
    add("subframe", "Can an audio clip start between two frames? (fixes two-mic echo)", answers[subframe],
      { askedTicks: (target + ticksPerFrame / 2n).toString(), gotTicks: aAfter ? aAfter.start.toString() : null,
        videoAlsoMoved: vAfter ? vAfter.start !== target : null, error: moveRead.ok ? null : moveRead.error });
  }

  // 4. Route B: place the clip's file on fresh tracks, like a drag from the bin — Premiere lays
  // video and audio down together. Overwrite first; the typings document track creation only
  // for insert, so insert is the fallback (after the sequence end there is nothing to ripple).
  const span = toFrame(cu.video.end - cu.video.start) + ticksPerFrame;
  const target2 = target + span;
  const beforePlace = await readSequence(ppro, copy);
  const placeSource = findSource(beforePlace) || cu.video;
  const placeRead = async (label, make) => {
    const r = await attempt(label, async () => {
      const projectItem = await placeSource.item.getProjectItem();
      const editor = ppro.SequenceEditor.getEditor(copy);
      runTransaction(project, `CutDeck sync test: ${label}`, (compound) => {
        if (!compound.addAction(make(editor, projectItem))) throw new Error(`addAction(${label}) returned false`);
      });
    });
    const now2 = await readSequence(ppro, copy);
    return { r, seq: now2, v: startingAt(now2.video, target2), a: startingAt(now2.audio, target2) };
  };
  let placed = await placeRead("overwrite from file", (editor, pi) =>
    editor.createOverwriteItemAction(pi, tick(target2), beforePlace.videoTracks, beforePlace.audioTracks));
  let placeHow = "overwrite";
  if (!placed.v.length && !placed.a.length) {
    placed = await placeRead("insert from file", (editor, pi) =>
      editor.createInsertProjectItemAction(pi, tick(target2), beforePlace.videoTracks, beforePlace.audioTracks, false));
    placeHow = "insert";
  }
  const placedLength = placed.v.length ? placed.v[0].end - placed.v[0].start : null;
  const fromFile = placed.v.length === 1 && placed.a.length === channels;
  add("place", "Route B — place the clip from its file (like a drag from the bin): did video AND audio land?",
    !placed.v.length && !placed.a.length ? "no — nothing landed"
      : `${placed.v.length ? `video on V${placed.v[0].track + 1}` : "NO video"}, ${placed.a.length} audio clip(s)${placed.a.length ? ` on A${trackList(placed.a)}` : ""} (original has ${channels})`,
    { method: placeHow, sameLengthAsOriginal: placedLength === null ? null : placedLength === cu.video.end - cu.video.start,
      videoTracksNow: placed.seq.videoTracks, audioTracksNow: placed.seq.audioTracks, error: placed.r.ok ? null : placed.r.error });

  // 5. Speed: many clones in ONE transaction, each on its own new track when (2) could make one.
  const before = await readSequence(ppro, copy);
  const sameFile = (seq) => seq.video.filter((c) => c.path === cu.video.path).length;
  const sourceItem = (findSource(before) || cu.video).item;
  const started = now();
  const speedRead = await attempt("speed", () => runTransaction(project, `CutDeck sync test: ${SPEED_CLONES} clones`, (compound) => {
    for (let i = 1; i <= SPEED_CLONES; i++) {
      const action = newTrack
        ? cloneAction(sourceItem, vOffset + i, aOffset + i * channels, offset)
        : cloneAction(sourceItem, vOffset, aOffset, offset + BigInt(i) * span);
      if (!compound.addAction(action)) throw new Error(`addAction(clone ${i}) returned false`);
    }
  }));
  const elapsedMs = now() - started;
  const after = await readSequence(ppro, copy);
  const landed = sameFile(after) - sameFile(before);
  add("speed", `How long do ${SPEED_CLONES} clones take in one step?`,
    speedRead.ok ? `${landed} of ${SPEED_CLONES} landed in ${(elapsedMs / 1000).toFixed(1)} s` : "failed",
    { layout: newTrack ? "one new track each" : "one after another on one track",
      videoTracksNow: after.videoTracks, audioTracksNow: after.audioTracks, error: speedRead.ok ? null : speedRead.error });

  const verdict = landedA.length === channels ? (newTrack ? "clone-works" : "clone-works-no-new-track")
    : fromFile ? "place-from-file"
      : placed.v.length && placed.a.length ? "place-audio-mismatch"
        : separateAudio ? "clone-separately"
          : landedA.length === 0 ? "clone-drops-audio" : "clone-audio-mismatch";
  return { probe: "sync-moves", complete: true, findings, verdict, testName, subframe,
    target: landedV[0].track + 1, placeTrack: placed.v.length ? placed.v[0].track + 1 : null };
}

function formatSyncMovesReport(report) {
  const linkClip = report.placeTrack
    ? `the clip on V${report.placeTrack} (placed from its file, the second one after the old end of the timeline)`
    : `the single clip right after the old end of the timeline, on V${report.target}`;
  const checks = report.complete ? [
    "Now check two things yourself in the test copy (it is open):",
    `  1. LINK: click ${linkClip}. Does its audio highlight with it? yes = linked.`,
    `  2. UNDO: press Ctrl+Z once. Do all ${SPEED_CLONES} test clones disappear together?`,
    "Then send back this report plus your two answers. Delete the test copy from the Project panel afterwards.",
  ].join("\n") : "Stopped early. Send back this report.";
  const lead = {
    "clone-works": "VERDICT: the clone lands on a new track with all its audio.",
    "clone-works-no-new-track": "VERDICT: the clone brings its audio, but did not create a new track.",
    "place-from-file": "VERDICT: cloning does not bring the audio correctly, but placing from the file lands video and all its audio together.",
    "place-audio-mismatch": "VERDICT: placing from the file lands a different number of audio clips than the original.",
    "clone-separately": "VERDICT: only cloning video and audio separately works, and that loses the link.",
    "clone-drops-audio": "VERDICT: the clone copies the video only; Sync would need another route for audio.",
    "clone-audio-mismatch": "VERDICT: the clone's audio count differs from the original. This is the merge/duplicate problem.",
    "clone-failed": "VERDICT: the clone did not land.",
  }[report.verdict];
  return formatFindings("Sync moves test (edits a copy only)", report, [lead, checks].filter(Boolean).join("\n"));
}

module.exports = { probeSyncMoves, formatSyncMovesReport, groupUnits, classifySubframe, TEST_SUFFIX, SPEED_CLONES };
