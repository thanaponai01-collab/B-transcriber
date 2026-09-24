/* host/components.js & host/trackItems.js — split out of timeline/componentAccess.js
   as part of Move 5 (issue #53, docs/arch-design-cutdeck-panel.md).
   Tests component helpers, keyframe value unwrapping, track item access, and selection. */
const test = require("node:test");
const assert = require("node:assert/strict");

const components = require("../uxp/cutdeck/host/components.js");
const trackItems = require("../uxp/cutdeck/host/trackItems.js");

// --- isTrackItemSelected --------------------------------------------------------------------

test("isTrackItemSelected uses getIsSelected() when it exists, even if isSelected does not", async () => {
  const item = { getIsSelected: () => Promise.resolve(true) };
  assert.equal(await trackItems.isTrackItemSelected(item), true);
});

test("isTrackItemSelected returns false, not throws, when getIsSelected() rejects", async () => {
  const item = { getIsSelected: () => Promise.reject(new Error("boom")) };
  assert.equal(await trackItems.isTrackItemSelected(item), false);
});

test("isTrackItemSelected falls back to a function-typed isSelected when getIsSelected is absent", async () => {
  const item = { isSelected: () => Promise.resolve(true) };
  assert.equal(await trackItems.isTrackItemSelected(item), true);
});

test("isTrackItemSelected falls back to a plain isSelected/selected property last", async () => {
  assert.equal(await trackItems.isTrackItemSelected({ isSelected: true }), true);
  assert.equal(await trackItems.isTrackItemSelected({ selected: true }), true);
  assert.equal(await trackItems.isTrackItemSelected({}), false);
  assert.equal(await trackItems.isTrackItemSelected(null), false);
});

// --- getSelectedTrackItems -------------------------------------------------------------------

test("getSelectedTrackItems prefers seq.getSelection() when it returns items", async () => {
  const items = [{ name: "a" }, { name: "b" }];
  const seq = { getSelection: () => Promise.resolve({ getTrackItems: () => Promise.resolve(items) }) };
  assert.deepEqual(await trackItems.getSelectedTrackItems(seq), items);
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
  const items = await trackItems.getSelectedTrackItems(seq);
  assert.deepEqual(items, [selected]);
});

test("getFirstSelectedTrackItem returns null when nothing is selected", async () => {
  const seq = { getSelection: () => Promise.resolve({ getTrackItems: () => Promise.resolve([]) }) };
  assert.equal(await trackItems.getFirstSelectedTrackItem(seq), null);
});

test("getSelectedTrackItems returns [] for a null sequence, never throws", async () => {
  assert.deepEqual(await trackItems.getSelectedTrackItems(null), []);
});

// --- getTrackClipItemsOrThrow & getTrackClipItems -------------------------------------------

test("getTrackClipItemsOrThrow returns items from track.getTrackItems", async () => {
  const items = [{ name: "clip1" }];
  const track = { getTrackItems: () => Promise.resolve(items) };
  const result = await trackItems.getTrackClipItemsOrThrow(track);
  assert.deepEqual(result, items);
});

test("getTrackClipItemsOrThrow passes CLIP constant from ppro when available", async () => {
  const calls = [];
  const track = {
    getTrackItems: (type, selectedOnly) => {
      calls.push({ type, selectedOnly });
      return Promise.resolve([{ name: "c" }]);
    },
  };
  const ppro = { Constants: { TrackItemType: { CLIP: 42 } } };
  const result = await trackItems.getTrackClipItemsOrThrow(track, ppro);
  assert.equal(calls[0].type, 42);
  assert.equal(calls[0].selectedOnly, false);
  assert.equal(result.length, 1);
});

test("getTrackClipItemsOrThrow falls back across multiple signatures on failure", async () => {
  let callCount = 0;
  const track = {
    getTrackItems: (arg) => {
      callCount++;
      if (callCount === 1) throw new Error("first fail");
      return Promise.resolve([{ name: "recovered" }]);
    },
  };
  const result = await trackItems.getTrackClipItemsOrThrow(track);
  assert.equal(result.length, 1);
  assert.equal(callCount, 2);
});

test("getTrackClipItemsOrThrow throws when all attempts fail instead of masking as empty", async () => {
  const track = {
    getTrackItems: () => { throw new Error("track unreadable"); },
  };
  await assert.rejects(
    () => trackItems.getTrackClipItemsOrThrow(track),
    /track unreadable/
  );
});

test("getTrackClipItems returns [] when getTrackClipItemsOrThrow throws", async () => {
  const track = {
    getTrackItems: () => { throw new Error("track unreadable"); },
  };
  const result = await trackItems.getTrackClipItems(track);
  assert.deepEqual(result, []);
});

test("getTrackClipItems drops null entries Premiere returns", async () => {
  const clip = { name: "A" };
  const track = { getTrackItems: () => Promise.resolve([null, clip, undefined]) };
  assert.deepEqual(await trackItems.getTrackClipItems(track), [clip]);
  assert.deepEqual(await trackItems.getTrackClipItemsOrThrow(track), [clip]);
});

// --- getSelectedVideoClips -------------------------------------------------------------------

test("getSelectedVideoClips excludes Audio clips and Adjustment Layers", async () => {
  const videoClip1 = { name: "Footage A", mediaType: "Video", getIsSelected: () => Promise.resolve(true) };
  const adjLayer = { name: "Adjustment Layer 1", mediaType: "Video", getIsSelected: () => Promise.resolve(true) };
  const audioClip = { name: "Footage A Audio", mediaType: "Audio", getIsSelected: () => Promise.resolve(true) };

  const trackV0 = { getTrackItems: () => Promise.resolve([videoClip1, adjLayer]) };
  const trackA0 = { getTrackItems: () => Promise.resolve([audioClip]) };

  const seq = {
    getSelection: () => Promise.resolve({
      getTrackItems: () => Promise.resolve([videoClip1, adjLayer, audioClip]),
    }),
    getVideoTrackCount: () => Promise.resolve(1),
    getVideoTrack: () => Promise.resolve(trackV0),
    getAudioTrackCount: () => Promise.resolve(1),
    getAudioTrack: () => Promise.resolve(trackA0),
  };

  const results = await trackItems.getSelectedVideoClips(null, seq);
  assert.equal(results.length, 1);
  assert.equal(results[0].item, videoClip1);
  assert.equal(results[0].track, 0);
});

test("getSelectedVideoClips trusts isAdjustmentLayer() over the clip name", async () => {
  const sel = () => Promise.resolve(true);
  const footageNamedAdj = { name: "adjustment_test.mp4", isAdjustmentLayer: () => Promise.resolve(false), getIsSelected: sel };
  const renamedAL = { name: "Grade", isAdjustmentLayer: () => Promise.resolve(true), getIsSelected: sel };
  const trackV0 = { getTrackItems: () => Promise.resolve([footageNamedAdj, renamedAL]) };
  const seq = {
    getSelection: () => Promise.resolve({ getTrackItems: () => Promise.resolve([footageNamedAdj, renamedAL]) }),
    getVideoTrackCount: () => Promise.resolve(1),
    getVideoTrack: () => Promise.resolve(trackV0),
  };
  const results = await trackItems.getSelectedVideoClips(null, seq);
  assert.deepEqual(results.map((r) => r.item), [footageNamedAdj]);
});

test("getSelectedVideoClips reads only the video tracks getTrackIndex() names", async () => {
  const sel = () => Promise.resolve(true);
  const onV2 = { name: "B-roll", getTrackIndex: () => Promise.resolve(1), getIsSelected: sel };
  const audioA1 = { name: "Mic", getTrackIndex: () => Promise.resolve(0), getIsSelected: sel };
  const reads = [];
  const tracks = [
    { getTrackItems: () => Promise.resolve([{ name: "V1 clip" }]) },
    { getTrackItems: () => Promise.resolve([onV2]) },
    { getTrackItems: () => Promise.resolve([]) },
  ];
  const seq = {
    getSelection: () => Promise.resolve({ getTrackItems: () => Promise.resolve([onV2, audioA1]) }),
    getVideoTrackCount: () => Promise.resolve(3),
    getVideoTrack: (v) => { reads.push(v); return Promise.resolve(tracks[v]); },
  };
  const results = await trackItems.getSelectedVideoClips(null, seq);
  assert.deepEqual(results.map((r) => [r.item, r.track]), [[onV2, 1]]);
  assert.deepEqual(reads.sort(), [0, 1]); // V3 never read; audio's index 0 read but it isn't on V1
});

test("getSelectedVideoClips returns [] for null sequence or empty selection", async () => {
  assert.deepEqual(await trackItems.getSelectedVideoClips(null, null), []);
  const seq = { getSelection: () => Promise.resolve(null), getVideoTrackCount: () => Promise.resolve(0), getAudioTrackCount: () => Promise.resolve(0) };
  assert.deepEqual(await trackItems.getSelectedVideoClips(null, seq), []);
});

// --- unwrapKeyframeValue -----------------------------------------------------------------

test("unwrapKeyframeValue strips the documented {value:{value:X}} double wrapper", () => {
  assert.deepEqual(components.unwrapKeyframeValue({ value: { value: [0.5, 0.5] } }), [0.5, 0.5]);
  assert.equal(components.unwrapKeyframeValue({ value: { value: 100 } }), 100);
});

test("unwrapKeyframeValue leaves an already-plain value alone", () => {
  assert.deepEqual(components.unwrapKeyframeValue({ value: [0.5, 0.5] }), [0.5, 0.5]);
});

test("unwrapKeyframeValue tolerates a missing keyframe", () => {
  assert.equal(components.unwrapKeyframeValue(null), null);
  assert.equal(components.unwrapKeyframeValue(undefined), null);
});

// --- isFixedComponent ----------------------------------------------------------------------

test("isFixedComponent matches Premiere's own fixed effects, case- and whitespace-insensitively", () => {
  assert.equal(components.isFixedComponent("Motion"), true);
  assert.equal(components.isFixedComponent(" opacity "), true);
  assert.equal(components.isFixedComponent("Time Remapping"), true);
  assert.equal(components.isFixedComponent("Gaussian Blur"), false);
  assert.equal(components.isFixedComponent(null), false);
  assert.equal(components.isFixedComponent(""), false);
});

// --- Hostile & Edge Case Tests -------------------------------------------------------------

test("getTrackClipItemsOrThrow returns [] for null or malformed track", async () => {
  assert.deepEqual(await trackItems.getTrackClipItemsOrThrow(null), []);
  assert.deepEqual(await trackItems.getTrackClipItemsOrThrow({}), []);
  assert.deepEqual(await trackItems.getTrackClipItemsOrThrow({ getTrackItems: "not a func" }), []);
});

test("getSelectedTrackItems gracefully handles seq.getSelection returning non-array items", async () => {
  const seq = {
    getSelection: () => Promise.resolve({ items: "invalid" }),
    getVideoTrackCount: () => Promise.resolve(0),
    getAudioTrackCount: () => Promise.resolve(0),
  };
  const items = await trackItems.getSelectedTrackItems(seq);
  assert.deepEqual(items, []);
});

test("getSelectedVideoClips excludes items matching ppro.AudioClipTrackItem instance", async () => {
  class MockAudioClip {}
  const audioItem = new MockAudioClip();
  audioItem.name = "Audio Stem";
  audioItem.getIsSelected = () => Promise.resolve(true);

  const videoItem = { name: "Footage", mediaType: "Video", getIsSelected: () => Promise.resolve(true) };

  const seq = {
    getSelection: () => Promise.resolve([audioItem, videoItem]),
    getVideoTrackCount: () => Promise.resolve(1),
    getVideoTrack: () => Promise.resolve({ getTrackItems: () => Promise.resolve([videoItem]) }),
  };

  const ppro = { AudioClipTrackItem: MockAudioClip };
  const result = await trackItems.getSelectedVideoClips(ppro, seq);
  assert.equal(result.length, 1);
  assert.equal(result[0].item, videoItem);
});

test("unwrapKeyframeValue handles nested nulls and primitives safely", () => {
  assert.equal(components.unwrapKeyframeValue({ value: null }), null);
  assert.equal(components.unwrapKeyframeValue({ value: { value: null } }), null);
  assert.equal(components.unwrapKeyframeValue({ value: 42 }), 42);
  assert.equal(components.unwrapKeyframeValue({ value: "text" }), "text");
});

