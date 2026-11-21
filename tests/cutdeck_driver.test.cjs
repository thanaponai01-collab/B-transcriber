/* The panel as the Premiere driver (docs/arch-design-helper-v2.md move 3): the fixed commands
   the helper forwards from MCP agents and scripts, run against the shared Premiere fake. */
const test = require("node:test");
const assert = require("node:assert/strict");
const { createDriver, keepRegistered, COMMANDS } = require("../uxp/cutdeck/features/driver.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");
const fake = require("./fakes/premiere.cjs");

const TPF = "8475667200"; // 29.97 fps (PREMIERE_FACTS "Sequences": getTimebase)

function host({ endFrames = 900 } = {}) {
  const { project, undoSteps } = fake.createProject();
  const added = [];
  const sequence = {
    guid: { toString: () => "seq-guid" }, name: "Interview",
    getInPoint: async () => ({ seconds: 1, ticks: String(30n * BigInt(TPF)) }),
    getOutPoint: async () => ({ seconds: 10, ticks: String(300n * BigInt(TPF)) }),
    getEndTime: async () => ({ seconds: 30, ticks: String(BigInt(endFrames) * BigInt(TPF)) }),
    getTimebase: async () => TPF, getAudioTrackCount: async () => 2, getVideoTrackCount: async () => 1,
  };
  project.guid = { toString: () => "project-guid" };
  project.getActiveSequence = async () => sequence;
  const markers = {
    createAddMarkerAction: (name, type, start, duration, comments) =>
      fake.action(() => added.push({ name, type, start: start.ticks, duration: duration.ticks, comments })),
  };
  const ppro = {
    Project: { getActiveProject: async () => project },
    Markers: { getMarkers: async (owner) => { assert.equal(owner, sequence); return markers; } },
    TickTime: fake.TickTime,
  };
  return { ppro, project, undoSteps, added };
}

const controller = () => createController({ render: () => {} });

test("the driver offers exactly the helper's fixed commands", () => {
  assert.deepEqual(COMMANDS, [
    "read_sequence",
    "read_audio_range",
    "apply_cuts",
    "add_markers",
    "run_probe",
    "inspect_selection",
    "set_transform_field",
    "set_anchor",
    "align_clips",
    "distribute_clips",
    "export_sequence",
    "reload_panel",
    "build_sequence",
    "cut_copy",
    "create_sequence",
  ]);
});

test("export_sequence exports the ACTIVE sequence IMMEDIATELY with the given preset", async () => {
  const h = host();
  const calls = [];
  h.ppro.Constants = { ExportType: { IMMEDIATELY: "ExportType.IMMEDIATELY" } };
  h.ppro.EncoderManager = {
    getExportFileExtension: async (seq, preset) => { calls.push(["ext", seq.name, preset]); return "mp4"; },
    getManager: () => ({
      exportSequence: async (...args) => { calls.push(["export", args[0].name, ...args.slice(1)]); return true; },
    }),
  };
  const out = await createDriver({ ppro: h.ppro, ctl: controller() }).handle({
    command: "export_sequence", args: { output_file: "G:\\out\\reel.mp4", preset_file: "C:\\BAS4.epr" } });
  assert.deepEqual(calls, [
    ["ext", "Interview", "C:\\BAS4.epr"],
    ["export", "Interview", "ExportType.IMMEDIATELY", "G:\\out\\reel.mp4", "C:\\BAS4.epr"],
  ]);
  assert.equal(out.sequence_name, "Interview");
  assert.equal(out.resolved, true);
  assert.equal(out.extension, "mp4");
});

function ameHost({ fireQueued }) {
  const h = host();
  const log = [];
  const listeners = new Map();
  h.ppro.Constants = { ExportType: { IMMEDIATELY: "ExportType.IMMEDIATELY", QUEUE_TO_AME: "ExportType.QUEUE_TO_AME" } };
  const manager = { isAMEInstalled: true,
    exportSequence: async (seq, type) => {
      log.push(type);
      if (fireQueued) setTimeout(() => { log.push("queued"); listeners.get("onRenderQueue")?.(); }, 5);
      return true;
    },
    startBatchEncode: async () => { log.push("start"); return true; } };
  h.ppro.EncoderManager = { EVENT_RENDER_QUEUE: "onRenderQueue",
    getExportFileExtension: async () => "mp4", getManager: () => manager };
  h.ppro.EventManager = {
    addEventListener: (target, name, fn) => { assert.equal(target, manager); listeners.set(name, fn); },
    removeEventListener: (target, name, fn) => { if (listeners.get(name) === fn) listeners.delete(name); log.push("unlisten"); },
  };
  return { h, log, listeners };
}

test("export_sequence queue 'ame' starts the queue only after AME reports the job queued", async () => {
  const { h, log, listeners } = ameHost({ fireQueued: true });
  const out = await createDriver({ ppro: h.ppro, ctl: controller() }).handle({
    command: "export_sequence", args: { output_file: "G:\\out\\yt.mp4", preset_file: "C:\\BAS4.epr", queue: "ame" } });
  assert.deepEqual(log, ["ExportType.QUEUE_TO_AME", "queued", "start", "unlisten"]);
  assert.equal(out.queued_event, true);
  assert.equal(out.queue_started, true);
  assert.equal(listeners.size, 0);
});

test("export_sequence with start false only adds the job to AME's queue", async () => {
  const { h, log, listeners } = ameHost({ fireQueued: true });
  const out = await createDriver({ ppro: h.ppro, ctl: controller() }).handle({
    command: "export_sequence", args: { output_file: "G:\\out\\fb.mp4", preset_file: "C:\\BAS4.epr", queue: "ame", start: false } });
  assert.deepEqual(log, ["ExportType.QUEUE_TO_AME"]);
  assert.equal(out.queue_started, null);
  assert.equal(listeners.size, 0);
});

test("export_sequence still presses Start when AME never reports the job queued", async () => {
  const { h, log } = ameHost({ fireQueued: false });
  const out = await createDriver({ ppro: h.ppro, ctl: controller(), queueWaitMs: 20 }).handle({
    command: "export_sequence", args: { output_file: "G:\\out\\yt.mp4", preset_file: "C:\\BAS4.epr", queue: "ame" } });
  assert.deepEqual(log, ["ExportType.QUEUE_TO_AME", "start", "unlisten"]);
  assert.equal(out.queued_event, false);
});

test("export_sequence queues without starting on a Premiere that lacks startBatchEncode", async () => {
  const h = host();
  h.ppro.Constants = { ExportType: { IMMEDIATELY: "ExportType.IMMEDIATELY", QUEUE_TO_AME: "ExportType.QUEUE_TO_AME" } };
  h.ppro.EncoderManager = {
    getExportFileExtension: async () => "mp4",
    getManager: () => ({ isAMEInstalled: true, exportSequence: async () => true }),
  };
  const out = await createDriver({ ppro: h.ppro, ctl: controller() }).handle({
    command: "export_sequence", args: { output_file: "G:\\out\\yt.mp4", preset_file: "C:\\BAS4.epr", queue: "ame" } });
  assert.equal(out.queue_started, null);
});

test("export_sequence by name takes the one same-named sequence with content", async () => {
  const { h, log } = ameHost({ fireQueued: true });
  const seq = (name, end, id) => ({ name, guid: { toString: () => id },
    getEndTime: async () => ({ seconds: end }), getInPoint: async () => ({ seconds: 0 }),
    getOutPoint: async () => ({ seconds: Math.min(end, 1095.8) }) });
  const sequences = [seq("1 YOUTUBE D1", 0, "empty-template"), seq("1 YOUTUBE D1", 8438.6, "edited"), seq("2 FACEBOOK D1", 179.96, "fb")];
  h.project.getSequences = async () => sequences;
  const exported = [];
  const manager = h.ppro.EncoderManager.getManager();
  const original = manager.exportSequence;
  manager.exportSequence = async (s, ...rest) => { exported.push(String(s.guid)); return original(s, ...rest); };
  const driver = createDriver({ ppro: h.ppro, ctl: controller() });
  const out = await driver.handle({ command: "export_sequence", args: {
    output_file: "G:\\out\\yt.mp4", preset_file: "C:\\BAS4.epr", queue: "ame", sequence_name: "1 YOUTUBE D1" } });
  assert.deepEqual(exported, ["edited"]);
  assert.equal(out.out_seconds, 1095.8);
  assert.equal(out.end_seconds, 8438.6);
  sequences.push(seq("2 FACEBOOK D1", 179.96, "fb-copy"));
  await assert.rejects(driver.handle({ command: "export_sequence", args: {
    output_file: "G:\\out\\fb.mp4", preset_file: "C:\\BAS4.epr", queue: "ame", sequence_name: "2 FACEBOOK D1" } }),
  /Found 2 sequences named "2 FACEBOOK D1" with content/);
  await assert.rejects(driver.handle({ command: "export_sequence", args: {
    output_file: "G:\\out\\x.mp4", preset_file: "C:\\BAS4.epr", sequence_name: "missing" } }), /Found 0 sequences/);
  assert.ok(log.length > 0);
});

test("export_sequence refuses an output name the preset would not write", async () => {
  const h = host();
  let exported = false;
  h.ppro.Constants = { ExportType: { IMMEDIATELY: "ExportType.IMMEDIATELY" } };
  h.ppro.EncoderManager = {
    getExportFileExtension: async () => ".mp4",
    getManager: () => ({ exportSequence: async () => { exported = true; return true; } }),
  };
  await assert.rejects(createDriver({ ppro: h.ppro, ctl: controller() }).handle({
    command: "export_sequence", args: { output_file: "G:\\out\\reel.mov", preset_file: "C:\\BAS4.epr" } }),
  /must end in \.mp4/);
  assert.equal(exported, false);
});

test("transform driver commands reject when no clip is selected", async () => {
  const h = host();
  const ctl = controller();
  const driver = createDriver({ ppro: h.ppro, ctl });
  await assert.rejects(
    driver.handle({ command: "set_transform_field", args: { field: "scale", value: 120 } }),
    /Select a clip/
  );
  await assert.rejects(
    driver.handle({ command: "set_anchor", args: { target: "center" } }),
    /Select a clip/
  );
  await assert.rejects(
    driver.handle({ command: "align_clips", args: { edge: "left", to: "frame" } }),
    /Select a clip/
  );
  await assert.rejects(
    driver.handle({ command: "distribute_clips", args: { kind: "h-centers", to: "frame" } }),
    /Select a clip/
  );
});

test("run_probe runs timing probe against fake host", async () => {
  const h = host();
  const ctl = controller();
  const out = await createDriver({ ppro: h.ppro, ctl }).handle({ command: "run_probe", args: { probe: "timing" } });
  assert.equal(out.probe, "timing");
  assert.ok(out.report);
  assert.equal(ctl.state.busy, false);
});

test("run_probe rejects unknown probe name", async () => {
  const h = host();
  const ctl = controller();
  await assert.rejects(
    createDriver({ ppro: h.ppro, ctl }).handle({ command: "run_probe", args: { probe: "nonexistent" } }),
    /Unknown probe/
  );
});

test("inspect_selection inspects selection on active sequence", async () => {
  const h = host();
  const ctl = controller();
  const out = await createDriver({ ppro: h.ppro, ctl }).handle({ command: "inspect_selection" });
  assert.equal(out.sequence_name, "Interview");
  assert.equal(out.selected_count, 0);
  assert.deepEqual(out.items, []);
  assert.equal(ctl.state.busy, false);
});

test("read_sequence reports the active sequence", async () => {
  const h = host();
  const out = await createDriver({ ppro: h.ppro, ctl: controller() }).handle({ command: "read_sequence" });
  assert.equal(out.name, "Interview");
  assert.equal(out.sequence_id, "seq-guid");
  assert.equal(out.ticks_per_frame, TPF);
  assert.equal(out.audio_track_count, 2);
  assert.equal(out.video_track_count, 1);
  assert.equal(out.in_seconds, 1);
});

test("add_markers adds every marker in one transaction, created inside it", async () => {
  const h = host();
  const ctl = controller();
  const out = await createDriver({ ppro: h.ppro, ctl }).handle({ command: "add_markers", args: { markers: [
    { start_ticks: "254016000000", duration_ticks: "0", name: "cut 1", comment: "removed 1.2 s" },
    { start_ticks: "508032000000", duration_ticks: "127008000000", name: "cut 2", comment: "" },
  ] } });
  assert.deepEqual(out, { added: 2, undo_steps: 1 });
  assert.equal(h.undoSteps.length, 1);
  assert.deepEqual(h.added[0], { name: "cut 1", type: "Comment", start: "254016000000", duration: "0", comments: "removed 1.2 s" });
  assert.equal(h.added[1].duration, "127008000000");
  assert.equal(ctl.state.busy, false);
});

test("a busy panel refuses a command instead of queueing behind the user", async () => {
  const h = host();
  const ctl = controller();
  ctl.state.busy = true;
  await assert.rejects(createDriver({ ppro: h.ppro, ctl }).handle({ command: "add_markers",
    args: { markers: [{ start_ticks: "0", duration_ticks: "0", name: "", comment: "" }] } }), /busy/);
  assert.equal(h.undoSteps.length, 0);
  assert.equal(ctl.state.busy, true, "the user's own action keeps the panel");
});

test("apply_cuts refuses a sequence other than the one the job analysed", async () => {
  const h = host();
  const ctl = controller();
  await assert.rejects(createDriver({ ppro: h.ppro, ctl }).handle({ command: "apply_cuts", args: {
    cuts: { cuts_frames: [[10, 20]] }, sequence_id: "other-guid", sequence_name: "Podcast", result_name: "x" } }),
  /Open "Podcast"/);
  assert.equal(h.undoSteps.length, 0);
  assert.equal(ctl.state.status.level, "error");
});

test("apply_cuts for a retired file job refuses missing source identity", async () => {
  const h = host({ endFrames: 900 });
  await assert.rejects(createDriver({ ppro: h.ppro, ctl: controller() }).handle({ command: "apply_cuts", args: {
    cuts: { cuts_frames: [[10, 20]], sequence_duration_frames: 5000 }, result_name: "x" } }),
  /no source sequence identity/);
  assert.equal(h.undoSteps.length, 0);
});

test("an unknown command is refused", async () => {
  await assert.rejects(createDriver({ ppro: host().ppro, ctl: controller() }).handle({ command: "eval" }), /no command eval/);
});

test("keepRegistered registers, and registers again after a drop, backing off while it fails", async () => {
  const sent = [];
  let helperUp = true;
  const timers = [];
  const rpc = async (req) => {
    sent.push(req.type);
    if (!helperUp) throw new Error("Cannot reach CutDeck helper");
    return { ok: true };
  };
  const reg = keepRegistered({ rpc, version: "v", commands: COMMANDS, setTimer: (fn, ms) => timers.push({ fn, ms }) });
  await reg.start();
  assert.deepEqual(sent, ["hello", "register_driver"]);
  helperUp = false;
  reg.onClose();                          // helper restarted
  reg.onClose();                          // a second drop while waiting schedules nothing more
  assert.deepEqual(timers.map((t) => t.ms), [5000]);
  await timers.shift().fn();              // helper not back yet
  assert.deepEqual(timers.map((t) => t.ms), [10000]);
  helperUp = true;
  await timers.shift().fn();
  assert.deepEqual(sent.slice(-2), ["hello", "register_driver"]);
  assert.equal(timers.length, 0);
});
test("keepRegistered stop clears pending timers and halts further registration", async () => {
  const sent = [];
  const cleared = [];
  const timers = [];
  const rpc = async (req) => { sent.push(req.type); return { ok: true }; };
  const reg = keepRegistered({
    rpc,
    version: "v",
    commands: COMMANDS,
    setTimer: (fn, ms) => {
      const id = timers.length + 1;
      timers.push({ id, fn, ms });
      return id;
    },
    clearTimer: (id) => cleared.push(id),
  });
  reg.onClose();
  assert.equal(timers.length, 1);
  reg.stop();
  assert.deepEqual(cleared, [1]);
  reg.onClose();
  assert.equal(timers.length, 1);
});

test("inspect_selection reports no graphic layers for a plain clip", async () => {
  const h = host();
  const item = { getComponentChain: async () => ({ getComponentCount: () => 0 }) };
  const seq = await (await h.ppro.Project.getActiveProject()).getActiveSequence();
  seq.getSelection = async () => ({ getTrackItems: async () => [item] });
  const out = await createDriver({ ppro: h.ppro, ctl: controller() }).handle({ command: "inspect_selection" });
  assert.equal(out.selected_count, 1);
  assert.equal(out.items[0].graphic, null);
});

test("the driver measures Graphics with the Transform panel's measure", async () => {
  const src = require("node:fs").readFileSync(require.resolve("../uxp/cutdeck/main.js"), "utf8");
  assert.match(src, /createDriver\(\{[^}]*measure: align\.measure/);
  const { createAlignFeature } = require("../uxp/cutdeck/features/align.js");
  const withHelper = createAlignFeature({ ppro: {}, ctl: { state: {}, render() {} }, uxp: {}, rpc: () => {} });
  assert.equal(typeof withHelper.measure, "function");
});
