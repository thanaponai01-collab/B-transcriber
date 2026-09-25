const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { createProbesFeature, PROBES, runProbe } = require("../uxp/cutdeck/features/probes.js");
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

test("every data-probe in index.html has a PROBES entry and vice versa", () => {
  const htmlPath = path.join(__dirname, "..", "uxp", "cutdeck", "index.html");
  const html = fs.readFileSync(htmlPath, "utf8");

  const htmlDataProbes = [...html.matchAll(/data-probe="([^"]+)"/g)].map((m) => m[1]);
  const probeIds = PROBES.map((p) => p.id);

  assert.ok(htmlDataProbes.length > 0, "no data-probe attributes found in index.html");
  assert.deepEqual(
    new Set(htmlDataProbes),
    new Set(probeIds),
    "Mismatch between data-probe attributes in index.html and PROBES registry"
  );
  assert.equal(htmlDataProbes.length, probeIds.length, "Duplicate data-probe or PROBES entries");
});

test("every non-special probe in PROBES satisfies the registry contract", () => {
  for (const p of PROBES) {
    if (p.special) continue;
    assert.ok(typeof p.id === "string" && p.id.length > 0, `probe missing valid id: ${JSON.stringify(p)}`);
    assert.ok(typeof p.startText === "string" && p.startText.length > 0, `probe ${p.id} missing startText`);
    assert.equal(typeof p.run, "function", `probe ${p.id} run is not a function`);
    assert.equal(typeof p.format, "function", `probe ${p.id} format is not a function`);
  }
});

test("generic probe dispatch sets startText, runs probe, logs json, and formats report into ready status", async () => {
  const ctl = createController({ render: () => {} });
  const statuses = [];
  ctl.setStatus = (text, level) => {
    statuses.push({ text, level });
    ctl.state.status = { text, level };
  };

  const logs = [];
  const origLog = console.log;
  console.log = (...args) => logs.push(args);

  const fakePpro = { isFake: true };
  const timingEntry = PROBES.find((p) => p.id === "timing");
  const origRun = timingEntry.run;
  const origFormat = timingEntry.format;
  timingEntry.run = async (ppro) => ({ fakeSuccess: true, receivedPpro: ppro.isFake });
  timingEntry.format = (r) => `Formatted: fake=${r.fakeSuccess}`;

  try {
    const probes = createProbesFeature({ ppro: fakePpro, ctl });
    await probes.onProbe("timing");

    assert.equal(statuses.length, 2);
    assert.equal(statuses[0].text, timingEntry.startText);
    assert.equal(statuses[0].level, "busy");
    assert.equal(statuses[1].text, "Formatted: fake=true");
    assert.equal(statuses[1].level, "ready");
    assert.ok(logs.some((l) => l[0] === "CutDeck capability probe"));
  } finally {
    console.log = origLog;
    timingEntry.run = origRun;
    timingEntry.format = origFormat;
  }
});

test("probes: unknown probe throws error caught by controller", async () => {
  const ctl = createController({ render: () => {} });
  const probes = createProbesFeature({ ppro: {}, ctl });

  await probes.onProbe("nonexistent");
  assert.equal(ctl.state.status.level, "error");
  assert.match(ctl.state.status.text, /Unknown probe: nonexistent/);
});

test("features/align.js reuses transform probe from PROBES and runProbe", async () => {
  const alignMod = require("../uxp/cutdeck/features/align.js");
  const ctl = createController({ render: () => {}, initialState: { transform: null } });

  const statuses = [];
  ctl.setStatus = (text, level) => {
    statuses.push({ text, level });
    ctl.state.status = { text, level };
  };

  const fakePpro = {
    Project: {
      getActiveProject: async () => ({
        getActiveSequence: async () => null,
      }),
    },
  };

  const align = alignMod.createAlignFeature({ ppro: fakePpro, ctl });
  await align.onProbe();

  assert.ok(statuses.length >= 2);
  const transformEntry = PROBES.find((p) => p.id === "transform");
  assert.equal(statuses[0].text, transformEntry.startText);
  assert.equal(statuses[0].level, "busy");
  // "info", not "ready": the Transform panel's status bar is quiet at "ready", and a report the
  // user asked for must show.
  assert.equal(statuses[statuses.length - 1].level, "info");
});

test("core/panel.js binds [data-probe] buttons to onProbe and closes overflow menu", () => {
  delete require.cache[require.resolve("../uxp/cutdeck/core/panel.js")];
  const panel = require("../uxp/cutdeck/core/panel.js");
  const classes = new Set(["open"]);

  const overflowMenu = {
    classList: {
      contains: (c) => classes.has(c),
      remove: (c) => classes.delete(c),
      add: (c) => classes.add(c),
    },
  };

  const mockButtons = ["timing", "copystatus", "transform"].map((id) => {
    let handler;
    const el = {
      getAttribute: (attr) => (attr === "data-probe" ? id : null),
      addEventListener: (evt, fn) => { if (evt === "click") handler = fn; },
      click: () => handler && handler(),
    };
    return { id, el };
  });

  const origDoc = global.document;
  global.document = {
    getElementById: (id) => (id === "overflow-menu" ? overflowMenu : null),
    querySelectorAll: (sel) => (sel === "[data-probe]" ? mockButtons.map((b) => b.el) : []),
    addEventListener: () => {},
  };

  try {
    const probeCalls = [];
    panel.bind({
      onProbe: (id) => probeCalls.push(id),
    });

    for (const b of mockButtons) {
      classes.add("open");
      b.el.click();
      assert.equal(classes.has("open"), false, `overflow menu did not close on probe ${b.id}`);
    }

    assert.deepEqual(probeCalls, ["timing", "copystatus", "transform"]);
  } finally {
    global.document = origDoc;
  }
});

