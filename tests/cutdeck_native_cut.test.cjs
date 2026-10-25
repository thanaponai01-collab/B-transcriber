/* Route A end to end against a fake Premiere that behaves the way the live probes proved
   (TODO_LEDGER 2026-09-24): moves are relative and never drag linked audio, SetInPoint trims
   the head, SetOutPoint the tail, a clone copies one item and OVERWRITES what it lands on,
   removal is per media type. The fake is stricter than Premiere where Premiere is unknown: a
   move onto an occupied spot throws, so ordering bugs can't hide. The expected result is the
   XML route's own recut() of the captured synced stack (tests/fixtures golden). */
const test = require("node:test");
const assert = require("node:assert/strict");

const { applyNativeCut, findUncuttable } = require("../uxp/cutdeck/timeline/nativeCut.js");

const { fakeHost, golden, TPF } = require("./fakes/native_cut_host.cjs");

function audioSnapshot(rows) {
  const audioTracks = [];
  for (const [kind, track, start, end, inPoint] of rows) {
    if (kind !== "audio") continue;
    while (audioTracks.length <= track) audioTracks.push({ enabled: true, clips: [] });
    audioTracks[track].clips.push({ path: "D:/a.mp4", enabled: true,
      start_ticks: String(BigInt(start) * TPF), in_ticks: String(BigInt(inPoint) * TPF),
      out_ticks: String(BigInt(inPoint + end - start) * TPF) });
  }
  return { ticks_per_frame: String(TPF), end_ticks: String(BigInt(Math.max(...rows.map((r) => r[3]))) * TPF),
    audio_tracks: audioTracks };
}

for (const [name, change] of [
  ["timing", (h) => { h.src.tracks.audio[0][0].start += TPF; }],
  ["source in", (h) => { h.src.tracks.audio[0][0].in += TPF; }],
  ["media", (h) => { h.src.tracks.audio[0][0].path = "D:/different.wav"; }],
  ["disabled clip", (h) => { h.src.tracks.audio[0][0].disabled = true; }],
  ["speed", (h) => { h.src.tracks.audio[0][0].speed = 2; }],
  ["muted track", (h) => { h.src.tracks.audio[0].muted = true; }],
  ["duration", (h) => { h.src.tracks.video[0][0].end += TPF; }],
]) {
  test(`source audio snapshot: changed ${name} refuses before cloning or editing`, async () => {
    const h = fakeHost(golden.before, { speedOf: (r) => r.speed || 1 });
    change(h);
    const sourceBefore = h.rowsOf(h.src);
    await assert.rejects(applyNativeCut(h.ppro, h.project, h.source,
      { ...golden, source_sequence: audioSnapshot(golden.before) }, "Stale result"),
      (error) => /changed since analysis/.test(error.message) && error.staleSource === true);
    assert.equal(h.transactions, 0, "stale audio snapshot caused a transaction");
    assert.equal(h.sequences.length, 1, "stale audio snapshot created a copy");
    assert.deepEqual(h.rowsOf(h.src), sourceBefore);
  });
}

test("source audio snapshot: enumeration order changes still apply the exact golden", async () => {
  const h = fakeHost(golden.before);
  for (const track of h.src.tracks.audio) track.reverse();
  const result = await applyNativeCut(h.ppro, h.project, h.source,
    { ...golden, source_sequence: audioSnapshot(golden.before) }, "Fresh result");
  assert.equal(result.cuts, golden.cuts_frames.length);
  const copy = h.sequences.find((s) => s.name === "Fresh result");
  assert.deepEqual(h.rowsOf(copy), golden.after.map((r) => JSON.stringify(r)).sort());
});

test("golden: native apply on the captured synced stack equals the XML route's recut, source untouched", async () => {
  const h = fakeHost(golden.before);
  const before = h.rowsOf(h.src);
  const r = await applyNativeCut(h.ppro, h.project, h.source, golden, "Shoot — CutDeck test");
  assert.equal(r.cuts, golden.cuts_frames.length);
  assert.ok(r.splits > 0);
  assert.ok(r.steps <= 5, `${r.steps} undo steps`);
  assert.deepEqual(h.rowsOf(h.src), before, "the source sequence was edited");
  const copy = h.sequences.find((s) => s.name === "Shoot — CutDeck test");
  assert.deepEqual(h.rowsOf(copy), golden.after.map((x) => JSON.stringify(x)).sort());
  assert.deepEqual(h.binPath(copy), ["CutDeck", "Rough Cuts"]);
  assert.ok(h.events.lastIndexOf("open Shoot — CutDeck test") > h.events.lastIndexOf("tx clone"),
    "the new sequence is shown only after it is cut (no redraw per edit)");
});

test("refuses before any edit: a sped-up clip under a cut", async () => {
  const h = fakeHost(golden.before, { speedOf: (r) => (r.kind === "video" && r.track === 1 ? 2 : 1) });
  await assert.rejects(applyNativeCut(h.ppro, h.project, h.source, golden, "x"), /Cannot cut natively: .*200% speed/);
  assert.equal(h.transactions, 0);
  assert.equal(h.sequences.length, 1, "no copy should be made on a refusal");
});

test("refuses before any edit: a transition a cut lands inside", async () => {
  const h = fakeHost(golden.before, { transitions: [{ kind: "video", track: 0, start: 995n * TPF, end: 1005n * TPF }] });
  await assert.rejects(applyNativeCut(h.ppro, h.project, h.source, golden, "x"), /transition/);
  assert.equal(h.transactions, 0);
});

test("a null entry in a track's transition list is skipped, not a crash", async () => {
  const h = fakeHost(golden.before, { transitions: [{ kind: "video", track: 0, null: true }] });
  const r = await applyNativeCut(h.ppro, h.project, h.source, golden, "Null transition");
  assert.equal(r.cuts, golden.cuts_frames.length);
});

test("findUncuttable names what a cut inside In/Out would refuse, and edits nothing", async () => {
  const h = fakeHost(golden.before, {
    speedOf: (r) => (r.kind === "video" && r.track === 1 ? 2 : 1),
    transitions: [{ kind: "video", track: 0, start: 995n * TPF, end: 1005n * TPF }, { kind: "video", track: 0, start: 5000n * TPF, end: 5010n * TPF }],
  });
  const found = await findUncuttable(h.ppro, h.source, (900n * TPF).toString(), (1100n * TPF).toString());
  assert.ok(found.some((f) => /200% speed/.test(f)), found.join("; "));
  assert.equal(found.filter((f) => /transition/.test(f)).length, 1, "only the transition inside the range");
  assert.equal(h.transactions, 0);
});

test("findUncuttable is empty when nothing in the range is refusable", async () => {
  const h = fakeHost(golden.before);
  assert.deepEqual(await findUncuttable(h.ppro, h.source, (900n * TPF).toString(), (1100n * TPF).toString()), []);
});

test("refuses a cut list from another frame rate", async () => {
  const h = fakeHost(golden.before);
  await assert.rejects(applyNativeCut(h.ppro, h.project, h.source, { ...golden, ticks_per_frame: "8475667200" }, "x"), /ticks\/frame/);
});

test("a split never harms the next clip on the same track (clones park past the end)", async () => {
  const rows = [["video", 0, 0, 100, 0], ["video", 0, 100, 200, 500], ["audio", 0, 0, 100, 0], ["audio", 0, 100, 200, 500]];
  const h = fakeHost(rows);
  const cuts = { cuts_frames: [[40, 50]], ticks_per_frame: golden.ticks_per_frame };
  await applyNativeCut(h.ppro, h.project, h.source, cuts, "cut");
  const copy = h.sequences.find((s) => s.name === "cut");
  assert.deepEqual(h.rowsOf(copy), [
    ["audio", 0, 0, 40, 0], ["audio", 0, 40, 90, 50], ["audio", 0, 90, 190, 500],
    ["video", 0, 0, 40, 0], ["video", 0, 40, 90, 50], ["video", 0, 90, 190, 500],
  ].map((x) => JSON.stringify(x)).sort());
});

test("scale: 432 cuts across a 5-track synced clip — exact result, no long clones parked", async () => {
  const len = 45000;
  const rows = [["video", 0, 0, len, 0], ...[0, 1, 2, 3].map((t) => ["audio", t, 0, len, 0])];
  const cuts_frames = Array.from({ length: 432 }, (_, i) => [100 * i + 50, 100 * i + 60 + (i % 7)]);
  const h = fakeHost(rows);
  const r = await applyNativeCut(h.ppro, h.project, h.source, { cuts_frames, ticks_per_frame: golden.ticks_per_frame }, "big");
  assert.equal(r.cuts, 432);
  assert.ok(r.steps <= 8); // 5 fixed steps + one extra per 3,000-action batch (split, close gaps)
  const { planCutApply } = require("../uxp/cutdeck/timeline/cutPlanApply.js");
  const items = rows.map(([k, t, s, e, i]) => ({ id: `${k}${t}`, mediaType: k, track: t, startTicks: BigInt(s) * TPF, endTicks: BigInt(e) * TPF, inTicks: BigInt(i) * TPF }));
  const plan = planCutApply(items, cuts_frames.map(([a, b]) => [BigInt(a) * TPF, BigInt(b) * TPF]));
  const want = items.flatMap((it, i) => plan.edits[i].pieces.map((p) =>
    JSON.stringify([it.mediaType, it.track, Number(p.startTicks / TPF), Number(p.endTicks / TPF), Number(p.inTicks / TPF)]))).sort();
  assert.deepEqual(h.rowsOf(h.sequences.find((s) => s.name === "big")), want);
  const long = h.clones.filter((n) => n > TPF);
  assert.equal(long.length, 5, "only one full-length clone per track (the razor filler's source)");
  // Review 2026-09-24: this was 75,950 before (7 full reads, flags and paths on each). Middle
  // reads now skip paths, flags are read only under a cut, the copy is not pre-read.
  console.log(`scale test host reads: ${h.hostReads}`);
  assert.deepEqual(Object.keys(r.timings).sort(), ["close gaps", "make razor fillers", "open copy", "read source",
    "read-back", "reads", "remove cut pieces", "split at cut edges", "trim razor fillers"]);
  // 2026-10-01: split and close-gaps run in 3,000-action batches, each from a fresh read (48,445 here).
  assert.ok(h.hostReads < 50000, `host reads ${h.hostReads}`);
});

/* Live 2026-09-24: Premiere returned undefined for one clone of 7,650, and a rerun went through. */
function flakyClones(h, failures) {
  let calls = 0;
  const getEditor = h.ppro.SequenceEditor.getEditor;
  h.ppro.SequenceEditor.getEditor = (s) => {
    const editor = getEditor(s);
    return { ...editor, createCloneTrackItemAction: (...args) => (failures.has(++calls) ? undefined : editor.createCloneTrackItemAction(...args)) };
  };
}

test("a clone Premiere returns empty once is asked for again, and the cut is still exact", async () => {
  const h = fakeHost(golden.before);
  flakyClones(h, new Set([30]));            // a razor clone (the 15 fillers take the first calls)
  await applyNativeCut(h.ppro, h.project, h.source, golden, "retry");
  assert.deepEqual(h.rowsOf(h.sequences.find((s) => s.name === "retry")), golden.after.map((x) => JSON.stringify(x)).sort());
});

test("a clone that stays empty still stops the cut, saying where", async () => {
  const h = fakeHost(golden.before);
  flakyClones(h, new Set([30, 31]));
  await assert.rejects(applyNativeCut(h.ppro, h.project, h.source, golden, "x"), /split at cut edges: action \d+ of \d+ .*returned no action \(undefined\), twice/);
});

test("a cut that fails after the copy exists renames the copy (FAILED) and says so on the error", async () => {
  const h = fakeHost(golden.before);
  flakyClones(h, new Set([30, 31]));
  const error = await applyNativeCut(h.ppro, h.project, h.source, golden, "Result").then(() => null, (e) => e);
  assert.ok(error, "the cut should fail");
  assert.equal(error.copyCreated, true);
  assert.deepEqual(h.sequences.map((s) => s.name).sort(), ["Result (FAILED)", "Shoot"]);
});

test("a refusal before the copy is made leaves no copy and no copyCreated flag", async () => {
  const h = fakeHost(golden.before, { speedOf: () => 2 });
  const error = await applyNativeCut(h.ppro, h.project, h.source, golden, "Result").then(() => null, (e) => e);
  assert.ok(error);
  assert.notEqual(error.copyCreated, true);
  assert.deepEqual(h.sequences.map((s) => s.name), ["Shoot"]);
});

test("stale handle mid-batch in close gaps: commits partial batch, re-reads, and completes exact cut", async () => {
  const h = fakeHost(golden.before, { staleMoveCalls: new Set([4]) });
  const r = await applyNativeCut(h.ppro, h.project, h.source, golden, "partial-close");
  const copy = h.sequences.find((s) => s.name === "partial-close");
  assert.deepEqual(h.rowsOf(copy), golden.after.map((x) => JSON.stringify(x)).sort());
  assert.ok(r.steps >= 6, `expected at least 6 steps with split batch, got ${r.steps}`);
});


test("stale handle mid-batch in split at cut edges: commits partial batch, re-reads, and completes exact cut", async () => {
  // Live 2026-10-10: action 2585 of 3000 in the razor step threw "The script object is no longer valid."
  const h = fakeHost(golden.before, { staleCloneCalls: new Set([15 + 8]) /* 15 filler clones, then mid-razor */ });
  const r = await applyNativeCut(h.ppro, h.project, h.source, golden, "partial-split");
  const copy = h.sequences.find((s) => s.name === "partial-split");
  assert.deepEqual(h.rowsOf(copy), golden.after.map((x) => JSON.stringify(x)).sort());
  assert.ok(r.steps >= 6, `expected at least 6 steps with split batch, got ${r.steps}`);
});

/* Live 2026-10-25: after a committed close-gaps batch, the next read lacked ~370 clips that had
   not moved (one "vanished" from audio track 0). A clip nothing moved onto can't be gone, so the
   read is retried. Here the fake returns null entries on audio reads after the first moves. */
function nullAudioReads(times) {
  let left = times;
  let lastMoves = -1;
  return ({ kind, moveCalls }) => {
    if (kind !== "audio" || moveCalls === 0 || left === 0) return false;
    if (moveCalls !== lastMoves) { lastMoves = moveCalls; left--; } // one bad read per move count
    return true;
  };
}

test("close gaps: a read missing clips is retried and the cut is still exact", async () => {
  const h = fakeHost(golden.before, { staleMoveCalls: new Set([4]), nullClipRead: nullAudioReads(1) });
  await applyNativeCut(h.ppro, h.project, h.source, golden, "missing-once");
  assert.deepEqual(h.rowsOf(h.sequences.find((s) => s.name === "missing-once")),
    golden.after.map((x) => JSON.stringify(x)).sort());
});

test("close gaps: clips missing on every fresh read still stop the cut, saying how many", async () => {
  const h = fakeHost(golden.before, { staleMoveCalls: new Set([4]), nullClipRead: ({ kind, moveCalls }) => kind === "audio" && moveCalls > 0 });
  const error = await applyNativeCut(h.ppro, h.project, h.source, golden, "missing").then(() => null, (e) => e);
  assert.match(error.message, /close gaps: clip at audio track \d+\|\d+ vanished .*\d+ of \d+ missing after 3 fresh reads/);
  assert.equal(error.copyCreated, true);
});

for (const stage of ["split", "move"]) {
  test(`stale first handle in ${stage}: fresh read recovers an exact cut`, async () => {
    // Include a stale first handle after a partial commit, not just the initial batch.
    const failures = stage === "split"
      ? { staleCloneCalls: new Set([16, 17, 20, 21]) }
      : { staleMoveCalls: new Set([1, 2, 5, 6]) };
    const h = fakeHost(golden.before, failures);
    const before = h.rowsOf(h.src);
    await applyNativeCut(h.ppro, h.project, h.source, golden, "recovered");
    assert.deepEqual(h.rowsOf(h.sequences.find((s) => s.name === "recovered")),
      golden.after.map((x) => JSON.stringify(x)).sort());
    assert.deepEqual(h.rowsOf(h.src), before);
    assert.ok(!h.events.includes("tx empty"), "a stale first action must not commit an empty transaction");
  });

  test(`persistently stale first handle in ${stage}: bounded failure leaves source untouched`, async () => {
    const calls = new Set(Array.from({ length: 30 }, (_, i) => i + (stage === "split" ? 16 : 1)));
    const h = fakeHost(golden.before, stage === "split" ? { staleCloneCalls: calls } : { staleMoveCalls: calls });
    const before = h.rowsOf(h.src);
    const error = await applyNativeCut(h.ppro, h.project, h.source, golden, "stalled").then(() => null, (e) => e);
    assert.match(error.message, /stalled.*3 fresh reads/);
    assert.equal(error.copyCreated, true);
    assert.equal(stage === "split" ? h.cloneCalls - 15 : h.moveCalls, 4,
      "one initial attempt plus three fresh-read attempts, then stop");
    assert.deepEqual(h.rowsOf(h.src), before);
    assert.ok(h.sequences.some((s) => s.name === "stalled (FAILED)"));
    assert.ok(!h.events.includes("tx empty"));
  });
}
