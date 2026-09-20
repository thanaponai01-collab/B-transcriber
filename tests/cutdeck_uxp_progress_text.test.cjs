const test = require("node:test");
const assert = require("node:assert/strict");
const { progressText, FALLBACK } = require("../uxp/cutdeck/progressText.js");

test("shows the stage and percentage the helper reported", () => {
  const text = progressText({ progress: { pct: 35, stage: "Transcribing speech" } });
  assert.match(text, /^Transcribing speech… 35%\n/);
  assert.match(text, /captured In\/Out range/);
});

test("falls back to the existing message before any phase is reported", () => {
  assert.equal(progressText({ state: "running" }), FALLBACK);
  assert.equal(progressText(undefined), FALLBACK);
  assert.match(FALLBACK, /This can take several minutes/);
});

test("malformed progress never renders undefined or NaN", () => {
  for (const progress of [null, {}, { pct: 50 }, { stage: "x" }, { pct: "50", stage: "x" },
                          { pct: NaN, stage: "x" }, { pct: 50, stage: "" }, { pct: 50, stage: 7 }]) {
    assert.equal(progressText({ progress }), FALLBACK, JSON.stringify(progress));
  }
});

test("percentage is rounded and clamped to 0-100", () => {
  assert.match(progressText({ progress: { pct: 149, stage: "s" } }), /… 100%/);
  assert.match(progressText({ progress: { pct: -5, stage: "s" } }), /… 0%/);
  assert.match(progressText({ progress: { pct: 33.6, stage: "s" } }), /… 34%/);
});
