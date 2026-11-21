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
