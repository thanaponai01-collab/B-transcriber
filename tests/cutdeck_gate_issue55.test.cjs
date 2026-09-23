const test = require("node:test");
const assert = require("node:assert/strict");
const { createProbesFeature, PROBES, runProbe } = require("../uxp/cutdeck/features/probes.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");
const panel = require("../uxp/cutdeck/core/panel.js");

// --- Correctness Gate: Issue #55 Attack Suite ---

test("ATTACK [probes]: probe.run rejecting recovers controller to error status and unsets busy", async () => {
  const ctl = createController({ render: () => {} });
  const timingEntry = PROBES.find((p) => p.id === "timing");
  const origRun = timingEntry.run;
  timingEntry.run = async () => {
    throw new Error("Premiere host bridge failed");
  };

  const origError = console.error;
  console.error = () => {};

  try {
    const probes = createProbesFeature({ ppro: {}, ctl });
    await probes.onProbe("timing");

    assert.equal(ctl.state.busy, false, "busy flag must be reset to false after probe failure");
    assert.equal(ctl.state.status.level, "error");
    assert.equal(ctl.state.status.text, "Premiere host bridge failed");
  } finally {
    console.error = origError;
    timingEntry.run = origRun;
  }
});

test("ATTACK [probes]: probe.format throwing recovers controller to error status and unsets busy", async () => {
  const ctl = createController({ render: () => {} });
  const timingEntry = PROBES.find((p) => p.id === "timing");
  const origRun = timingEntry.run;
  const origFormat = timingEntry.format;

  timingEntry.run = async () => ({ unexpectedShape: true });
  timingEntry.format = () => {
    throw new Error("Malformed report: missing required fields");
  };

  const origError = console.error;
  console.error = () => {};

  try {
    const probes = createProbesFeature({ ppro: {}, ctl });
    await probes.onProbe("timing");

    assert.equal(ctl.state.busy, false, "busy flag must be reset to false after format failure");
    assert.equal(ctl.state.status.level, "error");
    assert.equal(ctl.state.status.text, "Malformed report: missing required fields");
  } finally {
    console.error = origError;
    timingEntry.run = origRun;
    timingEntry.format = origFormat;
  }
});

test("ATTACK [probes]: hostile probe names (null, undefined, empty, number) throw cleanly", async () => {
  const ctl = createController({ render: () => {} });
  const probes = createProbesFeature({ ppro: {}, ctl });
  const hostileNames = [null, undefined, "", 0, 42, {}, []];

  for (const name of hostileNames) {
    await probes.onProbe(name);
    assert.equal(ctl.state.busy, false);
    assert.equal(ctl.state.status.level, "error");
    assert.match(ctl.state.status.text, /Unknown probe:/);
  }
});

test("ATTACK [probes]: concurrent burst of 5 probe calls drops secondary calls without race", async () => {
  const ctl = createController({ render: () => {} });
  let timingRan = 0;
  let motionRan = 0;
  let resolveProbe;

  const timingEntry = PROBES.find((p) => p.id === "timing");
  const motionEntry = PROBES.find((p) => p.id === "motion");
  const origTimingRun = timingEntry.run;
  const origTimingFormat = timingEntry.format;
  const origMotionRun = motionEntry.run;

  timingEntry.run = () => {
    timingRan++;
    return new Promise((resolve) => {
      resolveProbe = resolve;
    });
  };
  timingEntry.format = () => "Timing Complete";
  motionEntry.run = async () => {
    motionRan++;
    return {};
  };

  try {
    const probes = createProbesFeature({ ppro: {}, ctl });

    // Fire 5 concurrent requests
    const p1 = probes.onProbe("timing");
    const p2 = probes.onProbe("timing");
    const p3 = probes.onProbe("motion");
    const p4 = probes.onProbe("timing");
    const p5 = probes.onProbe("motion");

    assert.equal(ctl.state.busy, true);
    assert.equal(timingRan, 1, "Only first call should have executed");
    assert.equal(motionRan, 0, "Concurrent calls must be dropped by act");

    resolveProbe({});
    await Promise.all([p1, p2, p3, p4, p5]);

    assert.equal(ctl.state.busy, false);
    assert.equal(timingRan, 1);
    assert.equal(motionRan, 0);
    assert.equal(ctl.state.status.text, "Timing Complete");
  } finally {
    timingEntry.run = origTimingRun;
    timingEntry.format = origTimingFormat;
    motionEntry.run = origMotionRun;
  }
});

test("ATTACK [probes]: syncmoves probe logReplacer correctly handles BigInt without throwing", async () => {
  const ctl = createController({ render: () => {} });
  const syncmovesEntry = PROBES.find((p) => p.id === "syncmoves");
  const origRun = syncmovesEntry.run;
  const origFormat = syncmovesEntry.format;

  syncmovesEntry.run = async () => ({
    startTicks: 254016000000n,
    duration: 1234567890123456789n,
    nested: { mark: 100n },
  });
  syncmovesEntry.format = () => "SyncMoves OK";

  const loggedMessages = [];
  const origLog = console.log;
  console.log = (...args) => loggedMessages.push(args);

  try {
    const probes = createProbesFeature({ ppro: {}, ctl });
    await probes.onProbe("syncmoves");

    assert.equal(ctl.state.status.level, "ready");
    assert.equal(ctl.state.status.text, "SyncMoves OK");

    const jsonLog = loggedMessages.find((m) => m[0] === "CutDeck sync moves probe");
    assert.ok(jsonLog, "expected sync moves json log");
    assert.match(jsonLog[1], /"startTicks": "254016000000"/);
    assert.match(jsonLog[1], /"duration": "1234567890123456789"/);
  } finally {
    console.log = origLog;
    syncmovesEntry.run = origRun;
    syncmovesEntry.format = origFormat;
  }
});

test("ATTACK [probes]: copystatus uses uxp.clipboard when navigator.clipboard is unavailable", async () => {
  const ctl = createController({
    render: () => {},
    initialState: { status: { text: "Diagnostic Findings #1", level: "ready" } },
  });

  let uxpCopied = null;
  const mockUxp = {
    clipboard: {
      copyText: (text) => {
        uxpCopied = text;
      },
    },
  };

  const probes = createProbesFeature({
    ppro: {},
    ctl,
    clipboard: null, // navigator.clipboard unavailable
    uxp: mockUxp,
  });

  await probes.onProbe("copystatus");

  assert.equal(uxpCopied, "Diagnostic Findings #1");
  assert.equal(ctl.state.status.level, "ready");
  assert.match(ctl.state.status.text, /Diagnostic Findings #1\n\n--- copied to clipboard ---/);
});

test("ATTACK [panel]: element with empty data-probe does not trigger onProbe", () => {
  let probeCalled = null;
  const classes = new Set(["open"]);
  const overflowMenu = {
    classList: {
      remove: (c) => classes.delete(c),
    },
  };

  let handler;
  const el = {
    getAttribute: (attr) => (attr === "data-probe" ? "" : null),
    dataset: { probe: "" },
    addEventListener: (evt, fn) => { if (evt === "click") handler = fn; },
  };

  const origDoc = global.document;
  global.document = {
    getElementById: (id) => (id === "overflow-menu" ? overflowMenu : null),
    querySelectorAll: (sel) => (sel === "[data-probe]" ? [el] : []),
    addEventListener: () => {},
  };

  try {
    panel.bind({
      onProbe: (id) => { probeCalled = id; },
    });

    handler();
    assert.equal(probeCalled, null, "empty data-probe must not trigger onProbe");
    assert.equal(classes.has("open"), false, "overflow menu should still close");
  } finally {
    global.document = origDoc;
  }
});
