/* The mute-state and text-canvas probes: read-only, and their verdicts follow the readings. */
const test = require("node:test");
const assert = require("node:assert/strict");
const probe = require("../uxp/cutdeck/layoutProbe.js");
const transformParams = require("../uxp/cutdeck/transform/params.js");

const track = (muted) => ({ isMuted: async () => muted, setMute() { throw new Error("probe must not write"); } });
const seqWith = (extra = {}) => ({
  getVideoTrackCount: async () => 2, getVideoTrack: async (i) => track(i === 1),
  getAudioTrackCount: async () => 1, getAudioTrack: async () => track(false),
  ...extra,
});
const pproFor = (seq) => ({ Project: { getActiveProject: async () => ({ getActiveSequence: async () => seq }) } });

test("mute probe reports each track and counts the muted ones without writing", async () => {
  const report = await probe.probeMuteState(pproFor(seqWith()));
  assert.equal(report.total, 3);
  assert.equal(report.mutedCount, 1);
  assert.deepEqual(report.tracks.filter((t) => t.muted).map((t) => `${t.kind}${t.index}`), ["video1"]);
  assert.match(probe.formatMuteStateReport(report), /V2: MUTED/);
});

test("mute probe warns when nothing reads muted", async () => {
  const seq = seqWith({ getVideoTrack: async () => track(false) });
  const text = probe.formatMuteStateReport(await probe.probeMuteState(pproFor(seq)));
  assert.match(text, /isMuted\(\) is NOT reliable/);
});

test("mute probe treats a failing isMuted as a finding, not a throw", async () => {
  const bad = { isMuted: async () => { throw new Error("boom"); } };
  const report = await probe.probeMuteState(pproFor(seqWith({ getVideoTrack: async () => bad })));
  assert.equal(report.complete, true);
  assert.match(probe.formatMuteStateReport(report), /could not read \(boom\)/);
});

test("mute probe says so when no project is open", async () => {
  const report = await probe.probeMuteState({ Project: { getActiveProject: async () => null } });
  assert.equal(report.complete, false);
  assert.match(probe.formatMuteStateReport(report), /no active project/);
});

function patched(overrides, fn) {
  const saved = {};
  for (const k of Object.keys(overrides)) { saved[k] = transformParams[k]; transformParams[k] = overrides[k]; }
  return fn().finally(() => Object.assign(transformParams, saved));
}
const selected = (items) => ({ getSelection: async () => ({ getTrackItems: async () => items }) });
const graphicParams = (anchor) => ({
  isGraphic: async () => true,
  readGraphicLayers: async () => ({ texts: [{ position: { value: { x: 0.25, y: 0.5 } } }] }),
  readSequenceFrameSize: async () => ({ width: 1920, height: 1080 }),
  readSourceFrameSize: async () => anchor,
  readAnchorFrameSize: async () => anchor || { width: 1920, height: 1080 },
});

test("text probe: same sizes means the two routes agree", async () => {
  const out = await patched(graphicParams(null), () => probe.probeTextCanvas(pproFor(selected([{}]))));
  assert.equal(out.routesDiffer, false);
  assert.deepEqual(out.positions[0].inSequencePx, { x: 480, y: 540 });
  assert.match(probe.formatTextCanvasReport(out), /same size/);
});

test("text probe: a project item of another size makes the routes differ", async () => {
  const out = await patched(graphicParams({ width: 1280, height: 720 }), () => probe.probeTextCanvas(pproFor(selected([{}]))));
  assert.equal(out.routesDiffer, true);
  assert.deepEqual(out.positions[0].inCanvasPx, { x: 320, y: 360 });
  assert.match(probe.formatTextCanvasReport(out), /DIFFERENT sizes/);
});

test("text probe refuses anything but exactly one selected Graphic", async () => {
  const none = await probe.probeTextCanvas(pproFor(selected([])));
  assert.match(probe.formatTextCanvasReport(none), /select exactly one/);
  const notGraphic = await patched({ isGraphic: async () => false }, () => probe.probeTextCanvas(pproFor(selected([{}]))));
  assert.match(probe.formatTextCanvasReport(notGraphic), /not a Graphic/);
});

const caption = (start, end) => ({ getStartTime: async () => ({ ticks: String(start) }), getEndTime: async () => ({ ticks: String(end) }) });
const captionSeq = (tracks) => ({
  name: "Ep 1",
  getTimebase: async () => "10160640000",
  getCaptionTrackCount: async () => tracks.length,
  getCaptionTrack: async (i) => tracks[i],
});
const TPF = 10160640000n; // 25 fps

test("caption probe reads every caption's ticks in time order with the sequence timebase", async () => {
  const track = { getTrackItems: async () => [caption(TPF * 50n, TPF * 75n), null, caption(0n, TPF * 50n)] };
  const report = await probe.probeCaptionTiming(pproFor(captionSeq([track])));
  assert.equal(report.complete, true);
  assert.equal(report.ticks_per_frame, "10160640000");
  assert.deepEqual(report.tracks[0].items.map((i) => i.start_ticks), ["0", String(TPF * 50n)]);
  assert.match(probe.formatCaptionTimingReport(report), /C1: 2 captions, frames 0-75/);
});

test("caption probe reports missing timing members instead of guessing", async () => {
  const track = { getTrackItems: async () => [{ getName: async () => "x" }] };
  const report = await probe.probeCaptionTiming(pproFor(captionSeq([track])));
  assert.match(report.tracks[0].error, /no getStartTime/);
});

test("caption probe says so when there is no caption track", async () => {
  const report = await probe.probeCaptionTiming(pproFor(captionSeq([])));
  assert.match(probe.formatCaptionTimingReport(report), /no caption track/);
});
