const test = require("node:test");
const assert = require("node:assert/strict");
const { progressText } = require("../cep/cutdeck/client/progress_text.js");

const STATIC = "Processing sequence in helper… Cuts stay inside marked In/Out.";

test("shows the stage and percentage the helper reported", () => {
  assert.equal(
    progressText({ progress: { pct: 35, stage: "Transcribing speech" } }),
    "Transcribing speech… 35% — cuts stay inside marked In/Out.");
});

test("falls back to the static message before any phase is reported", () => {
  assert.equal(progressText({ state: "running" }), STATIC);
  assert.equal(progressText(undefined), STATIC);
});

test("malformed progress never renders undefined or NaN", () => {
  for (const progress of [null, {}, { pct: 50 }, { stage: "x" }, { pct: "50", stage: "x" },
                          { pct: NaN, stage: "x" }, { pct: 50, stage: "" }, { pct: 50, stage: 7 }]) {
    assert.equal(progressText({ progress }), STATIC, JSON.stringify(progress));
  }
});

test("percentage is rounded and clamped to 0-100", () => {
  assert.match(progressText({ progress: { pct: 149, stage: "s" } }), /… 100% —/);
  assert.match(progressText({ progress: { pct: -5, stage: "s" } }), /… 0% —/);
  assert.match(progressText({ progress: { pct: 33.6, stage: "s" } }), /… 34% —/);
});
