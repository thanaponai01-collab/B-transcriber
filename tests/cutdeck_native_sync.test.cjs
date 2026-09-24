/* timeline/nativeSync.js: native multi-cam Sync against a fake Premiere. Proves the panel's half
   off-host — which tracks each clip gets, video snapped to frames while audio keeps exact ticks,
   the refusal on *_Synced, the user's sequence left untouched, and a read-back that names a clip
   that landed short, late, or not at all. What real Premiere does with these calls is for the
   live run (docs/HANDOFF_CUTDECK_NATIVE_SYNC.md, "Unknowns"). */
const test = require("node:test");
const assert = require("node:assert/strict");

const sync = require("../uxp/cutdeck/timeline/nativeSync.js");

const SEC = 254016000000n;
const TPF = 10160640000n; // 25 fps

/* files: path -> { seconds, channels, video, markedSeconds? }. Overwrite lays down the whole file
   (or its Source Monitor marks) like a drag from the bin. Switches model hosts that misbehave. */
function fakeHost({ files, timeline, snapAudio = false, oneNewTrackPerTransaction = false, removeIgnored = false }) {
  let guidSeq = 0;
  const makeSeq = (name) => ({ name, id: `g${guidSeq++}`, video: [], audio: [] });
  const add = (seq, kind, track, raw) => {
    while (seq[kind].length <= track) seq[kind].push([]);
    seq[kind][track].push({ ...raw, track });
  };
  const original = makeSeq("Shoot");
  for (const c of timeline) add(original, c.kind, c.track, { path: c.path, start: c.start, end: c.end, in: c.in || 0n });
  const sequences = [original];

  const projectItem = (path) => ({ path, getMediaFilePath: async () => path });
  const wrapItem = (raw) => ({
    _raw: raw,
    getStartTime: async () => ({ ticks: raw.start.toString() }),
    getEndTime: async () => ({ ticks: raw.end.toString() }),
    getInPoint: async () => ({ ticks: raw.in.toString() }),
    getProjectItem: async () => projectItem(raw.path),
  });
  const wrapSeq = (seq) => ({
    get name() { return seq.name; },
    guid: { toString: () => seq.id },
    getVideoTrackCount: async () => seq.video.length,
    getAudioTrackCount: async () => seq.audio.length,
    getVideoTrack: async (i) => ({ getTrackItems: () => seq.video[i].map(wrapItem) }),
    getAudioTrack: async (i) => ({ getTrackItems: () => seq.audio[i].map(wrapItem) }),
    getTimebase: async () => TPF.toString(),
    getProjectItem: async () => ({ _seq: seq, createSetNameAction: (n) => ({ type: "rename", seq, name: n }),
      getParentBin: () => binOf(seq) }),
    createCloneAction: () => ({ type: "cloneSeq", seq }),
    _seq: seq,
  });

  // Project panel: bins hold sequences (by seq object) and child bins.
  const makeBin = (name) => { const b = { name, items: [] };
    b.getItems = async () => b.items;
    b.createBinAction = (child) => ({ type: "bin", into: b, name: child });
    b.createMoveItemAction = (pi, to) => ({ type: "moveItem", from: b, pi, to });
    return b; };
  const rootBin = makeBin("root");
  rootBin.items.push(original);
  const binOf = (seq) => { const walk = (b) => (b.items.includes(seq) ? b : b.items.filter((x) => x.items).map(walk).find(Boolean)); return walk(rootBin) || rootBin; };
  const binPath = (seq) => { const walk = (b, path) => (b.items.includes(seq) ? path : b.items.filter((x) => x.items).map((x) => walk(x, [...path, x.name])).find(Boolean)); return walk(rootBin, []); };

  const apply = (a, limits) => {
    if (a.type === "bin") {
      a.into.items.push(makeBin(a.name));
    } else if (a.type === "moveItem") {
      if (!a.from.items.includes(a.pi._seq)) throw new Error("move must be called on the item's parent");
      a.from.items = a.from.items.filter((x) => x !== a.pi._seq); a.to.items.push(a.pi._seq);
    } else if (a.type === "cloneSeq") {
      const copy = makeSeq(`${a.seq.name} Copy`);
      copy.video = a.seq.video.map((t) => t.map((r) => ({ ...r })));
      copy.audio = a.seq.audio.map((t) => t.map((r) => ({ ...r })));
      sequences.push(copy);
      binOf(a.seq).items.push(copy);
    } else if (a.type === "rename") {
      a.seq.name = a.name;
    } else if (a.type === "remove") {
      if (removeIgnored) return;
      for (const kind of ["video", "audio"]) a.seq[kind] = a.seq[kind].map((t) => t.filter((r) => !a.raws.includes(r)));
    } else if (a.type === "place") {
      const f = files[a.path];
      const length = BigInt(Math.round((f.markedSeconds || f.seconds) * Number(SEC)));
      const allowed = (kind, index) => !oneNewTrackPerTransaction || index <= limits[kind];
      if (f.video && a.v >= 0 && allowed("video", a.v)) add(a.seq, "video", a.v, { path: a.path, start: a.time, end: a.time + length, in: 0n });
      let start = a.time;
      if (!f.video && snapAudio) start = (a.time / TPF) * TPF;
      if (a.a >= 0) {
        for (let ch = 0; ch < f.channels; ch++) {
          if (allowed("audio", a.a + ch)) add(a.seq, "audio", a.a + ch, { path: a.path, start, end: start + length, in: 0n });
        }
      }
    }
  };
  let transactions = 0;
  const project = {
    getRootItem: async () => rootBin,
    getActiveSequence: async () => wrapSeq(sequences[0]),
    getSequences: async () => sequences.map(wrapSeq),
    opened: null,
    openSequence: async (s) => { project.opened = s.name; return true; },
    setActiveSequence: async () => true,
    lockedAccess: (cb) => cb(),
    executeTransaction: (fn) => {
      const actions = [];
      fn({ addAction: (a) => { actions.push(a); return true; } });
      const target = actions.find((a) => a.seq) && actions.find((a) => a.seq).seq;
      const limits = target ? { video: target.video.length, audio: target.audio.length } : {};
      actions.forEach((a) => apply(a, limits));
      transactions++;
      return true;
    },
  };
  const ppro = {
    Project: { getActiveProject: async () => project },
    ClipProjectItem: { cast: (pi) => pi },
    Constants: { TrackItemType: { CLIP: 1 }, MediaType: { ANY: "any" } },
    TickTime: { createWithTicks: (s) => ({ ticks: s }) },
    TrackItemSelection: {
      // Like the real host: the selection is only valid while its callback runs (Adobe's
      // eslint-plugin-premierepro rule no-empty-selection-escape; live 2026-09-23).
      createEmptySelection: (cb) => {
        const raws = [];
        let live = true;
        const stale = () => { if (!live) throw new Error("The script object is no longer valid."); };
        cb({ raws, stale, addItem: (item) => { stale(); raws.push(item._raw); return true; } });
        live = false;
        return true;
      },
    },
    SequenceEditor: {
      getEditor: (s) => ({
        createRemoveItemsAction: (sel, ripple, mediaType) => {
          sel.stale();
          assert.equal(ripple, false, "clearing the copy must not ripple");
          assert.equal(mediaType, "any");
          return { type: "remove", seq: s._seq, raws: sel.raws };
        },
        createOverwriteItemAction: (pi, t, v, a) => ({ type: "place", seq: s._seq, path: pi.path, time: BigInt(t.ticks), v, a }),
      }),
    },
  };
  const snapshot = () => JSON.stringify(original, (k, v) => (typeof v === "bigint" ? v.toString() : v));
  return { ppro, project, sequences, original, snapshot, binPath, get transactions() { return transactions; } };
}

/* A helper that answers plan_sync from a {file name: placement} table, running once first. */
function fakeHelper(byName) {
  const calls = [];
  let job = null;
  const rpc = async (req) => {
    calls.push(req);
    if (req.type === "plan_sync") {
      const placements = req.clips.map((c) => ({ id: c.id, reason: "", session: 0, media_duration_s: null,
        ...byName[c.path.split("/").pop()] }));
      job = { job_id: "j1", state: "ready", plan: { placements, sessions: 1, duration_s: 100 } };
      return { job_id: "j1", state: "running", progress: { pct: 33, stage: "Reading audio 1/3" } };
    }
    if (req.type === "status") return job;
    throw new Error(`unexpected ${req.type}`);
  };
  return { rpc, calls };
}

const s = (n) => BigInt(Math.round(n * Number(SEC)));
const FILES = {
  "D:/cam1/C0001.MP4": { seconds: 30, channels: 2, video: true },
  "D:/cam2/C0101.MP4": { seconds: 28, channels: 1, video: true },
  "D:/rec/ZOOM0001.WAV": { seconds: 40, channels: 1, video: false },
};
// The user's flat row: cam1, cam2, then the recorder, each with its audio under it.
const TIMELINE = [
  { kind: "video", track: 0, path: "D:/cam1/C0001.MP4", start: 0n, end: s(30) },
  { kind: "audio", track: 0, path: "D:/cam1/C0001.MP4", start: 0n, end: s(30) },
  { kind: "audio", track: 1, path: "D:/cam1/C0001.MP4", start: 0n, end: s(30) },
  { kind: "video", track: 0, path: "D:/cam2/C0101.MP4", start: s(30), end: s(58) },
  { kind: "audio", track: 0, path: "D:/cam2/C0101.MP4", start: s(30), end: s(58) },
  { kind: "audio", track: 0, path: "D:/rec/ZOOM0001.WAV", start: s(58), end: s(98) },
];
const PLAN = {
  "C0001.MP4": { status: "anchor", start_s: 2.0, media_duration_s: 30 },
  "C0101.MP4": { status: "synced", start_s: 14.3456, matched_to: "c0", media_duration_s: 28 },
  "ZOOM0001.WAV": { status: "synced", start_s: 0.0123, matched_to: "c0", media_duration_s: 40 },
};

async function run(host, helper, extra = {}) {
  const statuses = [];
  const result = await sync.syncSequence(host.ppro, { rpc: helper.rpc, ensureHelper: async () => {},
    onStatus: (t) => statuses.push(t), sleep: async () => {}, ...extra });
  return { ...result, statuses };
}

const items = (seq, kind) => seq[kind].flatMap((t) => t);

test("places each clip on its own tracks at its planned start, in a _Synced copy", async () => {
  const host = fakeHost({ files: FILES, timeline: TIMELINE });
  const helper = fakeHelper(PLAN);
  const before = host.snapshot();
  const { text, problems, statuses } = await run(host, helper);

  assert.deepEqual(problems, []);
  assert.equal(host.snapshot(), before, "the user's own sequence was edited");
  const copy = host.sequences[1];
  assert.equal(copy.name, "Shoot_Synced");
  assert.equal(host.project.opened, "Shoot_Synced");
  assert.deepEqual(host.binPath(copy), ["CutDeck", "Synced"], "the copy is filed under CutDeck > Synced");
  assert.deepEqual(host.binPath(host.original), [], "the user's sequence stays where it was");
  assert.equal(host.transactions, 6, "copy, rename, 2 bins, file, then ONE transaction for all the placing");

  const request = helper.calls.find((c) => c.type === "plan_sync");
  assert.deepEqual(request.clips.map((c) => [c.id, c.path.split("/").pop(), c.duration_s]),
    [["c0", "C0001.MP4", 30], ["c1", "C0101.MP4", 28], ["c2", "ZOOM0001.WAV", 40]]);

  const where = (kind, path) => items(copy, kind).filter((r) => r.path === path).map((r) => [r.track, r.start]);
  assert.deepEqual(where("video", "D:/cam1/C0001.MP4"), [[0, s(2)]]);
  assert.deepEqual(where("audio", "D:/cam1/C0001.MP4"), [[0, s(2)], [1, s(2)]]);
  // 14.3456 s is between frames: video snaps to the nearest frame (358.64 -> 359).
  assert.deepEqual(where("video", "D:/cam2/C0101.MP4"), [[1, 359n * TPF]]);
  assert.deepEqual(where("audio", "D:/cam2/C0101.MP4"), [[2, 359n * TPF]]);
  // Audio-only keeps its exact tick.
  assert.deepEqual(where("audio", "D:/rec/ZOOM0001.WAV"), [[3, s(0.0123)]]);
  assert.notEqual(s(0.0123) % TPF, 0n);
  assert.equal(items(copy, "video").length + items(copy, "audio").length, 6, "the originals were cleared");

  assert.ok(statuses.includes("Matching audio… Reading audio 1/3"));
  assert.match(text, /^3 synced in 1 session\./);
  assert.match(text, /Opened Shoot_Synced\. Ctrl\+Z once undoes the placing\./);
});

test("refuses to run on a _Synced sequence, before calling the helper", async () => {
  const host = fakeHost({ files: FILES, timeline: TIMELINE });
  host.original.name = "Shoot_Synced";
  const helper = fakeHelper(PLAN);
  let helperStarted = false;
  await assert.rejects(run(host, helper, { ensureHelper: async () => { helperStarted = true; } }),
    /already a synced copy/);
  assert.equal(helperStarted, false);
  assert.equal(helper.calls.length, 0);
  assert.equal(host.sequences.length, 1, "nothing was copied");
});

test("reports the clips at the back, drift, and items with no media file", async () => {
  const files = { ...FILES, "D:/drone/DJI_0001.MP4": { seconds: 10, channels: 0, video: true } };
  const timeline = [...TIMELINE,
    { kind: "video", track: 0, path: "D:/drone/DJI_0001.MP4", start: s(98), end: s(108) },
    { kind: "video", track: 1, path: null, start: 0n, end: s(5) }]; // a title
  const plan = { ...PLAN,
    "C0101.MP4": { ...PLAN["C0101.MP4"], reason: "drifts +45 ms across the overlap — check the end" },
    "ZOOM0001.WAV": { status: "unmatched", start_s: 50, reason: "its audio matched no other clip", media_duration_s: 40 },
    "DJI_0001.MP4": { status: "no_audio", start_s: 92, reason: "no usable audio" } };
  const host = fakeHost({ files, timeline });
  const { text, problems } = await run(host, fakeHelper(plan));
  assert.deepEqual(problems, []);
  // Synced clips get their own tracks; the rest lie flat on the first tracks, at their planned time.
  const copy = host.sequences[1];
  const where = (kind, path) => items(copy, kind).filter((r) => r.path === path).map((r) => [r.track, r.start]);
  assert.deepEqual(where("video", "D:/cam2/C0101.MP4"), [[1, 359n * TPF]]);
  assert.deepEqual(where("audio", "D:/rec/ZOOM0001.WAV"), [[0, s(50)]]);
  assert.deepEqual(where("video", "D:/drone/DJI_0001.MP4"), [[0, s(92)]]);
  assert.equal(copy.video.length, 2, "no track was made for a clip that could not be synced");
  assert.equal(copy.audio.length, 3);
  assert.match(text, /^2 synced in 1 session\. 2 at the back: ZOOM0001\.WAV matched nothing, DJI_0001\.MP4 no audio\./);
  assert.match(text, /C0101\.MP4 drifts \+45 ms across the overlap — check the end\./);
  assert.match(text, /Skipped 1 item\(s\) with no media file/);
});

test("read-back flags a clip that lands shorter than its file (Source Monitor marks)", async () => {
  const files = { ...FILES, "D:/cam2/C0101.MP4": { ...FILES["D:/cam2/C0101.MP4"], markedSeconds: 20 } };
  const { problems, text } = await run(fakeHost({ files, timeline: TIMELINE }), fakeHelper(PLAN));
  assert.deepEqual(problems, ["C0101.MP4 is shorter than its file: check its In/Out marks in the Source Monitor"]);
  assert.match(text, /CHECK THE COPY — 1 problem/);
});

test("read-back flags clips that did not land when later track indexes create no track", async () => {
  const { problems } = await run(fakeHost({ files: FILES, timeline: TIMELINE, oneNewTrackPerTransaction: true }),
    fakeHelper(PLAN));
  // The copy starts with V1 and A1-A2; only one more track of each kind is created.
  assert.ok(problems.includes("ZOOM0001.WAV did not land"), problems);
});

test("read-back flags audio that snapped to a frame", async () => {
  const { problems } = await run(fakeHost({ files: FILES, timeline: TIMELINE, snapAudio: true }), fakeHelper(PLAN));
  assert.equal(problems.length, 1);
  assert.match(problems[0], /^ZOOM0001\.WAV landed -\d+ ticks off its planned start$/);
});

test("read-back flags originals left behind on the copy", async () => {
  const { problems } = await run(fakeHost({ files: FILES, timeline: TIMELINE, removeIgnored: true }), fakeHelper(PLAN));
  // The originals share files and tracks with what was placed, so they also muddy cam1's own
  // check; what matters is that the copy is flagged at all.
  assert.ok(problems.some((p) => /other item\(s\) are on the copy that should not be/.test(p)), problems);
});

test("a failed match stops before any copy is made", async () => {
  const host = fakeHost({ files: FILES, timeline: TIMELINE });
  const rpc = async (req) => (req.type === "plan_sync" ? { job_id: "j", state: "running" }
    : { job_id: "j", state: "failed", message: "Sync matching failed: ffmpeg not found on PATH" });
  await assert.rejects(run(host, { rpc }), /ffmpeg not found/);
  assert.equal(host.sequences.length, 1);
});

test("assignTracks: synced clips get their own tracks, the rest share the first ones", () => {
  const clips = [{ video: {}, audio: [{}, {}] }, { video: {}, audio: [{}] }, { video: null, audio: [{}, {}] },
    { video: {}, audio: [] }, { video: {}, audio: [{}, {}] }, { video: null, audio: [{}] }];
  assert.deepEqual(sync.assignTracks(clips, [true, true, true, true, false, false]), [
    { video: 0, audio: 0 }, { video: 1, audio: 2 }, { video: -1, audio: 3 }, { video: 2, audio: -1 },
    { video: 0, audio: 0 }, { video: -1, audio: 0 }]);
});

test("startTicks snaps video to the nearest frame and keeps audio exact", () => {
  assert.equal(sync.startTicks(0.02, true, TPF), TPF, "half a frame rounds up");
  assert.equal(sync.startTicks(0.019, true, TPF), 0n);
  assert.equal(sync.startTicks(0.019, false, TPF), s(0.019));
  assert.equal(sync.startTicks(3600.5, false, TPF), s(3600.5), "an hour in, still exact");
});

test("groupClips: timeline order, recorder audio stands alone, same-file clips at different starts stay apart", () => {
  const v = (path, start) => ({ kind: "video", path, start, end: start + SEC, inPoint: 0n, track: 0 });
  const a = (path, start, track) => ({ kind: "audio", path, start, end: start + SEC, inPoint: 0n, track });
  const seq = { video: [v("cam.mp4", 5n), v("cam.mp4", 0n)],
    audio: [a("cam.mp4", 0n, 0), a("cam.mp4", 5n, 0), a("rec.wav", 2n, 1), a("rec.wav", 2n, 2), a(null, 9n, 3)] };
  const { clips, skipped } = sync.groupClips(seq);
  assert.deepEqual(clips.map((c) => [c.id, c.name, String(c.video && c.video.start), c.audio.length]),
    [["c0", "cam.mp4", "0", 1], ["c1", "rec.wav", "null", 2], ["c2", "cam.mp4", "5", 1]]);
  assert.equal(skipped.length, 1);
});
