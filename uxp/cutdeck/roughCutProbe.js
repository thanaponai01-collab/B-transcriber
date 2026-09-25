/* Native rough cut probes P1-P5 ("Test Native Cut"), docs/HANDOFF_CUTDECK_NATIVE_ROUGH_CUT.md
   section 5. Answers from the real host what Route A/B need before they are built:

     P2  project-item In/Out + overwrite in ONE transaction: does the overwrite place only the
         marked span? (else retried as two transactions)
     P5  createMoveAction: relative or absolute, which sign; does linked audio follow; do other
         tracks stay put? createRemoveItemsAction(ripple=false, VIDEO): gap left, audio kept?
     P3  split substitute (no razor in the API): trim with SetEnd, clone with an offset, slip the
         clone with SetIn/SetOutPoint. Contiguous, media continuous? Audio done the same way.
     P4  do both pieces keep the clip's effects and keyframes (at the same media time)?
     P1  createSequenceFromMedia: settings, and is the clip already laid on it?

   NOT read-only, but it never edits your sequence: it copies the active sequence
   (Sequence.createCloneAction) and edits only "... — CutDeck cut test". Two things land outside
   the copy and are reported: P2 sets the clip's In/Out in the Project panel and restores it,
   and P1 creates one new sequence. Every call is declared in @adobe/premierepro 26.2.1's
   premierepro.d.ts (line numbers in the handoff). Like capabilityProbe.js, nothing here throws
   at the caller: a failed call is a finding. */

const { attempt, finding, formatFindings } = require("./capabilityProbe.js");
const { runTransaction } = require("./host/project.js");
const { TICKS_PER_SECOND, toTicks } = require("./host/ticks.js");
const { readSequence, groupUnits, baseName } = require("./timeline/nativeSync.js");
const { captureEffectFromTrackItem } = require("./timeline/effects.js");

const TEST_SUFFIX = " — CutDeck cut test";
const MIN_CLIP = 4n * TICKS_PER_SECOND;

const key = (c) => `${c.kind}|${c.track}|${c.start}|${c.end}|${c.inPoint}`;
const at = (clips, track, start) => clips.find((c) => c.track === track && c.start === start);

/* Every clip the probe did not mean to touch, as keys, so "nothing else moved" is checkable. */
function untouched(seq, exclude) {
  return [...seq.video, ...seq.audio].filter((c) => !exclude(c)).map(key).sort();
}

/* What a move of `asked` ticks did to a clip that started at `from`. */
function classifyMove(from, to, asked) {
  if (to === from + asked) return "relative";
  if (to === asked) return "absolute";
  if (to === from) return "ignored";
  return "other";
}

/* Effects as comparable data: component names and each keyframe at its MEDIA time (in + offset),
   which must be identical on both pieces of a split clip. */
function effectSignature(captured, inPoint) {
  return captured.components.map((c) => ({
    matchName: c.matchName,
    params: c.params.map((p) => ({
      name: p.displayName,
      value: p.keyframes ? null : JSON.stringify(p.value),
      keyframes: (p.keyframes || []).map((k) => `${BigInt(k.offsetTicks) + inPoint}=${JSON.stringify(k.value)}`),
    })),
  }));
}

async function probeNativeCut(ppro) {
  const findings = [];
  const add = (...args) => { findings.push(finding(...args)); return findings[findings.length - 1]; };
  const results = {};
  const stop = () => ({ probe: "native-cut", complete: false, findings, results });
  const tick = (n) => ppro.TickTime.createWithTicks(n.toString());
  const MT = ppro && ppro.Constants && ppro.Constants.MediaType;

  if (!ppro || !ppro.Project) {
    add("host", "Is the Premiere API reachable?", "no");
    return stop();
  }
  const projectRead = await attempt("getActiveProject", () => ppro.Project.getActiveProject());
  if (!projectRead.ok || !projectRead.value) { add("project", "Is a project open?", "no", projectRead.ok ? null : projectRead); return stop(); }
  const project = projectRead.value;
  const seqRead = await attempt("getActiveSequence", () => project.getActiveSequence());
  if (!seqRead.ok || !seqRead.value) { add("sequence", "Is a sequence open?", "no", seqRead.ok ? null : seqRead); return stop(); }
  const source = seqRead.value;
  if (String(source.name).endsWith(TEST_SUFFIX)) {
    add("sequence", "Is this your own sequence?", "no — this is a test copy. Open your original sequence and run again.");
    return stop();
  }

  // Pick the camera clip: the selected one if exactly one video clip is selected, else the first
  // camera clip (video + its audio) at least 4 s long.
  const origRead = await attempt("read original", () => readSequence(ppro, source));
  if (!origRead.ok) { add("read", "Can the sequence's clips be read?", "no", origRead); return stop(); }
  const orig = origRead.value;
  const units = groupUnits(orig.video, orig.audio).filter((u) => u.audio.length && u.video.end - u.video.start >= MIN_CLIP);
  let picked = null;
  const selRead = await attempt("getSelection", async () => {
    const sel = await source.getSelection();
    return sel ? await sel.getTrackItems() : [];
  });
  if (selRead.ok && selRead.value && selRead.value.length) {
    for (const u of units) {
      for (const s of selRead.value) {
        const start = await attempt("selected start", () => s.getStartTime());
        const track = await attempt("selected track", () => s.getTrackIndex());
        if (start.ok && track.ok && toTicks(start.value) === u.video.start && track.value === u.video.track) picked = u;
      }
    }
  }
  const unit = picked || units[0];
  if (!unit) {
    add("unit", "Is there a camera clip (video + its audio, at least 4 s) to test on?", "no — put one on this timeline");
    return stop();
  }
  const channels = unit.audio.length;
  add("unit", "Which clip will be tested?",
    `${baseName(unit.video.path)} on V${unit.video.track + 1} (${picked ? "your selection" : "first camera clip"}) — 1 video + ${channels} audio clip(s)`);

  // Copy the sequence; everything below edits the copy only.
  const beforeIds = new Set((await project.getSequences()).map((s) => s.guid.toString()));
  const copyRead = await attempt("createCloneAction", () => runTransaction(project, "CutDeck cut test: copy sequence", (compound) => {
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
    runTransaction(project, "CutDeck cut test: name copy", (compound) => {
      if (!compound.addAction(item.createSetNameAction(testName))) throw new Error("addAction(rename) returned false");
    });
  });
  await attempt("open copy", async () => { await project.openSequence(copy); await project.setActiveSequence(copy); });
  add("copy", "Can the sequence be copied, so your original stays untouched?",
    `yes — "${renamed.ok ? testName : copy.name}"`, renamed.ok ? null : { rename: renamed.error });

  const tpf = toTicks(await copy.getTimebase());
  const snap = (t) => (t / tpf) * tpf;
  const second = snap(TICKS_PER_SECOND);
  const read = () => readSequence(ppro, copy);
  const tx = (label, build) => attempt(label, () => runTransaction(project, `CutDeck cut test: ${label}`, (compound) => {
    for (const action of build()) {
      if (!compound.addAction(action)) throw new Error(`addAction(${label}) returned false`);
    }
  }));
  const c0 = await read();
  const cv0 = at(c0.video, unit.video.track, unit.video.start);
  if (!cv0) { add("copy-read", "Does the copy hold the same clip?", "no — stopped"); return stop(); }
  // Overwrite takes the plain ProjectItem (as native Sync passes it — run 1 got "Invalid
  // parameter." with the cast one); marks live on the ClipProjectItem.
  const rawPI = await cv0.item.getProjectItem();
  const clipPI = ppro.ClipProjectItem.cast(rawPI);

  // ── P2: project-item In/Out + overwrite, one transaction ────────────────────────────────
  const endTicks = toTicks(await copy.getEndTime());
  const T = snap(endTicks + tpf - 1n) + second;
  const markIn = await attempt("clip getInPoint", () => clipPI.getInPoint(MT.VIDEO));
  const markOut = await attempt("clip getOutPoint", () => clipPI.getOutPoint(MT.VIDEO));
  const savedMarks = markIn.ok && markOut.ok ? [toTicks(markIn.value), toTicks(markOut.value)] : null;
  const wantIn = 2n * second, wantLen = 2n * second;
  const place = async (label, at0, oneTx) => {
    const editor = ppro.SequenceEditor.getEditor(copy);
    const before = await read();
    const setMarks = () => [clipPI.createSetInOutPointsAction(tick(wantIn), tick(wantIn + wantLen))];
    const overwrite = () => [editor.createOverwriteItemAction(rawPI, tick(at0), before.videoTracks, before.audioTracks)];
    const r = oneTx ? await tx(label, () => [...setMarks(), ...overwrite()])
      : ((await tx(`${label} (marks)`, setMarks)).ok ? await tx(`${label} (overwrite)`, overwrite) : { ok: false, error: "setting marks failed" });
    const after = await read();
    const v = after.video.filter((c) => c.start === at0);
    const a = after.audio.filter((c) => c.start === at0);
    const exact = v.length === 1 && v[0].end - v[0].start === wantLen && v[0].inPoint === wantIn;
    return { r, v, a, exact, before };
  };
  let p2 = await place("P2 marks+overwrite in one step", T, true);
  let p2How = "one transaction";
  if (!p2.exact) {
    const oneStep = p2;
    p2 = await place("P2 marks, then overwrite", T + 6n * second, false);
    p2How = p2.exact ? "two transactions (one step did not work)" : "neither";
    add("p2-one", "P2 (one step) — what landed?", describePlaced(oneStep, wantIn, wantLen, channels), { error: oneStep.r.ok ? null : oneStep.r.error });
  }
  const restore = savedMarks ? await tx("P2 restore clip In/Out", () => [clipPI.createSetInOutPointsAction(tick(savedMarks[0]), tick(savedMarks[1]))]) : { ok: false, error: "marks were unreadable" };
  const nowIn = await attempt("clip getInPoint after", () => clipPI.getInPoint(MT.VIDEO));
  const nowOut = await attempt("clip getOutPoint after", () => clipPI.getOutPoint(MT.VIDEO));
  const restored = savedMarks && nowIn.ok && nowOut.ok && toTicks(nowIn.value) === savedMarks[0] && toTicks(nowOut.value) === savedMarks[1];
  results.p2 = p2.exact ? p2How : "fail";
  add("p2", "P2 — set the clip's In/Out (2 s–4 s) and place it: is exactly that 2 s span placed?",
    `${p2.exact ? "PASS" : "FAIL"} via ${p2How}: ${describePlaced(p2, wantIn, wantLen, channels)}`,
    { error: p2.r.ok ? null : p2.r.error,
      clipMarksRestored: restored ? "yes" : `NO — reset this clip's In/Out in the Project panel (was ${savedMarks ? savedMarks.map(String).join("-") : "unreadable"})`,
      restoreError: restore.ok ? null : restore.error,
      otherClipsUnchanged: untouched(await read(), (c) => c.start >= T).join() === untouched(c0, () => false).join() });

  // ── P5: move and remove semantics, on the isolated clip P2 placed ───────────────────────
  if (p2.v.length === 1) {
    const pv = p2.v[0];
    const from = pv.start;
    const isPlaced = (c) => c.start >= T;
    const others0 = untouched(await read(), isPlaced);
    const mv = await tx("P5 move +1 s", () => [pv.item.createMoveAction(tick(second))]);
    const m1 = await read();
    const vNow = m1.video.find((c) => c.track === pv.track && c.end - c.start === pv.end - pv.start);
    const moveKind = mv.ok && vNow ? classifyMove(from, vNow.start, second) : "failed";
    const audioFollowed = p2.a.length ? m1.audio.filter((c) => c.start === (vNow ? vNow.start : -1n)).length : null;
    const othersStill = untouched(m1, (c) => c.start >= T).join() === others0.join();
    let back = null;
    if (moveKind === "relative") {
      const mvBack = await tx("P5 move -1 s", () => [vNow.item.createMoveAction(tick(-second))]);
      const m2 = await read();
      back = mvBack.ok && at(m2.video, pv.track, from) ? "yes — back where it was" : mvBack.ok ? "no — it went elsewhere" : `failed: ${mvBack.error}`;
    }
    results.p5move = moveKind;
    add("p5-move", "P5 — createMoveAction(+1 s): relative shift or absolute position? Does its audio follow? Do other clips stay?",
      { relative: "RELATIVE (shift by)", absolute: "ABSOLUTE (move to)", ignored: "it did not move", other: "moved by an unexpected amount", failed: "the move failed" }[moveKind],
      { startBefore: from.toString(), startAfter: vNow ? vNow.start.toString() : null,
        audioMovedWithIt: audioFollowed === null ? null : `${audioFollowed} of ${p2.a.length}`,
        otherClipsUnchanged: othersStill, negativeMoveBack: back, error: mv.ok ? null : mv.error });

    const r0 = await read();
    const rv = r0.video.find((c) => c.track === pv.track && c.start >= T);
    const audioBefore = r0.audio.filter(isPlaced).length;
    let removed = { ok: false, error: "clip not found" };
    if (rv) {
      removed = await attempt("P5 remove video", () => runTransaction(project, "CutDeck cut test: P5 remove video", (compound) => {
        let added = false;
        ppro.TrackItemSelection.createEmptySelection((selection) => {
          selection.addItem(rv.item, true);
          added = compound.addAction(ppro.SequenceEditor.getEditor(copy).createRemoveItemsAction(selection, false, MT.VIDEO));
        });
        if (!added) throw new Error("addAction(remove) returned false");
      }));
    }
    const r1 = await read();
    const videoGone = rv && !r1.video.some((c) => c.track === rv.track && c.start === rv.start);
    results.p5remove = removed.ok && videoGone && untouched(r1, isPlaced).join() === untouched(r0, isPlaced).join() ? "gap" : "fail";
    add("p5-remove", "P5 — createRemoveItemsAction(ripple=false, VIDEO) on that clip: removed, gap left, nothing else shifted?",
      !removed.ok ? `failed: ${removed.error}` : !videoGone ? "no — the video is still there"
        : results.p5remove === "gap" ? "PASS — removed, nothing else moved" : "removed, but OTHER clips changed",
      { audioClipsBefore: audioBefore, audioClipsAfter: r1.audio.filter(isPlaced).length });
  }

  // ── P3 + P4: split substitute on the camera clip, and whether effects survive it ────────
  // Items read before a transaction can go stale (#18): re-read the clip before each step.
  const fresh = at((await read()).video, cv0.track, cv0.start);
  if (!fresh) { add("p3", "P3 — is the camera clip still on the copy?", "no — stopped"); return stop(); }
  const S = fresh.start, E = fresh.end, M = fresh.inPoint;
  const b = S + snap((E - S) / 2n);
  const off = b - S;
  let effects0 = null;
  const eff = await attempt("capture effects", () => captureEffectFromTrackItem(ppro, fresh.item));
  if (eff.ok) effects0 = effectSignature(eff.value, M);

  // Run 1 (2026-09-24): createSetEndAction threw "script object is no longer valid" on video
  // and audio; a clone landing on the clip's own track OVERWRITES what is there (it truncated
  // the clip — and would eat its neighbours); createSetInPointAction trims the HEAD (start and
  // media In move together, end stays). So route 2: clone into free space past the sequence end,
  // head-trim the clone there, tail-trim the original with SetOutPoint, move the clone back.
  const audioOf = (seq, start) => unit.audio.map((a) => at(seq.audio, a.track, start)).filter(Boolean);
  const X = snap(toTicks(await copy.getEndTime()) - S + tpf - 1n) + 2n * second;
  const t0 = await read();
  const src = [at(t0.video, cv0.track, S), ...audioOf(t0, S)].filter(Boolean);
  const cloneAll = await tx("P3 clone into free space", () => src.map((c) => ppro.SequenceEditor.getEditor(copy)
    .createCloneTrackItemAction(c.item, tick(X), 0, 0, false, false)));
  const t1 = await read();
  const far = [at(t1.video, cv0.track, S + X), ...audioOf(t1, S + X)].filter(Boolean);
  add("p3-clone", "P3a — clone the clip (video and each audio) into free space past the end: did all land?",
    !cloneAll.ok ? `failed: ${cloneAll.error}` : `${far.length} of ${1 + channels} landed`,
    { originalStillIntact: at(t1.video, cv0.track, S) ? at(t1.video, cv0.track, S).end === E : false });

  const headTrim = await tx("P3 head-trim clone", () => far.map((c) => c.item.createSetInPointAction(tick(M + off))));
  const t2 = await read();
  const trimmed = [at(t2.video, cv0.track, b + X), ...audioOf(t2, b + X)].filter(Boolean);
  const headOk = trimmed.length === 1 + channels && trimmed.every((c) => c.end === E + X && c.inPoint === M + off);
  add("p3-head", "P3b — createSetInPointAction on the clone: head trimmed (start and In move, end stays)?",
    !headTrim.ok ? `failed: ${headTrim.error}` : headOk ? "PASS — head trimmed" : `no — ${trimmed.length} of ${1 + channels} at the expected start`,
    { video: trimmed[0] ? `${trimmed[0].start}-${trimmed[0].end} in ${trimmed[0].inPoint}` : null,
      wanted: `${b + X}-${E + X} in ${M + off}` });

  const orig2 = [at(t2.video, cv0.track, S), ...audioOf(t2, S)].filter(Boolean);
  const tailTrim = await tx("P3 tail-trim original", () => orig2.map((c) => c.item.createSetOutPointAction(tick(M + off))));
  const t3 = await read();
  const origNow = [at(t3.video, cv0.track, S), ...audioOf(t3, S)].filter(Boolean);
  const tailOk = origNow.length === 1 + channels && origNow.every((c) => c.end === b && c.inPoint === M);
  add("p3-tail", "P3c — createSetOutPointAction on the original: tail trimmed to the split point?",
    !tailTrim.ok ? `failed: ${tailTrim.error}` : tailOk ? "PASS — tail trimmed, media In unchanged" : "no — see evidence",
    { video: origNow[0] ? `${origNow[0].start}-${origNow[0].end} in ${origNow[0].inPoint}` : null, wantedEnd: b.toString() });

  const t3b = await read();
  const toMove = [at(t3b.video, cv0.track, b + X), ...audioOf(t3b, b + X)].filter(Boolean);
  const moveBack = await tx("P3 move clone back", () => toMove.map((c) => c.item.createMoveAction(tick(-X))));
  const t4 = await read();
  const pieces = [at(t4.video, cv0.track, S), at(t4.video, cv0.track, b)];
  const aPieces = unit.audio.map((a) => [at(t4.audio, a.track, S), at(t4.audio, a.track, b)]);
  const good = (p) => p[0] && p[1] && p[0].end === b && p[0].inPoint === M && p[1].end === E && p[1].inPoint === M + off;
  const splitOk = good(pieces) && aPieces.every(good);
  const landed = pieces[1] || toMove[0];
  results.p3 = splitOk ? "pass" : "fail";
  add("p3", "P3 — split: two contiguous pieces at the split point, media continuous, nothing else touched?",
    !moveBack.ok ? `move back failed: ${moveBack.error}` : splitOk ? "PASS — split works (clone past end, head-trim, tail-trim, move back)" : "FAIL — see evidence",
    { secondPiece: landed ? `${landed.start}-${landed.end} in ${landed.inPoint}` : "not found",
      wanted: `${b}-${E} in ${M + off}`, audioPiecesOk: `${aPieces.filter(good).length} of ${channels}`,
      otherClipsUnchanged: untouched(t4, (c) => c.start >= T || (c.start >= S && c.start < E)).join() ===
        untouched(t0, (c) => c.start >= T || (c.start >= S && c.start < E)).join(),
      undoSteps: "4 (clone, head-trim, tail-trim, move)" });

  if (pieces[0] || pieces[1]) {
    // P4 — effects on both pieces equal the original's, keyframes at the same media time.
    if (!effects0) {
      results.p4 = "skipped";
      add("p4", "P4 — do both pieces keep the effects and keyframes?", "SKIPPED — this clip has no effect beyond Motion/Opacity. Add a keyframed Transform + Lumetri to it, select it, run again.", { error: eff.error });
    } else {
      const sig = async (piece) => {
        const c = piece ? await attempt("capture piece", () => captureEffectFromTrackItem(ppro, piece.item)) : { ok: false };
        return c.ok ? JSON.stringify(effectSignature(c.value, piece.inPoint)) : null;
      };
      const want = JSON.stringify(effects0);
      const s1 = await sig(pieces[0]), s2 = await sig(pieces[1]);
      results.p4 = s1 === want && s2 === want ? "pass" : "fail";
      add("p4", "P4 — do both pieces keep the effects, with keyframes at the same media time?",
        results.p4 === "pass" ? `PASS — ${effects0.length} effect(s), identical on both pieces` : "FAIL — see evidence",
        { piece1Matches: s1 === want, piece2Matches: s2 === want, animatedParams: eff.value.animatedCount });
    }
  }

  // ── P1: createSequenceFromMedia (adds one sequence to the project) ──────────────────────
  const p1Name = `${baseName(unit.video.path)} — CutDeck cut test (from media)`;
  const p1 = await attempt("createSequenceFromMedia", () => project.createSequenceFromMedia(p1Name, [clipPI]));
  if (p1.ok && p1.value) {
    const s = p1.value;
    const fromMedia = await readSequence(ppro, s);
    const frame = await attempt("getFrameSize", () => s.getFrameSize());
    const srcFrame = await attempt("getFrameSize", () => copy.getFrameSize());
    const tpfNew = toTicks(await s.getTimebase());
    results.p1 = fromMedia.video.length ? "pre-placed" : "empty";
    add("p1", "P1 — createSequenceFromMedia: settings, and is the clip already on it?",
      `created "${p1Name}" — ${fromMedia.video.length} video + ${fromMedia.audio.length} audio clip(s) already on it`,
      { ticksPerFrame: `${tpfNew} (your sequence: ${tpf})`,
        frameSize: frame.ok && frame.value ? `${frame.value.width}x${frame.value.height}` : frame.error,
        yourSequenceFrameSize: srcFrame.ok && srcFrame.value ? `${srcFrame.value.width}x${srcFrame.value.height}` : srcFrame.error,
        firstClip: fromMedia.video[0] ? `${fromMedia.video[0].start}-${fromMedia.video[0].end} in ${fromMedia.video[0].inPoint}` : null });
  } else {
    results.p1 = "fail";
    add("p1", "P1 — createSequenceFromMedia: does it work?", "no", p1.ok ? { detail: "returned nothing" } : p1);
  }
  await attempt("reopen copy", () => project.setActiveSequence(copy));

  return { probe: "native-cut", complete: true, findings, results, testName,
    splitAt: b, splitTrack: cv0.track + 1, placedAt: T };
}

function describePlaced(p, wantIn, wantLen, channels) {
  if (!p.v.length && !p.a.length) return "nothing landed";
  const v = p.v[0];
  return `${p.v.length} video (${v ? `length ${v.end - v.start}, media In ${v.inPoint}` : "none"}; wanted length ${wantLen}, In ${wantIn}), ${p.a.length} audio (original has ${channels})`;
}

function formatNativeCutReport(report) {
  const tc = (t) => `${(Number(t) / Number(TICKS_PER_SECOND)).toFixed(2)} s`;
  const checks = report.complete ? [
    "Now check in the test copy (it is open):",
    `  1. LINK: click the second piece on V${report.splitTrack} (starts at ${tc(report.splitAt)}). Does its audio highlight with it? yes = linked.`,
    `  2. LOOK: at ${tc(report.splitAt)} the clip should play straight through the split with no jump in picture or sound.`,
    "Then send back this report plus your two answers. Delete the test copy and the \"(from media)\" sequence from the Project panel afterwards.",
  ].join("\n") : "Stopped early. Send back this report.";
  return formatFindings("Native cut test (edits a copy only)", report, checks);
}

module.exports = { probeNativeCut, formatNativeCutReport, classifyMove, effectSignature, TEST_SUFFIX };
