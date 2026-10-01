/* Stands in for the CutDeck panel in tests/test_cutdeck_live_premiere.py's offline mode: the
   REAL core/rpc.js and features/driver.js over Node's WebSocket to a real helper, with the
   shared Premiere fake behind the driver and nothing selected. Prints "ready" once registered. */
const path = require("node:path");
const uxp = path.join(__dirname, "..", "..", "uxp", "cutdeck");
const { createRpc } = require(path.join(uxp, "core", "rpc.js"));
const { createDriver, keepRegistered } = require(path.join(uxp, "features", "driver.js"));
const { createController } = require(path.join(uxp, "features", "controller.js"));
const { VERSION } = require(path.join(uxp, "workflow.js"));
const fake = require(path.join(__dirname, "..", "fakes", "premiere.cjs"));

const TPF = "8475667200"; // 29.97 fps
const { project } = fake.createProject();
const sequence = {
  guid: { toString: () => "seq-guid" }, name: "Interview",
  getInPoint: async () => ({ seconds: 1, ticks: String(30n * BigInt(TPF)) }),
  getOutPoint: async () => ({ seconds: 10, ticks: String(300n * BigInt(TPF)) }),
  getEndTime: async () => ({ seconds: 30, ticks: String(900n * BigInt(TPF)) }),
  getTimebase: async () => TPF, getAudioTrackCount: async () => 2, getVideoTrackCount: async () => 1,
};
project.guid = { toString: () => "project-guid" };
project.getActiveSequence = async () => sequence;
const ppro = {
  Project: { getActiveProject: async () => project },
  Markers: { getMarkers: async () => ({ createAddMarkerAction: () => fake.action(() => {}) }) },
  TickTime: fake.TickTime,
};

const driver = createDriver({ ppro, ctl: createController({ render: () => {} }) });
let registration = null;
const rpc = createRpc({
  url: `ws://127.0.0.1:${process.argv[2]}`, attempts: 1,
  onCall: (call) => driver.handle(call),
  onClose: () => registration && registration.onClose(),
});
registration = keepRegistered({ rpc, version: VERSION, commands: driver.commands });
registration.start().then(() => process.stdout.write("ready\n"))
  .catch((e) => { process.stderr.write(String(e && e.message)); process.exit(1); });
