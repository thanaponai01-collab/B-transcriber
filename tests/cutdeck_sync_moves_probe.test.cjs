/* syncProbe.js asks real Premiere whether native Sync can move clips: clone to a new track with
   its audio, place audio between frames, and do 100 clones in one step. Provable off-host: given
   a host that behaves a certain way, the probe reports that, verdicts only on what it read back,
   and never edits the user's own sequence. What real Premiere does is the point of running it. */
const test = require("node:test");
const assert = require("node:assert/strict");

const { probeSyncMoves, formatSyncMovesReport, groupUnits, classifySubframe, TEST_SUFFIX, SPEED_CLONES } =
  require("../uxp/cutdeck/syncProbe.js");

const TPF = 10160640000n; // 25 fps
const SEC = 254016000000n;

/* A tiny timeline model. `audio`: "all" | "none" | "double" — what cloning a video item does
   with its linked audio. `subframe`: whether an audio move may land between frames. */
function fakeHost({ audio = "all", place = "linked", subframe = true, createTracks = true, clips } = {}) {
  let guidSeq = 0;
  const makeSeq = (name, video, audioTracks) => ({ name, id: `g${guidSeq++}`, video, audio: audioTracks });
  const original = makeSeq("Shoot", [[]], [[], []]);
  const add = (seq, kind, track, c) => {
    const list = seq[kind];
    while (list.length <= track) list.push([]);
    list[track].push({ ...c });
  };
  for (const c of clips || [
    { kind: "video", track: 0, path: "D:/cam1/C0001.MP4", start: 0n, end: 250n * TPF, in: 0n },
    { kind: "audio", track: 0, path: "D:/cam1/C0001.MP4", start: 0n, end: 250n * TPF, in: 0n },
    { kind: "audio", track: 1, path: "D:/cam1/C0001.MP4", start: 0n, end: 250n * TPF, in: 0n },
  ]) add(original, c.kind, c.track, c);
  const sequences = [original];

  const wrapItem = (seq, raw) => ({
    _raw: raw, _seq: seq,
    getStartTime: async () => ({ ticks: raw.start.toString() }),
    getEndTime: async () => ({ ticks: raw.end.toString() }),
    getInPoint: async () => ({ ticks: raw.in.toString() }),
    getProjectItem: async () => ({ path: raw.path, getMediaFilePath: async () => raw.path }),
    createMoveAction: (t) => ({ type: "move", seq, raw, by: BigInt(t.ticks) }),
  });
  const wrapSeq = (seq) => ({
    get name() { return seq.name; },
    guid: { toString: () => seq.id },
    _seq: seq,
    getVideoTrackCount: async () => seq.video.length,
    getAudioTrackCount: async () => seq.audio.length,
    getVideoTrack: async (i) => ({ getTrackItems: () => seq.video[i].map((r) => wrapItem(seq, r)) }),
    getAudioTrack: async (i) => ({ getTrackItems: () => seq.audio[i].map((r) => wrapItem(seq, r)) }),
    getTimebase: async () => TPF.toString(),
    getEndTime: async () => {
      const ends = [...seq.video.flat(), ...seq.audio.flat()].map((r) => r.end);
      return { ticks: ends.reduce((a, b) => (b > a ? b : a), 0n).toString() };
    },
    getProjectItem: async () => ({ createSetNameAction: (n) => ({ type: "rename", seq, name: n }) }),
    createCloneAction: () => ({ type: "cloneSeq", seq }),
  });

  const apply = (a) => {
    if (a.type === "cloneSeq") {
      const copy = makeSeq(`${a.seq.name} Copy`, a.seq.video.map((t) => t.map((r) => ({ ...r }))),
        a.seq.audio.map((t) => t.map((r) => ({ ...r }))));
      sequences.push(copy);
    } else if (a.type === "rename") {
      a.seq.name = a.name;
    } else if (a.type === "move") {
      a.raw.start += subframe ? a.by : (a.by / TPF) * TPF + TPF;
    } else if (a.type === "place") {
      const { seq } = a;
      const src = seq.video.flat().find((r) => r.path === a.path);
      const linked = seq.audio.flat().filter((r) => r.path === src.path && r.start === src.start && r.in === src.in);
      const firstA = Math.min(...linked.map((r) => r.track));
      const by = a.time - src.start;
      if (place !== "none") add(seq, "video", a.v, { ...src, track: a.v, start: a.time, end: src.end + by });
      if (place === "linked") for (const r of linked) add(seq, "audio", a.a + r.track - firstA, { ...r, track: a.a + r.track - firstA, start: a.time, end: r.end + by });
    } else if (a.type === "cloneItem" && a.raw.kind === "audio") {
      add(a.seq, "audio", a.raw.track + a.aOff, { ...a.raw, track: a.raw.track + a.aOff, start: a.raw.start + a.by, end: a.raw.end + a.by });
    } else if (a.type === "cloneItem") {
      const { seq, raw } = a;
      const vt = createTracks ? raw.track + a.vOff : Math.min(raw.track + a.vOff, seq.video.length - 1);
      const place = (kind, src, track) => {
        if (track >= seq[kind].length && !createTracks) track = seq[kind].length - 1;
        add(seq, kind, track, { ...src, track, start: src.start + a.by, end: src.end + a.by });
      };
      place("video", raw, vt);
      if (audio !== "none") {
        const linked = seq.audio.flat().filter((r) => r.path === raw.path && r.start === raw.start && r.in === raw.in);
        const firstA = Math.min(...linked.map((r) => r.track));
        for (const r of linked) {
          place("audio", r, firstA + a.aOff + (r.track - firstA));
          if (audio === "double") place("audio", r, firstA + a.aOff + (r.track - firstA));
        }
      }
    }
  };
  let transactions = 0;
  const project = {
    getActiveSequence: async () => wrapSeq(sequences[0]),
    getSequences: async () => sequences.map(wrapSeq),
    openSequence: async () => true,
    setActiveSequence: async () => true,
    lockedAccess: (cb) => cb(),
    executeTransaction: (fn) => {
      const actions = [];
      fn({ addAction: (a) => { actions.push(a); return true; } });
      actions.forEach(apply);
      transactions++;
      return true;
    },
  };
  const ppro = {
    Project: { getActiveProject: async () => project },
    ClipProjectItem: { cast: (pi) => pi },
    Constants: { TrackItemType: { CLIP: 1 } },
    TickTime: { createWithTicks: (s) => ({ ticks: s }) },
    SequenceEditor: {
      getEditor: (s) => ({
        createCloneTrackItemAction: (item, t, vOff, aOff) =>
          ({ type: "cloneItem", seq: s._seq, raw: item._raw, by: BigInt(t.ticks), vOff, aOff }),
        createOverwriteItemAction: (pi, t, v, a) => ({ type: "place", seq: s._seq, path: pi.path, time: BigInt(t.ticks), v, a }),
        createInsertProjectItemAction: (pi, t, v, a) => ({ type: "place", seq: s._seq, path: pi.path, time: BigInt(t.ticks), v, a }),
      }),
    },
  };
  const snapshot = JSON.stringify(original, (k, v) => (typeof v === "bigint" ? v.toString() : v));
  return { ppro, sequences, original, snapshot, get transactions() { return transactions; } };
}

const stringify = (o) => JSON.stringify(o, (k, v) => (typeof v === "bigint" ? v.toString() : v));
const answer = (report, id) => report.findings.find((f) => f.id === id).answer;

test("verdict 'clone-works' when the clone lands on a new track with all its audio", async () => {
  const h = fakeHost({});
  const report = await probeSyncMoves(h.ppro, { now: (() => { let t = 0; return () => (t += 1500); })() });
  assert.equal(report.verdict, "clone-works");
  assert.equal(report.subframe, "between-frames");
  assert.match(answer(report, "clone"), /new track was created/);
  assert.match(answer(report, "audio"), /^yes — 2 audio clip/);
  assert.match(answer(report, "speed"), new RegExp(`${SPEED_CLONES} of ${SPEED_CLONES} landed in 1.5 s`));
  assert.equal(stringify(h.original), h.snapshot, "the user's own sequence was edited");
  assert.equal(h.sequences[1].name, `Shoot${TEST_SUFFIX}`);
  const text = formatSyncMovesReport(report);
  assert.match(text, /VERDICT: the clone lands on a new track with all its audio/);
  assert.match(text, /LINK: click/);
  assert.match(text, /UNDO: press Ctrl\+Z once/);
});

test("live 2026-09-24 case: clone drops audio, placing from the file lands V + all audio", async () => {
  const h = fakeHost({ audio: "none" });
  const report = await probeSyncMoves(h.ppro);
  assert.equal(report.verdict, "place-from-file");
  assert.match(answer(report, "audio"), /only the video was copied/);
  assert.match(answer(report, "audio-separate"), /^yes — 2 audio clip\(s\).*NOT linked/);
  assert.equal(report.subframe, "between-frames", "sub-frame is tested on the separately cloned audio");
  assert.match(answer(report, "place"), /video on V3, 2 audio clip\(s\) on A5, 6 \(original has 2\)/);
  assert.match(formatSyncMovesReport(report), /LINK: click the clip on V3 \(placed from its file/);
  assert.equal(stringify(h.original), h.snapshot);
});

test("falls back to the separate-audio route when placing from the file lands nothing", async () => {
  const report = await probeSyncMoves(fakeHost({ audio: "none", place: "none" }).ppro);
  assert.equal(report.verdict, "clone-separately");
  assert.match(answer(report, "place"), /nothing landed/);
  assert.equal(report.findings.find((f) => f.id === "place").evidence.method, "insert");
});

test("flags duplicated audio — the problem the user saw with XML", async () => {
  const h = fakeHost({ audio: "double" });
  const report = await probeSyncMoves(h.ppro);
  assert.equal(report.verdict, "place-from-file", "placing from the file is the route that works");
  assert.match(formatSyncMovesReport(report), /cloning does not bring the audio correctly/);
  assert.match(answer(report, "audio"), /DUPLICATED — 4 audio clips, the original has 2/);
});

test("reports audio snapping to a whole frame", async () => {
  const report = await probeSyncMoves(fakeHost({ subframe: false }).ppro);
  assert.equal(report.subframe, "snapped");
  assert.match(answer(report, "subframe"), /snapped to a whole frame/);
});

test("says so when the clone does not create a track", async () => {
  const report = await probeSyncMoves(fakeHost({ createTracks: false }).ppro);
  assert.match(answer(report, "clone"), /no new track was created/);
  assert.equal(report.verdict, "clone-works-no-new-track");
});

test("refuses to run on its own test copy", async () => {
  const h = fakeHost({});
  h.sequences[0].name = `Shoot${TEST_SUFFIX}`;
  const report = await probeSyncMoves(h.ppro);
  assert.equal(report.complete, false);
  assert.match(answer(report, "sequence"), /this is a test copy/);
  assert.equal(h.sequences.length, 1, "nothing was copied");
});

test("stops before copying when no clip has audio", async () => {
  const h = fakeHost({ clips: [{ kind: "video", track: 0, path: "D:/drone.MP4", start: 0n, end: SEC, in: 0n }] });
  const report = await probeSyncMoves(h.ppro);
  assert.equal(report.complete, false);
  assert.match(answer(report, "unit"), /^no/);
  assert.equal(h.sequences.length, 1);
});

test("groupUnits pairs a video with the audio from the same file, start and In only", () => {
  const v = { path: "a.mp4", start: 0n, inPoint: 0n, track: 0 };
  const a1 = { path: "a.mp4", start: 0n, inPoint: 0n, track: 0 };
  const a2 = { path: "a.mp4", start: 0n, inPoint: 0n, track: 1 };
  const other = { path: "a.mp4", start: 5n, inPoint: 0n, track: 2 };
  const recorder = { path: "rec.wav", start: 0n, inPoint: 0n, track: 3 };
  const [unit] = groupUnits([v], [a1, a2, other, recorder]);
  assert.deepEqual(unit.audio, [a1, a2]);
});

test("classifySubframe", () => {
  assert.equal(classifySubframe(0n, TPF / 2n, TPF), "between-frames");
  assert.equal(classifySubframe(0n, 0n, TPF), "ignored");
  assert.equal(classifySubframe(0n, TPF, TPF), "snapped");
  assert.equal(classifySubframe(0n, 7n, TPF), "other");
});
