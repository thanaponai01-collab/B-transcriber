/* build_sequence (uxp/cutdeck/timeline/buildSequence.js), HKS build plan step 1e, on the shared
   fake Premiere (tests/fakes/premiere.cjs createTimelineHost). */
const test = require("node:test");
const assert = require("node:assert/strict");

const fake = require("./fakes/premiere.cjs");
const { buildSequence } = require("../uxp/cutdeck/timeline/buildSequence.js");

const S = fake.TICKS_PER_SECOND;
const FRAME = S / 25n;
const PROJECT = "E:\\Shows\\hks.prproj";
const SHOW = "D:\\shoot\\HKS show.mp4";
const DAMAGE = "D:\\fx\\FILM_DAMAGE2.mov";

function host(options = {}) {
  return fake.createTimelineHost({
    path: PROJECT,
    media: [
      { path: SHOW, video: true, audio: true, duration: 600n * S },
      { path: DAMAGE, video: true, audio: false, duration: 30n * S },
    ],
    sequences: [{
      name: "1 YOUTUBE D1",
      video: [[{ media: SHOW, start: 0n, end: 4n * S, in: 100n * S }], [{ media: DAMAGE, start: 0n, end: 2n * S, in: 0n }]],
      audio: [[{ media: SHOW, start: 0n, end: 4n * S, in: 100n * S }]],
    }],
    ...options,
  });
}

const t = (seconds) => String(BigInt(seconds) * S);
const ITEMS = [
  { id: "V1@0", media: SHOW, in_ticks: t(10), out_ticks: t(14), at_ticks: t(0), v: 0, a: 0 },
  { id: "V1@4", media: SHOW, in_ticks: t(50), out_ticks: t(52), at_ticks: t(4), v: 0, a: null },
  { id: "V2@1", media: DAMAGE, in_ticks: t(0), out_ticks: t(3), at_ticks: t(1), v: 1, a: null },
];
const args = (extra = {}) => ({ project: PROJECT, base: "1 YOUTUBE D1", name: "HKS build", items: ITEMS, ...extra });

test("refuses when another project is open, before any edit", async () => {
  const h = host({ path: "E:\\Shows\\other.prproj" });
  await assert.rejects(buildSequence(h.ppro, args()), /not E:\\Shows\\hks\.prproj: nothing was built/);
  assert.deepEqual(h.undoSteps, []);
  assert.equal(h.sequence("HKS build"), undefined);
});

test("accepts the same project read with the \\\\?\\ prefix, other slashes and case", async () => {
  const h = host({ path: "\\\\?\\E:\\Shows\\HKS.prproj" });
  const report = await buildSequence(h.ppro, args({ project: "e:/shows/hks.prproj" }));
  assert.equal(report.sequence, "HKS build");
});

test("places every item on a cleared copy, clears scratch tracks, restores marks, and saves only when asked", async () => {
  const h = host();
  const report = await buildSequence(h.ppro, args());
  assert.equal(report.mismatches, 0);
  assert.equal(report.saved, false);
  assert.equal(h.saves, 0);
  const built = h.sequence("HKS build");
  assert.deepEqual(built.video, [
    { track: 0, start: 0n, end: 4n * S, in: 10n * S, media: SHOW },
    { track: 0, start: 4n * S, end: 6n * S, in: 50n * S, media: SHOW },
    { track: 1, start: 1n * S, end: 4n * S, in: 0n, media: DAMAGE },
  ]);
  assert.deepEqual(built.audio, [{ track: 0, start: 0n, end: 4n * S, in: 10n * S, media: SHOW }], "the video-only item's audio is gone");
  assert.deepEqual(h.marks(SHOW), { in: 0n, out: 600n * S });
  assert.deepEqual(h.marks(DAMAGE), { in: 0n, out: 30n * S });
  assert.equal(h.sequence("1 YOUTUBE D1").video.length, 2, "the base is untouched");

  const again = host();
  assert.equal((await buildSequence(again.ppro, args({ save: true }))).saved, true);
  assert.equal(again.saves, 1);
});

test("reports an item that landed more than a frame off", async () => {
  const h = host({ place: (n) => (n === 2 ? 2n * FRAME : 0n) });
  const report = await buildSequence(h.ppro, args());
  assert.equal(report.mismatches, 1);
  assert.deepEqual(report.first_mismatches, [{ id: "V1@4", kind: "video", track: 0, problem: "missing", at: 4 }]);
});

test("a throw while placing still restores the source marks", async () => {
  const h = host({ place: (n) => { if (n === 3) throw new Error("Invalid parameter."); return 0n; } });
  await assert.rejects(buildSequence(h.ppro, args()), /Invalid parameter/);
  assert.deepEqual(h.marks(SHOW), { in: 0n, out: 600n * S });
  assert.deepEqual(h.marks(DAMAGE), { in: 0n, out: 30n * S });
  assert.equal(h.undoSteps.at(-1), "CutDeck build: restore source marks");
});

test("disable_tracks switches off every clip on the named tracks and nothing else", async () => {
  const h = host();
  const report = await buildSequence(h.ppro, args({ disable_tracks: { video: [1], audio: [] } }));
  assert.equal(report.disabled, 1);
  const built = h.sequence("HKS build");
  assert.deepEqual(built.video.filter((c) => c.disabled).map((c) => c.track), [1]);
  assert.equal(built.audio.some((c) => c.disabled), false);
  assert.ok(h.undoSteps.includes("CutDeck build: disable tracks"));
});

test("mark_whole sets the built sequence's In/Out to 0 .. the last item's end", async () => {
  const h = host();
  const report = await buildSequence(h.ppro, args({ mark_whole: true }));
  assert.deepEqual(report.marked, { in_s: 0, out_s: 6 }); // V1@4 runs 4-6 s
  assert.equal((await buildSequence(h.ppro, args({ name: "plain" }))).marked, null);
});

test("into edits the base itself: settings, far-end-first moves, restyle, and scratch past named tracks", async () => {
  const h = fake.createTimelineHost({
    path: PROJECT,
    media: [{ path: SHOW, video: true, audio: true, duration: 600n * S }, { path: DAMAGE, video: true, audio: false, duration: 30n * S }],
    sequences: [
      { name: "cut", video: [[{ media: SHOW, start: 0n, end: 2n * S, in: 10n * S }, { media: SHOW, start: 2n * S, end: 4n * S, in: 20n * S },
        { media: SHOW, start: 4n * S, end: 5n * S, in: 30n * S }], [{ media: DAMAGE, start: 0n, end: 5n * S, in: 0n, disabled: true }]],
        audio: [[{ media: SHOW, start: 0n, end: 2n * S, in: 10n * S }, { media: SHOW, start: 2n * S, end: 4n * S, in: 20n * S },
          { media: SHOW, start: 4n * S, end: 5n * S, in: 30n * S }]] },
      { name: "vertical", frame: "1080x1920", video: [[{ media: SHOW, start: 0n, end: 1n * S, in: 0n }]], audio: [[]] },
    ],
  });
  // Hook (4-5 s) to the front: park it at 10 s, shift 0-4 s right by 1 s, bring the hook to 0.
  const report = await buildSequence(h.ppro, {
    project: PROJECT, base: "cut", name: "cut", into: true, settings_from: "vertical",
    steps: [{ op: "move", from_ticks: t(4), to_ticks: t(5), dt_ticks: t(6) }, { op: "move", from_ticks: t(0), to_ticks: t(4), dt_ticks: t(1) },
      { op: "move", from_ticks: t(10), to_ticks: t(11), dt_ticks: String(-10n * S) }],
    restyle: [{ kind: "video", track: 1, from_ticks: t(0), to_ticks: t(99), enabled: true }],
    items: [{ id: "proof", media: DAMAGE, in_ticks: t(0), out_ticks: t(1), at_ticks: t(1), v: 2, a: null }],
  });
  const built = h.sequence("cut");
  assert.equal(built.frame, "1080x1920");
  assert.deepEqual(built.video.filter((c) => c.track === 0).map((c) => [c.start / S, c.in / S]), [[1n, 10n], [3n, 20n], [0n, 30n]]);
  assert.deepEqual(built.audio.filter((c) => c.track === 0).map((c) => [c.start / S, c.in / S]), [[1n, 10n], [3n, 20n], [0n, 30n]]);
  assert.equal(built.video.find((c) => c.track === 1).disabled, undefined);
  assert.deepEqual(built.video.filter((c) => c.track === 2).map((c) => c.start / S), [1n]);
  assert.equal(report.restyled, 1);
  assert.equal(report.mismatches, 0);
  assert.equal(h.sequence("cut Copy"), undefined); // no clone in into mode
});

test("into refuses a name other than the base", async () => {
  await assert.rejects(buildSequence(host().ppro, args({ into: true })), /name must be "1 YOUTUBE D1" too/);
});

test("into lift removes the clips starting in a range without ripple, before the moves", async () => {
  const h = fake.createTimelineHost({
    path: PROJECT,
    media: [{ path: SHOW, video: true, audio: true, duration: 600n * S }],
    sequences: [{ name: "cut",
      video: [[{ media: SHOW, start: 0n, end: 1n * S, in: 0n }, { media: SHOW, start: 1n * S, end: 3n * S, in: 10n * S }, { media: SHOW, start: 3n * S, end: 4n * S, in: 50n * S }]],
      audio: [[{ media: SHOW, start: 0n, end: 1n * S, in: 0n }, { media: SHOW, start: 1n * S, end: 3n * S, in: 10n * S }, { media: SHOW, start: 3n * S, end: 4n * S, in: 50n * S }]] }],
  });
  // Head block 0-1 s lifted, the hook (3-4 s) moved into the hole: no clip ever passes the end.
  await buildSequence(h.ppro, { project: PROJECT, base: "cut", name: "cut", into: true,
    steps: [{ op: "lift", from_ticks: t(0), to_ticks: t(1) }, { op: "move", from_ticks: t(3), to_ticks: t(4), dt_ticks: String(-3n * S) }],
    items: [{ id: "x", media: SHOW, in_ticks: t(100), out_ticks: t(101), at_ticks: t(5), v: 0, a: 0 }] });
  const built = h.sequence("cut");
  assert.deepEqual(built.video.filter((c) => c.in !== 100n * S).map((c) => [c.start / S, c.in / S]).sort((a, b) => Number(a[0] - b[0])), [[0n, 50n], [1n, 10n]]);
  assert.deepEqual(built.audio.filter((c) => c.in !== 100n * S).map((c) => [c.start / S, c.in / S]).sort((a, b) => Number(a[0] - b[0])), [[0n, 50n], [1n, 10n]]);
  assert.ok(h.undoSteps.some((s) => s.startsWith("CutDeck build: lift video")));
});

test("into clone + lift brings a later block forward without moving it past other clips", async () => {
  const h = fake.createTimelineHost({
    path: PROJECT,
    media: [{ path: SHOW, video: true, audio: true, duration: 600n * S }],
    sequences: [{ name: "cut",
      video: [[{ media: SHOW, start: 0n, end: 1n * S, in: 0n }, { media: SHOW, start: 1n * S, end: 3n * S, in: 10n * S }, { media: SHOW, start: 3n * S, end: 4n * S, in: 50n * S }]],
      audio: [[{ media: SHOW, start: 0n, end: 1n * S, in: 0n }, { media: SHOW, start: 1n * S, end: 3n * S, in: 10n * S }, { media: SHOW, start: 3n * S, end: 4n * S, in: 50n * S }]] }],
  });
  await buildSequence(h.ppro, { project: PROJECT, base: "cut", name: "cut", into: true,
    steps: [{ op: "lift", from_ticks: t(0), to_ticks: t(1) },
      { op: "clone", from_ticks: t(3), to_ticks: t(4), dt_ticks: String(-3n * S) },
      { op: "lift", from_ticks: t(3), to_ticks: t(4) }],
    items: [{ id: "x", media: SHOW, in_ticks: t(100), out_ticks: t(101), at_ticks: t(5), v: 0, a: 0 }] });
  const built = h.sequence("cut");
  const keep = (list) => list.filter((c) => c.in !== 100n * S).map((c) => [c.start / S, c.in / S]).sort((a, b) => Number(a[0] - b[0]));
  assert.deepEqual(keep(built.video), [[0n, 50n], [1n, 10n]]);
  assert.deepEqual(keep(built.audio), [[0n, 50n], [1n, 10n]]);
  assert.ok(h.undoSteps.some((s) => s.startsWith("CutDeck build: clone")));
});

test("into clone with tracks copies only those tracks (one text layer onto a later Short)", async () => {
  const h = fake.createTimelineHost({
    path: PROJECT,
    media: [{ path: SHOW, video: true, audio: true, duration: 600n * S }],
    sequences: [{ name: "cut",
      video: [[{ media: SHOW, start: 0n, end: 2n * S, in: 0n }], [{ media: SHOW, start: 0n, end: 1n * S, in: 7n * S }]],
      audio: [[{ media: SHOW, start: 0n, end: 2n * S, in: 0n }]] }],
  });
  await buildSequence(h.ppro, { project: PROJECT, base: "cut", name: "cut", into: true,
    steps: [{ op: "clone", from_ticks: t(0), to_ticks: t(1), dt_ticks: t(10), tracks: { video: [1] } }],
    items: [{ id: "x", media: SHOW, in_ticks: t(100), out_ticks: t(101), at_ticks: t(20), v: 0, a: 0 }] });
  const built = h.sequence("cut");
  const at10 = [...built.video, ...built.audio].filter((c) => c.start === 10n * S);
  assert.deepEqual(at10.map((c) => [c.track, c.in / S]), [[1, 7n]]);
});

test("into clone with v_offset puts the video copy on a higher track (a pasted title onto the subtitle track)", async () => {
  const h = fake.createTimelineHost({
    path: PROJECT,
    media: [{ path: SHOW, video: true, audio: true, duration: 600n * S }],
    sequences: [{ name: "cut",
      video: [[{ media: SHOW, start: 0n, end: 2n * S, in: 0n }, { media: SHOW, start: 60n * S, end: 62n * S, in: 7n * S }], [], []],
      audio: [[{ media: SHOW, start: 0n, end: 2n * S, in: 0n }]] }],
  });
  await buildSequence(h.ppro, { project: PROJECT, base: "cut", name: "cut", into: true,
    steps: [{ op: "clone", from_ticks: t(60), to_ticks: t(61), dt_ticks: String(-59n * S), tracks: { video: [0] }, v_offset: 2 }],
    items: [] });
  const built = h.sequence("cut");
  assert.deepEqual(built.video.filter((c) => c.start === 1n * S).map((c) => [c.track, c.in / S]), [[2, 7n]]);
  assert.deepEqual(built.video.filter((c) => c.track === 0).map((c) => c.start / S), [0n, 60n]); // V1 untouched
});

test("into clone with a negative v_offset then lift moves Graphics down (srt_subtitles: Upgrade lands them on top)", async () => {
  const h = fake.createTimelineHost({
    path: PROJECT,
    media: [{ path: SHOW, video: true, audio: true, duration: 600n * S }],
    sequences: [{ name: "cut",
      video: [[{ media: SHOW, start: 0n, end: 9n * S, in: 0n }], [], [{ media: SHOW, start: 1n * S, end: 2n * S, in: 3n * S }, { media: SHOW, start: 2n * S, end: 4n * S, in: 5n * S }]],
      audio: [[{ media: SHOW, start: 0n, end: 9n * S, in: 0n }]] }],
  });
  const span = { from_ticks: t(1), to_ticks: String(2n * S + 1n), tracks: { video: [2] } };
  await buildSequence(h.ppro, { project: PROJECT, base: "cut", name: "cut", into: true,
    steps: [{ op: "clone", ...span, dt_ticks: "0", v_offset: -1 }, { op: "lift", ...span }], items: [] });
  const built = h.sequence("cut");
  assert.deepEqual(built.video.filter((c) => c.track === 1).map((c) => [c.start / S, c.end / S]), [[1n, 2n], [2n, 4n]]);
  assert.equal(built.video.filter((c) => c.track === 2).length, 0);
  assert.deepEqual(built.video.filter((c) => c.track === 0).map((c) => c.start), [0n]); // V1 untouched
});

test("into trim ends a clip on a cut (a copied title) through its out point", async () => {
  const h = fake.createTimelineHost({
    path: PROJECT,
    media: [{ path: SHOW, video: true, audio: true, duration: 600n * S }],
    sequences: [{ name: "cut",
      video: [[{ media: SHOW, start: 0n, end: 6n * S, in: 0n }], [{ media: SHOW, start: 1n * S, end: 5n * S, in: 30n * S }]],
      audio: [[{ media: SHOW, start: 0n, end: 6n * S, in: 0n }]] }],
  });
  await buildSequence(h.ppro, { project: PROJECT, base: "cut", name: "cut", into: true,
    steps: [{ op: "trim", from_ticks: t(1), to_ticks: t(2), end_ticks: t(4), tracks: { video: [1] } }],
    items: [{ id: "x", media: SHOW, in_ticks: t(100), out_ticks: t(101), at_ticks: t(10), v: 0, a: 0 }] });
  const built = h.sequence("cut");
  const v1 = built.video.filter((c) => c.track === 1).map((c) => [c.start / S, c.end / S, c.in / S]);
  assert.deepEqual(v1, [[1n, 4n, 30n]]);
  assert.deepEqual(built.video.filter((c) => c.track === 0 && c.in === 0n).map((c) => c.end / S), [6n], "other tracks untouched");
});

const STILL = "E:\\assets\\proof.png";

test("import: true brings a still into CutDeck > Frame Holds once, places it, and reuses it next build", async () => {
  const h = host({ media: [
    { path: SHOW, video: true, audio: true, duration: 600n * S },
    { path: STILL, name: "proof.png", video: true, audio: false, duration: 3600n * S },
  ] });
  const still = { id: "still", media: STILL, import: true, in_ticks: t(0), out_ticks: t(2), at_ticks: t(1), v: 1, a: null };
  const report = await buildSequence(h.ppro, args({ items: [ITEMS[0], still] }));
  assert.equal(report.mismatches, 0);
  assert.deepEqual(h.imports, [STILL]);
  assert.deepEqual(h.sequence("HKS build").video.filter((c) => c.media === STILL).map((c) => [c.track, c.start / S, c.end / S]), [[1, 1n, 3n]]);
  const cutdeck = (await (await h.project.getRootItem()).getItems()).find((b) => b.name === "CutDeck");
  const holds = (await cutdeck.getItems()).find((b) => b.name === "Frame Holds");
  assert.deepEqual((await holds.getItems()).map((i) => i.name), ["proof.png"]);

  await buildSequence(h.ppro, args({ name: "again", items: [still] }));
  assert.deepEqual(h.imports, [STILL], "a file already in the bin is not imported twice");
});

test("an import that fails stops the build before any edit", async () => {
  const h = host();
  const missing = { id: "gone", media: "E:\\assets\\gone.png", import: true, in_ticks: t(0), out_ticks: t(1), at_ticks: t(0), v: 1, a: null };
  await assert.rejects(buildSequence(h.ppro, args({ items: [missing] })), /Import of E:\\assets\\gone\.png failed .*nothing was built/);
  assert.equal(h.sequence("HKS build"), undefined);
});

test("a failure after into steps ran names the phase and says not to retry on that copy", async () => {
  const h = host();
  await assert.rejects(
    buildSequence(h.ppro, { project: PROJECT, base: "1 YOUTUBE D1", name: "1 YOUTUBE D1", into: true,
      steps: [{ op: "lift", from_ticks: t(0), to_ticks: t(1) }, { op: "bogus", from_ticks: t(0), to_ticks: t(1) }],
      items: [ITEMS[0]] }),
    /Unknown step bogus \(build stopped after phase "settings"\. 1 of 2 steps were already applied to "1 YOUTUBE D1": build again on a fresh copy, never on this one\.\)/);
});

test("a failure before any step names the phase without the retry warning", async () => {
  const h = host();
  const err = await buildSequence(h.ppro, args({ items: [{ ...ITEMS[0], media: "D:\\nowhere.mp4" }] })).catch((e) => e);
  assert.match(err.message, /no project item for D:\\nowhere\.mp4/);
  assert.match(err.message, /build stopped after phase "start"/);
  assert.doesNotMatch(err.message, /already applied/);
});
