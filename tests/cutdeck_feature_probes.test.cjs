const test = require("node:test");
const assert = require("node:assert/strict");
const { createProbesFeature } = require("../uxp/cutdeck/features/probes.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");

test("probes: onProbe('copystatus') copies text to clipboard and updates status", async () => {
  const ctl = createController({
    render: () => {},
    initialState: { status: { text: "Report 123", level: "ready" } },
  });

  let copied = null;
  const fakeClipboard = {
    writeText: async (t) => { copied = t; },
  };

  const probes = createProbesFeature({
    ppro: {},
    ctl,
    clipboard: fakeClipboard,
  });

  await probes.onProbe("copystatus");

  assert.equal(copied, "Report 123");
  assert.equal(ctl.state.status.level, "ready");
  assert.match(ctl.state.status.text, /Report 123\n\n--- copied to clipboard ---/);
});

test("probes: onProbe('copystatus') fails gracefully when no clipboard API exists", async () => {
  const ctl = createController({
    render: () => {},
    initialState: { status: { text: "Report 123", level: "ready" } },
  });

  const probes = createProbesFeature({
    ppro: {},
    ctl,
    clipboard: null,
    uxp: null,
  });

  await probes.onProbe("copystatus");

  assert.equal(ctl.state.status.level, "error");
  assert.match(ctl.state.status.text, /No clipboard API/);
});

test("probes: onProbe('socket') runs probe and updates status", async () => {
  const ctl = createController({ render: () => {} });
  const probeMod = require("../uxp/cutdeck/probe.js");
  const origRun = probeMod.run;

  probeMod.run = async () => ({
    report: { results: [{ url: "ws://127.0.0.1", outcome: "connected" }] },
    written: true,
  });

  try {
    const probes = createProbesFeature({ ppro: {}, ctl });
    await probes.onProbe("socket");

    assert.equal(ctl.state.status.level, "ready");
    assert.match(ctl.state.status.text, /Socket permission probe/);
    assert.match(ctl.state.status.text, /ws:\/\/127\.0\.0\.1 -> connected/);
  } finally {
    probeMod.run = origRun;
  }
});
