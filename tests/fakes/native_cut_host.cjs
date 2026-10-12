/* The fake Premiere host for native cut tests, moved here from cutdeck_native_cut.test.cjs so
   the ripple probe tests share it. Behaviour notes are at the top of that file. */
const fs = require("node:fs");
const path = require("node:path");

const golden = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "cutdeck_native_plan_golden.json"), "utf8"));
const TPF = BigInt(golden.ticks_per_frame);

function fakeHost(rows, { speedOf = () => 1, transitions = [], staleMoveCalls = new Set(), staleCloneCalls = new Set(), rippleMode = "track" } = {}) {
  // rippleMode: what a ripple remove shifts. "track": later clips on that clip's own track;
  // "all": later clips on every track (sync lock on). Premiere's answer is unprobed.
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
  let moveCalls = 0;
  let cloneCalls = 0;
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
      const gone = a.items.filter((x) => (a.mt === 2) === (x.kind === "video")).sort((x, y) => (x.start < y.start ? 1 : -1));
      for (const x of gone) {
        const l = trackOf(a.seq, x); l.splice(l.indexOf(x), 1);
        if (!a.ripple) continue;
        const lanes = rippleMode === "all" ? [...a.seq.tracks.video, ...a.seq.tracks.audio] : [l];
        for (const lane of lanes) for (const o of lane) if (o.start >= x.end) { o.start -= x.end - x.start; o.end -= x.end - x.start; }
      }
    } else throw new Error(`unknown action ${a.type}`);
  };
  let hostReads = 0; // every per-clip read the panel makes
  const n = (v) => { hostReads++; return v; };
  const wrapItem = (r) => {
    const item = { _raw: r, _stale: false,
    getStartTime: async () => n({ ticks: r.start.toString() }), getEndTime: async () => n({ ticks: r.end.toString() }),
    getInPoint: async () => n({ ticks: r.in.toString() }),
    getOutPoint: async () => n({ ticks: (r.in + r.end - r.start).toString() }),
    isDisabled: async () => !!r.disabled,
    getSpeed: async () => n(speedOf(r)), isSpeedReversed: async () => n(0),
    getProjectItem: async () => n({ getMediaFilePath: async () => n(r.path), isSequence: async () => n(false), isMulticamClip: async () => n(false) }),
    createMoveAction: (t) => {
      if (staleMoveCalls.has(++moveCalls)) item._stale = true;
      if (item._stale) throw new Error("The script object is no longer valid.");
      return act({ type: "move", raw: r, by: BigInt(t.ticks) });
    },
    createSetInPointAction: (t) => act({ type: "setIn", raw: r, t: BigInt(t.ticks) }),
    createSetOutPointAction: (t) => act({ type: "setOut", raw: r, t: BigInt(t.ticks) }) };
    return item;
  };
  const wrapTrack = (seq, kind, i) => ({ isMuted: async () => !!seq.tracks[kind][i].muted,
    getTrackItems: (type) => (type === 2
    ? transitions.filter((x) => seq === src && x.kind === kind && x.track === i).map((x) => ({ getStartTime: async () => ({ ticks: x.start.toString() }), getEndTime: async () => ({ ticks: x.end.toString() }) }))
    : seq.tracks[kind][i].map(wrapItem)) });
  const wrapSeq = (seq) => ({ get name() { return seq.name; }, guid: { toString: () => seq.id }, _seq: seq,
    getVideoTrackCount: async () => seq.tracks.video.length, getAudioTrackCount: async () => seq.tracks.audio.length,
    getVideoTrack: async (i) => wrapTrack(seq, "video", i), getAudioTrack: async (i) => wrapTrack(seq, "audio", i),
    getTimebase: async () => TPF.toString(),
    getEndTime: async () => ({ ticks: [...seq.tracks.video.flat(), ...seq.tracks.audio.flat()]
      .reduce((end, r) => r.end > end ? r.end : end, 0n).toString() }),
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
    getActiveSequence: async () => wrapSeq(src),
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
    Project: { getActiveProject: async () => project },
    ClipProjectItem: { cast: (pi) => pi },
    Constants: { TrackItemType: { CLIP: 1, TRANSITION: 2 }, MediaType: { ANY: 0, DATA: 1, VIDEO: 2, AUDIO: 3 } },
    TickTime: { createWithTicks: (s) => ({ ticks: s }) },
    TrackItemSelection: { createEmptySelection: (cb) => { const items = []; cb({ items, addItem: (it) => items.push(it._raw) }); return true; } },
    SequenceEditor: { getEditor: (s) => ({
      createCloneTrackItemAction: (item, t) => {
        if (staleCloneCalls.has(++cloneCalls)) item._stale = true;
        if (item._stale) throw new Error("The script object is no longer valid.");
        return act({ type: "clone", raw: item._raw, by: BigInt(t.ticks) });
      },
      createRemoveItemsAction: (sel, ripple, mt) => act({ type: "remove", seq: s._seq, items: sel.items, mt, ripple }),
    }) },
  };
  const rowsOf = (seq) => ["video", "audio"].flatMap((k) => seq.tracks[k].flatMap((t) =>
    t.map((r) => JSON.stringify([k, r.track, Number(r.start / TPF), Number(r.end / TPF), Number(r.in / TPF)])))).sort();
  return { ppro, project, source: wrapSeq(src), src, sequences, rowsOf, clones, events, binPath,
    get transactions() { return transactions; }, get hostReads() { return hostReads; },
    get cloneCalls() { return cloneCalls; }, get moveCalls() { return moveCalls; } };
}

module.exports = { fakeHost, golden, TPF };
