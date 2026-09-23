const test = require("node:test");
const assert = require("node:assert/strict");
const { progressText, FALLBACK } = require("../uxp/cutdeck/core/progressText.js");

test("shows the stage and percentage the helper reported", () => {
  assert.equal(
    progressText({ progress: { pct: 35, stage: "Transcribing speech" } }),
    "Transcribing speech… 35% — cuts stay inside marked In/Out.");
});

test("names the analyzed reference audio once the helper reports it", () => {
  assert.equal(
    progressText({ progress: { pct: 35, stage: "Transcribing speech" }, reference: "A2 (interview.wav)" }),
    "Transcribing speech… 35% — analyzing A2 (interview.wav); cuts stay inside marked In/Out.");
  assert.equal(
    progressText({ progress: { pct: 35, stage: "s" }, reference: 7 }),
    "s… 35% — cuts stay inside marked In/Out.");
});

test("falls back to the static message before any phase is reported", () => {
  assert.equal(progressText({ state: "running" }), FALLBACK);
  assert.equal(progressText(undefined), FALLBACK);
  assert.equal(FALLBACK, "Processing sequence in helper… Cuts stay inside marked In/Out.");
});

test("malformed progress never renders undefined or NaN", () => {
  for (const progress of [null, {}, { pct: 50 }, { stage: "x" }, { pct: "50", stage: "x" },
                          { pct: NaN, stage: "x" }, { pct: 50, stage: "" }, { pct: 50, stage: 7 }]) {
    assert.equal(progressText({ progress }), FALLBACK, JSON.stringify(progress));
  }
});

test("percentage is rounded and clamped to 0-100", () => {
  assert.match(progressText({ progress: { pct: 149, stage: "s" } }), /… 100% —/);
  assert.match(progressText({ progress: { pct: -5, stage: "s" } }), /… 0% —/);
  assert.match(progressText({ progress: { pct: 33.6, stage: "s" } }), /… 34% —/);
});

test("CEP script tag exposes the window global the panel reads", () => {
  const sandbox = { window: undefined };
  const source = require("node:fs").readFileSync(
    require("node:path").join(__dirname, "../uxp/cutdeck/core/progressText.js"), "utf8");
  new Function("module", "window", source.replace("typeof window !== \"undefined\" ? window : globalThis", "window"))(undefined, sandbox);
  assert.equal(typeof sandbox.CutDeckProgressText.progressText, "function");
});
