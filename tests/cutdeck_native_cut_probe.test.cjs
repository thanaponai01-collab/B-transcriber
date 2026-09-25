/* roughCutProbe.js asks real Premiere what the native rough cut (HANDOFF_CUTDECK_NATIVE_ROUGH_CUT
   section 5, P1-P5) can rely on. Provable off-host: given a host that behaves a certain way, the
   probe reports that, and never edits the user's own sequence. What real Premiere does is the
   point of running it. */
const test = require("node:test");
const assert = require("node:assert/strict");

const { probeNativeCut, formatNativeCutReport, classifyMove, TEST_SUFFIX } = require("../uxp/cutdeck/roughCutProbe.js");

const TPF = 10160640000n; // 25 fps
const SEC = 254016000000n;
const PATH = "D:/cam1/C0001.MP4";

function fakeHost({ moveAbsolute = false, marksNeedCommit = false } = {}) {
  let guid = 0;
  const makeSeq = (name) => ({ name, id: `g${guid++}`, video: [[]], audio: [[], []] });
  const addRaw = (seq, kind, track, r) => {
    while (seq[kind].length <= track) seq[kind].push([]);
    const raw = { kind, track, path: PATH, ...r };
    seq[kind][track].push(raw);
    return raw;
  };
  const original = makeSeq("Shoot");
  for (const [kind, track] of [["video", 0], ["audio", 0], ["audio", 1]]) addRaw(original, kind, track, { start: 0n, end: 250n * TPF, in: 0n });
  addRaw(original, "video", 0, { start: 300n * TPF, end: 400n * TPF, in: 0n });
  const sequences = [original];
  const clipPI = { path: PATH, marks: [0n, 3600n * SEC], pending: null, getMediaFilePath: async () => PATH,
    getInPoint: async () => ({ ticks: clipPI.marks[0].toString() }), getOutPoint: async () => ({ ticks: clipPI.marks[1].toString() }),
    createSetInOutPointsAction: (i, o) => ({ type: "marks", marks: [BigInt(i.ticks), BigInt(o.ticks)] }) };

  const wrapItem = (seq, raw) => ({ _raw: raw,
    getStartTime: async () => ({ ticks: raw.start.toString() }), getEndTime: async () => ({ ticks: raw.end.toString() }),
    getInPoint: async () => ({ ticks: raw.in.toString() }), getTrackIndex: async () => raw.track,
    getProjectItem: async () => clipPI,
    createMoveAction: (t) => ({ type: "move", raw, by: BigInt(t.ticks) }),
    createSetEndAction: (t) => ({ type: "setEnd", raw, t: BigInt(t.ticks) }),
    createSetInPointAction: (t) => ({ type: "setIn", raw, t: BigInt(t.ticks) }),
    createSetOutPointAction: (t) => ({ type: "setOut", raw, t: BigInt(t.ticks) }) });
  const wrapSeq = (seq) => ({ get name() { return seq.name; }, guid: { toString: () => seq.id }, _seq: seq,
    getVideoTrackCount: async () => seq.video.length, getAudioTrackCount: async () => seq.audio.length,
    getVideoTrack: async (i) => ({ getTrackItems: () => seq.video[i].map((r) => wrapItem(seq, r)) }),
    getAudioTrack: async (i) => ({ getTrackItems: () => seq.audio[i].map((r) => wrapItem(seq, r)) }),
    getTimebase: async () => TPF.toString(), getFrameSize: async () => ({ width: 1920, height: 1080 }),
    getSelection: async () => ({ getTrackItems: async () => [] }),
    getEndTime: async () => ({ ticks: [...seq.video.flat(), ...seq.audio.flat()].reduce((a, r) => (r.end > a ? r.end : a), 0n).toString() }),
    getProjectItem: async () => ({ createSetNameAction: (n) => ({ type: "rename", seq, name: n }) }),
    createCloneAction: () => ({ type: "cloneSeq", seq }) });
  const remove = (raw, seq) => { for (const t of [...seq.video, ...seq.audio]) { const i = t.indexOf(raw); if (i >= 0) t.splice(i, 1); } };
  const seqOf = (raw) => sequences.find((s) => [...s.video.flat(), ...s.audio.flat()].includes(raw));

  const apply = (a) => {
    if (a.type === "cloneSeq") {
      const copy = makeSeq(`${a.seq.name} Copy`);
      copy.video = a.seq.video.map((t) => t.map((r) => ({ ...r })));
      copy.audio = a.seq.audio.map((t) => t.map((r) => ({ ...r })));
      sequences.push(copy);
    } else if (a.type === "rename") a.seq.name = a.name;
    else if (a.type === "marks") { if (marksNeedCommit) clipPI.pending = a.marks; else clipPI.marks = a.marks; }
    else if (a.type === "overwrite") {
      const [i, o] = clipPI.marks;
      addRaw(a.seq, "video", a.v, { start: a.time, end: a.time + (o - i), in: i });
      for (const k of [0, 1]) addRaw(a.seq, "audio", a.a + k, { start: a.time, end: a.time + (o - i), in: i });
    } else if (a.type === "move") {
      const len = a.raw.end - a.raw.start;
      a.raw.start = moveAbsolute ? a.by : a.raw.start + a.by;
      a.raw.end = a.raw.start + len;
    } else if (a.type === "remove") a.items.filter((r) => a.mt === 0 || (a.mt === 2) === (r.kind === "video")).forEach((r) => remove(r, a.seq));
    else if (a.type === "setEnd") a.raw.end = a.t;
    else if (a.type === "setOut") a.raw.end = a.raw.start + (a.t - a.raw.in);
    else if (a.type === "setIn") { a.raw.start += a.t - a.raw.in; a.raw.in = a.t; } // head trim, as run 1 showed
    else if (a.type === "clone") {
      // Like real Premiere (Sync probe, 2026-09-24): a clone copies only the item it was given.
      addRaw(seqOf(a.raw), a.raw.kind, a.raw.track, { start: a.raw.start + a.by, end: a.raw.end + a.by, in: a.raw.in });
    }
  };
  let transactions = 0;
  const project = {
    getActiveSequence: async () => wrapSeq(sequences[0]), getSequences: async () => sequences.map(wrapSeq),
    openSequence: async () => true, setActiveSequence: async () => true, lockedAccess: (cb) => cb(),
    executeTransaction: (fn) => {
      const actions = [];
      fn({ addAction: (x) => { actions.push(x); return true; } });
      actions.forEach(apply);
      if (clipPI.pending) { clipPI.marks = clipPI.pending; clipPI.pending = null; } // lands at commit
      transactions++;
      return true;
    },
    createSequenceFromMedia: async (name) => {
      const s = makeSeq(name);
      addRaw(s, "video", 0, { start: 0n, end: 3600n * SEC, in: 0n });
      sequences.push(s);
      return wrapSeq(s);
    },
  };
  const ppro = {
    Project: { getActiveProject: async () => project },
    ClipProjectItem: { cast: (pi) => pi },
    Constants: { TrackItemType: { CLIP: 1 }, MediaType: { ANY: 0, DATA: 1, VIDEO: 2, AUDIO: 3 } },
    TickTime: { createWithTicks: (s) => ({ ticks: s }) },
    TrackItemSelection: { createEmptySelection: (cb) => { const items = []; cb({ items, addItem: (it) => items.push(it._raw) }); return true; } },
    SequenceEditor: { getEditor: (s) => ({
      createOverwriteItemAction: (pi, t, v, a) => ({ type: "overwrite", seq: s._seq, time: BigInt(t.ticks), v, a }),
      createRemoveItemsAction: (sel, ripple, mt) => ({ type: "remove", seq: s._seq, items: sel.items, mt }),
      createCloneTrackItemAction: (item, t) => ({ type: "clone", raw: item._raw, by: BigInt(t.ticks) }),
    }) },
  };
  const snapshot = JSON.stringify(original, (k, v) => (typeof v === "bigint" ? v.toString() : v));
  return { ppro, sequences, original, snapshot, clipPI };
}

const stringify = (o) => JSON.stringify(o, (k, v) => (typeof v === "bigint" ? v.toString() : v));
const answer = (r, id) => r.findings.find((f) => f.id === id).answer;
const evidence = (r, id) => r.findings.find((f) => f.id === id).evidence;

test("a host that behaves as Route A hopes: every probe passes, your sequence untouched, marks restored", async () => {
  const h = fakeHost();
  const r = await probeNativeCut(h.ppro);
  assert.equal(r.complete, true, stringify(r.findings));
  assert.deepEqual(r.results, { p2: "one transaction", p5move: "relative", p5remove: "gap", p3: "pass", p4: "skipped", p1: "pre-placed" });
  assert.match(answer(r, "p3-clone"), /^3 of 3 landed/);
  assert.match(answer(r, "p3-head"), /^PASS/);
  assert.match(answer(r, "p3-tail"), /^PASS/);
  assert.equal(evidence(r, "p3").otherClipsUnchanged, true);
  assert.equal(evidence(r, "p2").clipMarksRestored, "yes");
  assert.equal(evidence(r, "p5-move").negativeMoveBack, "yes — back where it was");
  assert.equal(stringify(h.original), h.snapshot, "the user's own sequence was edited");
  assert.deepEqual(h.clipPI.marks, [0n, 3600n * SEC]);
  assert.equal(h.sequences[1].name, `Shoot${TEST_SUFFIX}`);
  assert.match(formatNativeCutReport(r), /LINK: click the second piece on V1/);
});

test("marks that only apply once committed: P2 reports the two-transaction route", async () => {
  const r = await probeNativeCut(fakeHost({ marksNeedCommit: true }).ppro);
  assert.equal(r.results.p2, "two transactions (one step did not work)");
  assert.ok(r.findings.find((f) => f.id === "p2-one"));
});

test("an absolute move is reported as absolute, not guessed as relative", async () => {
  const r = await probeNativeCut(fakeHost({ moveAbsolute: true }).ppro);
  assert.equal(r.results.p5move, "absolute");
  assert.match(answer(r, "p5-move"), /ABSOLUTE/);
});

test("refuses to run on its own test copy, and stops cleanly without a project", async () => {
  const h = fakeHost();
  h.original.name = `Shoot${TEST_SUFFIX}`;
  assert.equal((await probeNativeCut(h.ppro)).complete, false);
  const none = await probeNativeCut({ Project: { getActiveProject: async () => null } });
  assert.equal(none.complete, false);
  assert.equal(none.findings[0].id, "project");
});

test("classifyMove", () => {
  assert.equal(classifyMove(10n, 15n, 5n), "relative");
  assert.equal(classifyMove(10n, 5n, 5n), "absolute");
  assert.equal(classifyMove(10n, 10n, 5n), "ignored");
  assert.equal(classifyMove(10n, 99n, 5n), "other");
});
