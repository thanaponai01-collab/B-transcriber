/* "Test Ripple Delete" against the fake host's two guesses at Premiere's ripple: per track, and
   every track (sync lock). Neither matches the plan when a cut covers empty space before a later
   clip, so the probe must aim a cut there and must report a mismatch, never "exact". */
const test = require("node:test");
const assert = require("node:assert/strict");
const { fakeHost, golden } = require("./fakes/native_cut_host.cjs");
const { probeRippleDelete, formatRippleReport } = require("../uxp/cutdeck/rippleProbe.js");
const { PROBES } = require("../uxp/cutdeck/features/probes.js");

// Frames at 25 fps-ish golden timebase: 100 frames is several seconds either way.
const plain = [["video", 0, 0, 400, 0], ["audio", 0, 0, 400, 0], ["audio", 1, 0, 400, 0]];
const lateCamera = [...plain, ["video", 1, 150, 400, 0]];

for (const mode of ["track", "all"]) {
  test(`ripple probe (${mode} ripple): a later camera after empty space is caught as a mismatch`, async () => {
    const h = fakeHost(lateCamera, { rippleMode: mode });
    const before = h.rowsOf(h.src);
    const r = await probeRippleDelete(h.ppro);
    assert.equal(r.emptySpaceCase, true, "the probe did not aim a cut over empty space");
    assert.equal(r.verdict, "mismatch", formatRippleReport(r));
    assert.deepEqual(h.rowsOf(h.src), before, "the probe edited the source sequence");
    assert.ok(h.sequences.some((s) => s.name === "Shoot — CutDeck ripple test"));
  });
}

test("ripple probe: per-track ripple on a plain stack is exact, and says the empty-space case was not tested", async () => {
  const h = fakeHost(plain, { rippleMode: "track" });
  const r = await probeRippleDelete(h.ppro);
  assert.equal(r.verdict, "exact", formatRippleReport(r));
  assert.equal(r.emptySpaceCase, false);
  assert.match(formatRippleReport(r), /Not tested: a cut over empty space/);
});

test("ripple probe: sync-lock ripple double-shifts a plain stack and is reported", async () => {
  const h = fakeHost(plain, { rippleMode: "all" });
  const r = await probeRippleDelete(h.ppro);
  assert.equal(r.verdict, "mismatch", formatRippleReport(r));
});

test("ripple probe on the golden synced stack is a mismatch under per-track ripple", async () => {
  const h = fakeHost(golden.before, { rippleMode: "track" });
  const r = await probeRippleDelete(h.ppro);
  assert.equal(r.verdict, "mismatch", formatRippleReport(r));
});

test("the ripple probe is in the diagnostics menu", () => {
  const entry = PROBES.find((p) => p.id === "ripple");
  assert.ok(entry, "no 'ripple' probe entry");
  const html = require("node:fs").readFileSync(require("node:path").join(__dirname, "..", "uxp", "cutdeck", "index.html"), "utf8");
  assert.match(html, /data-probe="ripple"/);
});
