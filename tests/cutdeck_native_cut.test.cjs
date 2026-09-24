/* Route A end to end against a fake Premiere that behaves the way the live probes proved
   (TODO_LEDGER 2026-09-24): moves are relative and never drag linked audio, SetInPoint trims
   the head, SetOutPoint the tail, a clone copies one item and OVERWRITES what it lands on,
   removal is per media type. The fake is stricter than Premiere where Premiere is unknown: a
   move onto an occupied spot throws, so ordering bugs can't hide. The expected result is the
   XML route's own recut() of the captured synced stack (tests/fixtures golden). */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { applyNativeCut } = require("../uxp/cutdeck/timeline/nativeCut.js");

const golden = JSON.parse(fs.readFileSync(path.join(__dirname, "fixtures", "cutdeck_native_plan_golden.json"), "utf8"));
const TPF = BigInt(golden.ticks_per_frame);

function fakeHost(rows, { speedOf = () => 1, transitions = [] } = {}) {
  let guid = 0;
  const sequences = [];
  const makeSeq = (name, tracks) => { const s = { name, id: `g${guid++}`, tracks }; sequences.push(s); return s; };
  const blank = () => ({ video: [], audio: [] });
  const src = makeSeq("Shoot", blank());
  for (const [kind, track, s, e, i] of rows) {
    while (src.tracks[kind].length <= track) src.tracks[kind].push([]);
    src.tracks[kind][track].push({ kind, track, start: BigInt(s) * TPF, end: BigInt(e) * TPF, in: BigInt(i) * TPF, path: "D:/a.mp4" });
  }
  let transactions = 0;
  const clones = [];
  let inTx = false;
  // Live run 2026-09-24: an action created outside executeTransaction's callback throws.
  const act = (a) => { if (!inTx) throw new Error("The script object is no longer valid."); return a; };
  const overlaps = (a, b) => a.start < b.end && b.start < a.end;
  const trackOf = (seq, r) => seq.tracks[r.kind][r.track];
  const seqOf = (r) => sequences.find((s) => trackOf(s, r) && trackOf(s, r).includes(r));
  const overwrite = (seq, r) => { // Premiere's overwrite: whatever it covers is cut away
    const list = trackOf(seq, r);
    for (const o of [...list]) {
      if (!overlaps(o, r)) continue;
      if (o.start >= r.start && o.end <= r.end) list.splice(list.indexOf(o), 1);
      else if (o.start < r.start && o.end > r.end) { // lands inside: splits it, both sides stay
        list.push({ ...o, start: r.end, in: o.in + (r.end - o.start) });
        o.end = r.start;
      } else if (o.start < r.start) o.end = r.start;
      else { o.in += r.end - o.start; o.start = r.end; }
    }
    list.push(r);
  };
  const apply = (a) => {
    const r = a.raw;
    if (a.type === "cloneSeq") {
      makeSeq(`${a.seq.name} Copy`, { video: a.seq.tracks.video.map((t) => t.map((x) => ({ ...x }))), audio: a.seq.tracks.audio.map((t) => t.map((x) => ({ ...x }))) });
    } else if (a.type === "rename") a.seq.name = a.name;
    else if (a.type === "bin") a.into.items.push(makeBin(a.name));
    else if (a.type === "moveItem") {
      if (!a.from.items.includes(a.pi._seq) && a.from !== rootBin) throw new Error("move must be called on the item's parent");
      a.from.items = a.from.items.filter((x) => x !== a.pi._seq); a.to.items.push(a.pi._seq);
    }
    else if (a.type === "clone") { clones.push(r.end - r.start); overwrite(seqOf(r), { ...r, start: r.start + a.by, end: r.end + a.by }); }
    else if (a.type === "setIn") { r.start += a.t - r.in; r.in = a.t; }
    else if (a.type === "setOut") r.end = r.start + (a.t - r.in);
    else if (a.type === "move") {
      const next = { start: r.start + a.by, end: r.end + a.by };
      if (trackOf(seqOf(r), r).some((o) => o !== r && overlaps(o, next))) throw new Error("move onto an occupied spot");
      r.start = next.start; r.end = next.end;
    } else if (a.type === "remove") {
      for (const x of a.items) if ((a.mt === 2) === (x.kind === "video")) { const l = trackOf(a.seq, x); l.splice(l.indexOf(x), 1); }
    } else throw new Error(`unknown action ${a.type}`);
  };
  let hostReads = 0; // every per-clip read the panel makes
  const n = (v) => { hostReads++; return v; };
  const wrapItem = (r) => ({ _raw: r,
    getStartTime: async () => n({ ticks: r.start.toString() }), getEndTime: async () => n({ ticks: r.end.toString() }),
    getInPoint: async () => n({ ticks: r.in.toString() }), getSpeed: async () => n(speedOf(r)), isSpeedReversed: async () => n(0),
    getProjectItem: async () => n({ getMediaFilePath: async () => n(r.path), isSequence: async () => n(false), isMulticamClip: async () => n(false) }),
    createMoveAction: (t) => act({ type: "move", raw: r, by: BigInt(t.ticks) }),
    createSetInPointAction: (t) => act({ type: "setIn", raw: r, t: BigInt(t.ticks) }),
    createSetOutPointAction: (t) => act({ type: "setOut", raw: r, t: BigInt(t.ticks) }) });
  const wrapTrack = (seq, kind, i) => ({ getTrackItems: (type) => (type === 2
    ? transitions.filter((x) => seq === src && x.kind === kind && x.track === i).map((x) => ({ getStartTime: async () => ({ ticks: x.start.toString() }), getEndTime: async () => ({ ticks: x.end.toString() }) }))
    : seq.tracks[kind][i].map(wrapItem)) });
  const wrapSeq = (seq) => ({ get name() { return seq.name; }, guid: { toString: () => seq.id }, _seq: seq,
    getVideoTrackCount: async () => seq.tracks.video.length, getAudioTrackCount: async () => seq.tracks.audio.length,
    getVideoTrack: async (i) => wrapTrack(seq, "video", i), getAudioTrack: async (i) => wrapTrack(seq, "audio", i),
    getTimebase: async () => TPF.toString(),
    getProjectItem: async () => ({ _seq: seq, createSetNameAction: (n) => act({ type: "rename", seq, name: n }),
      getParentBin: () => binOf(seq) }),
    createCloneAction: () => act({ type: "cloneSeq", seq }) });
  // Project panel: bins hold sequences (by seq object) and child bins.
  const makeBin = (name) => { const b = { name, items: [] };
    b.getItems = async () => b.items;
    b.createBinAction = (child) => act({ type: "bin", into: b, name: child });
    b.createMoveItemAction = (pi, to) => act({ type: "moveItem", from: b, pi, to });
    return b; };
  const rootBin = makeBin("root");
  const binOf = (seq) => { const walk = (b) => (b.items.includes(seq) ? b : b.items.filter((x) => x.items).map(walk).find(Boolean)); return walk(rootBin) || rootBin; };
  const binPath = (seq) => { const walk = (b, path) => (b.items.includes(seq) ? path : b.items.filter((x) => x.items).map((x) => walk(x, [...path, x.name])).find(Boolean)); return walk(rootBin, []); };
  const events = [];
  const project = {
    getRootItem: async () => rootBin,
    getSequences: async () => sequences.map(wrapSeq), openSequence: async () => true,
    setActiveSequence: async (w) => { events.push(`open ${w.name}`); return true; },
    lockedAccess: (cb) => cb(),
    executeTransaction: (fn) => {
      const actions = [];
      inTx = true;
      try { fn({ addAction: (x) => { actions.push(x); return true; } }); } finally { inTx = false; }
      actions.forEach(apply);
      events.push(`tx ${actions[0] ? actions[0].type : "empty"}`);
      transactions++;
      return true;
    },
  };
  const ppro = {
    ClipProjectItem: { cast: (pi) => pi },
    Constants: { TrackItemType: { CLIP: 1, TRANSITION: 2 }, MediaType: { ANY: 0, DATA: 1, VIDEO: 2, AUDIO: 3 } },
    TickTime: { createWithTicks: (s) => ({ ticks: s }) },
    TrackItemSelection: { createEmptySelection: (cb) => { const items = []; cb({ items, addItem: (it) => items.push(it._raw) }); return true; } },
    SequenceEditor: { getEditor: (s) => ({
      createCloneTrackItemAction: (item, t) => act({ type: "clone", raw: item._raw, by: BigInt(t.ticks) }),
      createRemoveItemsAction: (sel, ripple, mt) => act({ type: "remove", seq: s._seq, items: sel.items, mt }),
    }) },
  };
  const rowsOf = (seq) => ["video", "audio"].flatMap((k) => seq.tracks[k].flatMap((t) =>
    t.map((r) => JSON.stringify([k, r.track, Number(r.start / TPF), Number(r.end / TPF), Number(r.in / TPF)])))).sort();
  return { ppro, project, source: wrapSeq(src), src, sequences, rowsOf, clones, events, binPath, get transactions() { return transactions; }, get hostReads() { return hostReads; } };
}

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
  assert.ok(r.steps <= 5);
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
  assert.ok(h.hostReads < 60000, `host reads ${h.hostReads}`);
});
