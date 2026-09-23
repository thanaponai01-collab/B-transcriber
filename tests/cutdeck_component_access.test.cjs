/* timeline/componentAccess.js — lifted out of timeline/effects.js once transform/params.js
   became a second consumer of the same selection lookup and value unwrap (Phase 1 of
   docs/research/cutdeck-transform-panel-plan.md, Part 2). These tests pin down the one real
   bug fix in the lift: the old isTrackItemSelected fallback tried `.isSelected` as a function
   then a property, and never `getIsSelected()` — the only getter Adobe actually declares
   (confirmed live on this build, transform-panel-plan.md Part 1a: `typeof item.getIsSelected`
   is "function", `item.isSelected` is `undefined`). That bug meant the per-track selection
   fallback silently returned false for every item whenever seq.getSelection() was the thing
   that failed. */
const test = require("node:test");
const assert = require("node:assert/strict");

const componentAccess = require("../uxp/cutdeck/timeline/componentAccess.js");

// --- isTrackItemSelected --------------------------------------------------------------------

test("isTrackItemSelected uses getIsSelected() when it exists, even if isSelected does not", async () => {
  const item = { getIsSelected: () => Promise.resolve(true) };
  assert.equal(await componentAccess.isTrackItemSelected(item), true);
});

test("isTrackItemSelected returns false, not throws, when getIsSelected() rejects", async () => {
  const item = { getIsSelected: () => Promise.reject(new Error("boom")) };
  assert.equal(await componentAccess.isTrackItemSelected(item), false);
});

test("isTrackItemSelected falls back to a function-typed isSelected when getIsSelected is absent", async () => {
  const item = { isSelected: () => Promise.resolve(true) };
  assert.equal(await componentAccess.isTrackItemSelected(item), true);
});

test("isTrackItemSelected falls back to a plain isSelected/selected property last", async () => {
  assert.equal(await componentAccess.isTrackItemSelected({ isSelected: true }), true);
  assert.equal(await componentAccess.isTrackItemSelected({ selected: true }), true);
  assert.equal(await componentAccess.isTrackItemSelected({}), false);
});

// --- getSelectedTrackItems -------------------------------------------------------------------

test("getSelectedTrackItems prefers seq.getSelection() when it returns items", async () => {
  const items = [{ name: "a" }, { name: "b" }];
  const seq = { getSelection: () => Promise.resolve({ getTrackItems: () => Promise.resolve(items) }) };
  assert.deepEqual(await componentAccess.getSelectedTrackItems(seq), items);
});

test("getSelectedTrackItems falls back to a per-track scan using the FIXED getIsSelected route", async () => {
  const selected = { name: "clip A", getIsSelected: () => Promise.resolve(true) };
  const notSelected = { name: "clip B", getIsSelected: () => Promise.resolve(false) };
  const track = { getTrackItems: () => Promise.resolve([selected, notSelected]) };
  const seq = {
    getSelection: () => Promise.resolve(null), // empty/unreliable selection, as on the real build
    getVideoTrackCount: () => Promise.resolve(1),
    getVideoTrack: () => Promise.resolve(track),
    getAudioTrackCount: () => Promise.resolve(0),
  };
  const items = await componentAccess.getSelectedTrackItems(seq);
  assert.deepEqual(items, [selected]);
});

test("getFirstSelectedTrackItem returns null when nothing is selected", async () => {
  const seq = { getSelection: () => Promise.resolve({ getTrackItems: () => Promise.resolve([]) }) };
  assert.equal(await componentAccess.getFirstSelectedTrackItem(seq), null);
});

test("getSelectedTrackItems returns [] for a null sequence, never throws", async () => {
  assert.deepEqual(await componentAccess.getSelectedTrackItems(null), []);
});

// --- unwrapKeyframeValue -----------------------------------------------------------------

test("unwrapKeyframeValue strips the documented {value:{value:X}} double wrapper", () => {
  assert.deepEqual(componentAccess.unwrapKeyframeValue({ value: { value: [0.5, 0.5] } }), [0.5, 0.5]);
  assert.equal(componentAccess.unwrapKeyframeValue({ value: { value: 100 } }), 100);
});

test("unwrapKeyframeValue leaves an already-plain value alone", () => {
  assert.deepEqual(componentAccess.unwrapKeyframeValue({ value: [0.5, 0.5] }), [0.5, 0.5]);
});

test("unwrapKeyframeValue tolerates a missing keyframe", () => {
  assert.equal(componentAccess.unwrapKeyframeValue(null), null);
  assert.equal(componentAccess.unwrapKeyframeValue(undefined), null);
});

// --- isFixedComponent ----------------------------------------------------------------------

test("isFixedComponent matches Premiere's own fixed effects, case- and whitespace-insensitively", () => {
  assert.equal(componentAccess.isFixedComponent("Motion"), true);
  assert.equal(componentAccess.isFixedComponent(" opacity "), true);
  assert.equal(componentAccess.isFixedComponent("Time Remapping"), true);
  assert.equal(componentAccess.isFixedComponent("Gaussian Blur"), false);
});

// --- runInTransaction ----------------------------------------------------------------------

test("runInTransaction runs through project.lockedAccess when the host provides it", () => {
  const calls = [];
  const project = {
    lockedAccess: (run) => { calls.push("locked"); run(); },
    executeTransaction: (fn, label) => { calls.push(label); fn({ addAction: () => true }); return true; },
  };
  componentAccess.runInTransaction(project, "CutDeck: Test", () => {});
  assert.deepEqual(calls, ["locked", "CutDeck: Test"]);
});

test("runInTransaction throws when executeTransaction reports failure", () => {
  const project = { executeTransaction: () => false };
  assert.throws(() => componentAccess.runInTransaction(project, "CutDeck: Test", () => {}), /Test/);
});
