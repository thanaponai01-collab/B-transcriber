/* Stands in for the CutDeck panel in tests/test_cutdeck_panel_wire.py: the REAL core/rpc.js and
   features/driver.js, over Node's WebSocket to a real helper, with a fake Premiere behind the
   driver. Prints one JSON line per event so the Python side can follow along. */
const path = require("node:path");
const uxp = path.join(__dirname, "..", "..", "uxp", "cutdeck");
const { createRpc } = require(path.join(uxp, "core", "rpc.js"));
const { createDriver, keepRegistered } = require(path.join(uxp, "features", "driver.js"));
const { createController } = require(path.join(uxp, "features", "controller.js"));
const { VERSION } = require(path.join(uxp, "workflow.js"));
const fake = require(path.join(__dirname, "..", "fakes", "premiere.cjs"));

const [port, watchJob] = process.argv.slice(2);
const say = (what) => process.stdout.write(JSON.stringify(what) + "\n");

const { project, undoSteps } = fake.createProject();
const sequence = { guid: { toString: () => "seq" }, name: "Wire" };
project.getActiveSequence = async () => sequence;
const added = [];
const ppro = {
  Project: { getActiveProject: async () => project },
  TickTime: fake.TickTime,
  Markers: { getMarkers: async () => ({
    createAddMarkerAction: (name, type, start, duration, comments) =>
      fake.action(() => added.push({ name, start: start.ticks, comments })) }) },
};

const ctl = createController({ render: () => {} });
const driver = createDriver({ ppro, ctl });
let registration = null;
const driverRpc = createRpc({
  url: `ws://127.0.0.1:${port}`, attempts: 1,
  onCall: async (call) => {
    const result = await driver.handle(call);
    say({ ran: call.command, added, undoSteps });
    return result;
  },
  onClose: () => registration && registration.onClose(),
});
registration = keepRegistered({ rpc: driverRpc, version: VERSION, commands: driver.commands });

(async () => {
  await registration.start();
  say({ registered: true });
  const rpc = createRpc({ url: `ws://127.0.0.1:${port}`, attempts: 1 });
  // Two calls at once on one socket, answered by id.
  const [hello, missing] = await Promise.allSettled([
    rpc({ type: "hello", version: VERSION }), rpc({ type: "status", job_id: "0".repeat(32) })]);
  say({ hello: hello.value && hello.value.version, missing: missing.reason && missing.reason.message });
  const job = await rpc.watch(watchJob, (update) => say({ update: update.state, pct: update.progress && update.progress.pct }));
  say({ finished: job.state });
  process.exit(0);  // the open sockets would keep Node running
})().catch((error) => { say({ error: error.message }); process.exit(1); });
