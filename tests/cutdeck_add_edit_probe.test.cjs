/* "Test Native Add Edit" / "Check Add Edit" (uxp/cutdeck/addEditProbe.js) against a fake host and
   a fake helper that stands in for the Cutter Probe plugin: it cuts the ACTIVE sequence at ITS
   playhead, the way Add Edit to All Tracks is expected to, or misbehaves on purpose. The probe must
   call only an exact split "exact", and must never edit the source sequence itself. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const probe = require("../uxp/cutdeck/addEditProbe.js");
const { PROBES, createProbesFeature } = require("../uxp/cutdeck/features/probes.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");

const TPS = 254016000000n;
const TPF = TPS / 25n; // 25 fps: the live test sequence's timebase was 10160640000 ticks/frame
const F = (n) => BigInt(n) * TPF;

function fakeHost(rows, { zeroFrames = 0, timebase = TPF } = {}) {
  let ids = 0;
  const sequences = [];
  const makeSeq = (name, clips) => {
    const s = { name, id: `g${ids++}`, clips, playhead: 0n };
    sequences.push(s);
    return s;
  };
  const src = makeSeq("Shoot", rows.map(([kind, track, s, e, i]) => ({ kind, track, start: F(s), end: F(e), in: F(i), path: "D:/a.mp4", selected: false })));
  let active = src;
  let inTx = false;
  const act = (a) => { if (!inTx) throw new Error("The script object is no longer valid."); return a; };
  const wrapItem = (c) => ({
    getStartTime: async () => ({ ticks: c.start.toString() }), getEndTime: async () => ({ ticks: c.end.toString() }),
    getInPoint: async () => ({ ticks: c.in.toString() }),
    getProjectItem: async () => ({ getMediaFilePath: async () => c.path }),
    getIsSelected: async () => c.selected,
  });
  const wrapSeq = (seq) => {
    const count = (kind) => Math.max(0, ...seq.clips.filter((c) => c.kind === kind).map((c) => c.track + 1));
    const track = (kind, t) => ({ getTrackItems: () => seq.clips.filter((c) => c.kind === kind && c.track === t).map(wrapItem) });
    return {
      get name() { return seq.name; }, guid: { toString: () => seq.id }, _seq: seq,
      getVideoTrackCount: async () => count("video"), getAudioTrackCount: async () => count("audio"),
      getVideoTrack: async (t) => track("video", t), getAudioTrack: async (t) => track("audio", t),
      getTimebase: async () => timebase.toString(),
      getZeroPoint: async () => ({ ticks: F(zeroFrames).toString() }),
      getPlayerPosition: async () => ({ ticks: seq.playhead.toString() }),
      setPlayerPosition: async (t) => { seq.playhead = BigInt(t.ticks); return true; },
      getProjectItem: async () => ({ createSetNameAction: (n) => act({ type: "rename", seq, name: n }) }),
      createCloneAction: () => act({ type: "clone", seq }),
    };
  };
  const project = {
    getSequences: async () => sequences.map(wrapSeq),
    getActiveSequence: async () => wrapSeq(active),
    setActiveSequence: async (w) => { active = w._seq; return true; },
    openSequence: async () => true,
    lockedAccess: (cb) => cb(),
    executeTransaction: (fn) => {
      const actions = [];
      inTx = true;
      try { fn({ addAction: (x) => { actions.push(x); return true; } }); } finally { inTx = false; }
      for (const a of actions) {
        if (a.type === "clone") makeSeq(`${a.seq.name} Copy`, a.seq.clips.map((c) => ({ ...c })));
        if (a.type === "rename") a.seq.name = a.name;
      }
      return true;
    },
  };
  const ppro = {
    Project: { getActiveProject: async () => project },
    Constants: { TrackItemType: { CLIP: 1 } },
    TickTime: { createWithTicks: (s) => { if (typeof s !== "string") throw new Error("Illegal Parameter type"); return { ticks: s }; } },
  };
  const display = (seq) => probe.smpte((F(zeroFrames) + seq.playhead) / TPF, 25n);
  const cut = (seq, at, kinds = ["video", "audio"]) => {
    seq.clips = seq.clips.flatMap((c) => (kinds.includes(c.kind) && c.start < at && at < c.end
      ? [{ ...c, end: at }, { ...c, start: at, in: c.in + (at - c.start) }] : [c]));
  };
  // The plugin's contract: runs only when the displayed timecode matches, on the active sequence.
  const requests = [];
  const rpc = (mode = "exact") => async (req) => {
    requests.push(req);
    const shown = display(active);
    if (mode === "refuse" || shown !== req.expected_timecode) return { status: "refused", reason: "timecode_mismatch", time_before: shown };
    if (mode === "exact") cut(active, active.playhead);
    if (mode === "video-only") cut(active, active.playhead, ["video"]);
    if (mode === "one-frame-late") cut(active, active.playhead + TPF);
    if (mode === "source") cut(src, active.playhead);
    return { status: "executed", time_before: shown, time_after: shown };
  };
  return { ppro, project, src, sequences, rpc, requests, active: () => active, cut };
}

const plain = [["video", 0, 0, 400, 0], ["audio", 0, 0, 400, 0], ["audio", 1, 0, 400, 0]];

test.beforeEach(() => probe._reset());

test("an exact native split on the copy passes, cuts at frame 120 and leaves the source alone", async () => {
  const h = fakeHost(plain);
  const before = JSON.stringify(h.src.clips, (k, v) => (typeof v === "bigint" ? v.toString() : v));
  const r = await probe.probeAddEdit(h.ppro, { rpc: h.rpc("exact") });
  assert.equal(r.verdict, "exact", probe.formatAddEditReport(r));
  assert.equal(r.expectedTimecode, "00:00:04:20");
  assert.equal(r.cutTicks, F(120).toString());
  assert.deepEqual(h.requests, [{ type: "native_split_request", expected_timecode: "00:00:04:20" }]);
  assert.equal(JSON.stringify(h.src.clips, (k, v) => (typeof v === "bigint" ? v.toString() : v)), before);
  assert.equal(h.active().clips.length, 6);
  assert.match(h.active().name, /^CutDeck AddEdit Probe /);
});

test("the expected timecode includes the sequence start offset", async () => {
  const h = fakeHost(plain, { zeroFrames: 25 * 3600 });
  const r = await probe.probeAddEdit(h.ppro, { rpc: h.rpc("exact") });
  assert.equal(r.expectedTimecode, "01:00:04:20");
  assert.equal(r.verdict, "exact", probe.formatAddEditReport(r));
});

for (const [mode, pattern] of [["video-only", /missing left piece on audio track 1/], ["one-frame-late", /missing left piece on video track 1/], ["source", /Your sequence changed/]]) {
  test(`a wrong native result (${mode}) is a mismatch, never exact`, async () => {
    const h = fakeHost(plain);
    const r = await probe.probeAddEdit(h.ppro, { rpc: h.rpc(mode) });
    assert.equal(r.verdict, "mismatch", probe.formatAddEditReport(r));
    assert.match(r.problems.join("\n"), pattern);
  });
}

test("a refusal from the plugin is reported with what Premiere showed", async () => {
  const h = fakeHost(plain);
  const r = await probe.probeAddEdit(h.ppro, { rpc: h.rpc("refuse") });
  assert.equal(r.verdict, "not-run");
  assert.match(probe.formatAddEditReport(r), /timecode_mismatch[\s\S]*Premiere showed 00:00:04:20/);
});

test("shapes other than one A/V clip, short clips, selections and fractional rates are refused before any request", async () => {
  const cases = [
    [fakeHost([["video", 0, 0, 400, 0]]), /exactly one video clip and its audio/],
    [fakeHost([...plain, ["video", 1, 0, 400, 0]]), /exactly one video clip/],
    [fakeHost([["video", 0, 0, 400, 0], ["audio", 0, 10, 400, 0]]), /start and end with the video/],
    [fakeHost([["video", 0, 0, 200, 0], ["audio", 0, 0, 200, 0]]), /at least 240 frames/],
    [fakeHost(plain, { timebase: 8475667200n }), /whole number of frames per second/],
  ];
  for (const [h, pattern] of cases) {
    const r = await probe.probeAddEdit(h.ppro, { rpc: h.rpc("exact") });
    assert.equal(r.verdict, "refused");
    assert.match(r.problems[0], pattern);
    assert.equal(h.requests.length, 0);
  }
  const h = fakeHost(plain);
  h.src.clips[0].selected = true;
  const r = await probe.probeAddEdit(h.ppro, { rpc: h.rpc("exact") });
  assert.equal(r.verdict, "refused");
  assert.match(r.problems[0], /Deselect/);
  assert.equal(h.requests.length, 0);
});

test("Check Add Edit reads links from the selection and undo/redo from before/after state", async () => {
  const h = fakeHost(plain);
  assert.equal((await probe.checkAddEdit(h.ppro)).verdict, "no-run");
  await probe.probeAddEdit(h.ppro, { rpc: h.rpc("exact") });
  const copy = h.active();
  const left = (kind) => copy.clips.filter((c) => c.kind === kind && c.start === 0n);
  for (const c of [...left("video"), ...left("audio")]) c.selected = true;
  let r = await probe.checkAddEdit(h.ppro);
  assert.equal(r.state, "after");
  assert.equal(r.linked, true, probe.formatCheckReport(r));
  copy.clips.forEach((c) => { c.selected = false; });
  left("video")[0].selected = true;
  copy.clips.find((c) => c.kind === "audio" && c.start !== 0n).selected = true;
  r = await probe.checkAddEdit(h.ppro);
  assert.equal(r.linked, false);
  copy.clips.forEach((c) => { c.selected = false; });
  copy.clips = h.src.clips.map((c) => ({ ...c }));
  r = await probe.checkAddEdit(h.ppro);
  assert.equal(r.state, "before");
  assert.match(probe.formatCheckReport(r), /BEFORE the cut \(undone\)/);
});

test("verifySplit: an untouched clip outside the cut and a clip ending at the cut are not split", () => {
  const row = (start, end, inPoint, track = 0) => ({ kind: "video", track, start, end, inPoint, path: "p" });
  const before = [row(0n, 10n, 0n), row(10n, 20n, 5n)];
  assert.deepEqual(probe.verifySplit(before, before, 10n), []);
  assert.match(probe.verifySplit(before, [row(0n, 5n, 0n), row(5n, 10n, 5n), before[1]], 10n).join(), /unexpected clip/);
});

test("both probes are in the diagnostics menu and the helper connection reaches the run", async () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "uxp", "cutdeck", "index.html"), "utf8");
  for (const id of ["addedit", "addeditcheck"]) {
    assert.ok(PROBES.find((p) => p.id === id), id);
    assert.match(html, new RegExp(`data-probe="${id}"`));
  }
  const h = fakeHost(plain);
  const ctl = createController({ render: () => {}, initialState: { status: { text: "", level: "ready" } } });
  const report = await createProbesFeature({ ppro: h.ppro, ctl, rpc: h.rpc("exact") }).handleProbe("addedit");
  assert.equal(report.verdict, "exact");
  assert.match(ctl.state.status.text, /cut every track exactly at 00:00:04:20/);
});
