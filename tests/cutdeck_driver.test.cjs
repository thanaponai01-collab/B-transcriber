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
    "apply_cuts",
    "add_markers",
    "run_probe",
    "inspect_selection",
    "set_transform_field",
    "set_anchor",
    "align_clips",
    "distribute_clips",
  ]);
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

test("apply_cuts for an XML-file job refuses a sequence of another length", async () => {
  const h = host({ endFrames: 900 });
  await assert.rejects(createDriver({ ppro: h.ppro, ctl: controller() }).handle({ command: "apply_cuts", args: {
    cuts: { cuts_frames: [[10, 20]], sequence_duration_frames: 5000 }, result_name: "x" } }),
  /900 frames; the cut list was made for 5000/);
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
