/* Phase 0 of the Transform & Align plan (docs/research/cutdeck-transform-panel-plan.md).

   The probe's whole job is to survive a hostile, undocumented host and still report something
   useful, so that is what these tests exercise: every call it makes is allowed to be absent,
   to throw, or to return the wrong shape, and the probe must record that as a finding rather
   than throw. A probe that dies on the first surprise tells you less than the build it was
   probing — the rule capabilityProbe.js's header already states.

   No Premiere here. `probeTransformParams(ppro)` takes its host as an argument precisely so
   it can be driven by a fake, which is what makes the logic provable off-host. What CANNOT be
   proven here is that the real Premiere returns these shapes — that is the point of running
   the probe, and is deferred to the host. */
const test = require("node:test");
const assert = require("node:assert/strict");

const capability = require("../uxp/cutdeck/capabilityProbe.js");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(root, p), "utf8");

// --- fake host ----------------------------------------------------------------------------
// Mirrors the shapes Adobe's declarations promise: getComponentCount/getParamCount are sync,
// the getters return Promises, and a Keyframe's value is the documented DOUBLE wrapper
// `{ value: <actual> }` (premierepro.d.ts: `Keyframe.value: { value: ... }`).

function param(name, inner, opts = {}) {
  return {
    displayName: name,
    isTimeVarying: () => (opts.timeVarying === undefined ? false : opts.timeVarying),
    getStartValue: opts.throws
      ? () => Promise.reject(new Error(opts.throws))
      : () => Promise.resolve({ value: { value: inner } }),
  };
}

function component(displayName, matchName, params) {
  return {
    getDisplayName: () => Promise.resolve(displayName),
    getMatchName: () => Promise.resolve(matchName),
    getParamCount: () => params.length,
    getParam: (i) => params[i] || null,
  };
}

function makeHost(overrides = {}) {
  const motion = component("Motion", "AE.ADBE Motion", [
    param("Position", { x: 960, y: 540 }),
    param("Scale", 100),
    param("Anchor Point", [0.5, 0.5]),
    param("Rotation", 0, { timeVarying: true }),
  ]);
  const item = Object.assign({
    name: "clip A",
    getIsSelected: () => Promise.resolve(true),
    getProjectItem: () => Promise.resolve({ id: "pi-1" }),
    getComponentChain: () => Promise.resolve({
      getComponentCount: () => 2,
      getComponentAtIndex: (i) => [component("Opacity", "AE.ADBE Opacity", []), motion][i] || null,
    }),
  }, overrides.item || {});

  const settings = Object.assign({
    getVideoFrameRect: () => Promise.resolve({ width: 1920, height: 1080 }),
    getVideoPixelAspectRatio: () => Promise.resolve("1"),
  }, overrides.settings || {});

  const sequence = Object.assign({
    name: "Sequence 1",
    getFrameSize: () => Promise.resolve({ width: 1920, height: 1080 }),
    getSettings: () => Promise.resolve(settings),
    getSelection: () => Promise.resolve({ getTrackItems: () => Promise.resolve([item]) }),
  }, overrides.sequence || {});

  const columnsJson = JSON.stringify([
    { ColumnID: "Column.Intrinsic.Name", ColumnName: "Name", ColumnValue: "clip A.mp4" },
    { ColumnID: "Column.Intrinsic.VideoInfo", ColumnName: "Video Info", ColumnValue: "3840 x 2160 (1.0)" },
  ]);

  return Object.assign({
    Project: {
      getActiveProject: () => Promise.resolve({ getActiveSequence: () => Promise.resolve(sequence) }),
    },
    Metadata: Object.assign({
      getProjectColumnsMetadata: () => Promise.resolve(columnsJson),
    }, overrides.metadata || {}),
  }, overrides.root || {});
}

const findingById = (report, id) => report.findings.filter((f) => f.id === id);
const oneFinding = (report, id) => {
  const hits = findingById(report, id);
  assert.equal(hits.length >= 1, true, `expected a "${id}" finding, got ids: ${report.findings.map((f) => f.id)}`);
  return hits[0];
};

// --- question 1: real match names and param indices ---------------------------------------

test("probe reports every component by index with its match name", async () => {
  const report = await capability.probeTransformParams(makeHost());
  assert.equal(report.complete, true);
  const components = oneFinding(report, "components");
  assert.deepEqual(components.evidence.components, [
    { index: 0, displayName: "Opacity", matchName: "AE.ADBE Opacity" },
    { index: 1, displayName: "Motion", matchName: "AE.ADBE Motion" },
  ]);
});

test("probe finds the Motion component and reports its params BY INDEX", async () => {
  const report = await capability.probeTransformParams(makeHost());
  const params = oneFinding(report, "transformParams").evidence;
  assert.equal(params.matchName, "AE.ADBE Motion");
  assert.equal(params.componentIndex, 1);
  assert.deepEqual(params.params.map((p) => [p.index, p.name]), [
    [0, "Position"], [1, "Scale"], [2, "Anchor Point"], [3, "Rotation"],
  ]);
});

// --- question 2: point SHAPE, which is the whole units question ---------------------------

test("probe records the RAW wrapper shape, not just the unwrapped value", async () => {
  const report = await capability.probeTransformParams(makeHost());
  const params = oneFinding(report, "transformParams").evidence.params;

  const position = params[0];
  assert.equal(position.rawJson, '{"value":{"x":960,"y":540}}');
  assert.equal(position.shape, "object{x,y}");
  assert.equal(position.hasXY, true);
  assert.deepEqual(position.unwrapped, { x: 960, y: 540 });

  // The competing shape effects.js saw by accident on a Transform component. Both must be
  // distinguishable from the report alone, without re-running anything.
  const anchor = params[2];
  assert.equal(anchor.rawJson, '{"value":[0.5,0.5]}');
  assert.equal(anchor.shape, "array[2]");
  assert.equal(anchor.hasXY, false);
});

test("probe reports isTimeVarying per param so animated clips can be skipped, not flattened", async () => {
  const report = await capability.probeTransformParams(makeHost());
  const params = oneFinding(report, "transformParams").evidence.params;
  assert.equal(params[0].isTimeVarying, false);
  assert.equal(params[3].isTimeVarying, true);
});

// --- question 3: sequence geometry --------------------------------------------------------

test("probe reads BOTH frame-size routes and says whether they agree", async () => {
  const geometry = oneFinding(await capability.probeTransformParams(makeHost()), "sequenceGeometry");
  assert.equal(geometry.answer, "1920x1080");
  assert.equal(geometry.evidence.routesAgree, true);
  // Typed Promise<string> in Adobe's declarations — recorded raw so a surprise type shows up.
  assert.equal(geometry.evidence.pixelAspectRatioRaw, '"1"');
  assert.equal(geometry.evidence.pixelAspectRatioType, "string");
});

test("probe flags disagreement between the two frame-size routes", async () => {
  const host = makeHost({ settings: { getVideoFrameRect: () => Promise.resolve({ width: 1280, height: 720 }) } });
  const geometry = oneFinding(await capability.probeTransformParams(host), "sequenceGeometry");
  assert.equal(geometry.evidence.routesAgree, false);
});

// --- question 4: the source-dimension route (plan Part 3) ---------------------------------

test("probe finds a source resolution column in the project-columns metadata", async () => {
  const dims = oneFinding(await capability.probeTransformParams(makeHost()), "sourceDimensions");
  assert.match(dims.answer, /^yes/);
  assert.equal(dims.evidence.parsedAsJson, true);
  assert.deepEqual(dims.evidence.resolutionCandidates, [
    { ColumnID: "Column.Intrinsic.VideoInfo", ColumnName: "Video Info", ColumnValue: "3840 x 2160 (1.0)" },
  ]);
});

test("probe reports the Video-Info column being absent as a finding, not a crash", async () => {
  // The exact case the ExtendScript docs warn about: the dump reflects the CURRENT project
  // view layout, so a user who hides the column changes the answer.
  const host = makeHost({
    metadata: {
      getProjectColumnsMetadata: () => Promise.resolve(
        JSON.stringify([{ ColumnID: "Column.Intrinsic.Name", ColumnName: "Name", ColumnValue: "clip A.mp4" }])),
    },
  });
  const dims = oneFinding(await capability.probeTransformParams(host), "sourceDimensions");
  assert.match(dims.answer, /^no — the metadata parsed but carries no resolution-looking column/);
  assert.deepEqual(dims.evidence.resolutionCandidates, []);
});

test("probe survives a build with no Metadata API at all", async () => {
  const host = makeHost();
  delete host.Metadata;
  const report = await capability.probeTransformParams(host);
  assert.equal(report.complete, true);
  const dims = oneFinding(report, "sourceDimensions");
  assert.match(dims.answer, /no Metadata\.getProjectColumnsMetadata/);
});

test("probe survives getProjectColumnsMetadata throwing", async () => {
  const host = makeHost({
    metadata: { getProjectColumnsMetadata: () => Promise.reject(new Error("not permitted")) },
  });
  const report = await capability.probeTransformParams(host);
  assert.equal(report.complete, true);
  assert.match(oneFinding(report, "sourceDimensions").answer, /the call failed/);
});

// --- the selection-getter claim, evidenced on the host rather than from the .d.ts ---------

test("probe records which selection getter the item really exposes", async () => {
  const api = oneFinding(await capability.probeTransformParams(makeHost()), "selectionApi");
  assert.equal(api.answer, "getIsSelected()");
  assert.equal(api.evidence["isSelected (undocumented)"], "undefined");
});

// --- error paths: every one a finding, never a throw --------------------------------------

test("no host, no project, no sequence and no selection each stop cleanly", async () => {
  const noHost = await capability.probeTransformParams(null);
  assert.equal(noHost.complete, false);
  assert.equal(oneFinding(noHost, "host").answer, "no");

  const noProject = await capability.probeTransformParams(
    { Project: { getActiveProject: () => Promise.resolve(null) } });
  assert.equal(noProject.complete, false);
  assert.equal(oneFinding(noProject, "project").answer, "no");

  const noSequence = await capability.probeTransformParams(
    { Project: { getActiveProject: () => Promise.resolve({ getActiveSequence: () => Promise.resolve(null) }) } });
  assert.equal(noSequence.complete, false);
  assert.equal(oneFinding(noSequence, "sequence").answer, "no");

  const nothingSelected = await capability.probeTransformParams(
    makeHost({ sequence: { getSelection: () => Promise.resolve({ getTrackItems: () => Promise.resolve([]) }) } }));
  assert.equal(nothingSelected.complete, false);
  assert.equal(oneFinding(nothingSelected, "selection").answer, "0");
});

test("a host call that THROWS is recorded, and the probe keeps going", async () => {
  const host = makeHost({
    sequence: { getFrameSize: () => { throw new Error("getFrameSize exploded"); } },
  });
  const report = await capability.probeTransformParams(host);
  assert.equal(report.complete, true, "one broken geometry call must not abort the probe");
  // The other route still answered, so the probe still has a frame size to report.
  assert.equal(oneFinding(report, "sequenceGeometry").answer, "1920x1080");
  assert.equal(findingById(report, "transformParams").length, 1, "params were still read");
});

test("one param whose getStartValue rejects does not lose the other params", async () => {
  const broken = component("Motion", "AE.ADBE Motion", [
    param("Position", null, { throws: "value unavailable" }),
    param("Scale", 100),
  ]);
  const host = makeHost({
    item: {
      getComponentChain: () => Promise.resolve({
        getComponentCount: () => 1,
        getComponentAtIndex: () => broken,
      }),
    },
  });
  const params = oneFinding(await capability.probeTransformParams(host), "transformParams").evidence.params;
  assert.equal(params.length, 2);
  assert.equal(params[0].present, false);
  assert.match(params[0].error, /value unavailable/);
  assert.equal(params[1].rawJson, '{"value":100}');
});

test("an item with no component chain is a finding, not a crash", async () => {
  const host = makeHost({ item: { getComponentChain: () => Promise.resolve(null) } });
  const report = await capability.probeTransformParams(host);
  assert.equal(report.complete, true);
  assert.equal(oneFinding(report, "chain").answer, "no");
});

test("a clip with no Motion or Transform component is reported as such", async () => {
  const host = makeHost({
    item: {
      getComponentChain: () => Promise.resolve({
        getComponentCount: () => 1,
        getComponentAtIndex: () => component("Opacity", "AE.ADBE Opacity", []),
      }),
    },
  });
  const report = await capability.probeTransformParams(host);
  assert.equal(oneFinding(report, "transform").answer, "not found");
});

// --- the formatter extraction was behavior-preserving -------------------------------------

test("formatFindings reproduces each probe's original header and body byte for byte", () => {
  const report = {
    complete: true,
    findings: [{ id: "x", question: "Q?", answer: "A", evidence: { k: "v", obj: { a: 1 }, skipped: null } }],
  };
  const body = ["• Q?", "    A", "      k: v", '      obj: {"a":1}'].join("\n");

  // The three pre-existing formatters, spelled out as they read before extraction.
  assert.equal(capability.formatMotionReport(report),
    `Adjustment Layer / Motion probe (complete)\n${body}`);
  assert.equal(capability.formatEffectChainReport(report),
    `Effect chain probe (complete)\n${body}`);
  assert.equal(capability.formatReport(Object.assign({ verdict: null }, report)),
    `Phase 0 probe 1 — marks and timing (complete)\n${body}\n` +
    "No verdict yet. Set In and Out on the source timeline — ideally on the same frame — and run again.");
  assert.equal(capability.formatReport(Object.assign({ verdict: "inclusive" }, report)),
    `Phase 0 probe 1 — marks and timing (complete)\n${body}\n` +
    "VERDICT: Out point looks inclusive. Set OUT_CONVENTION in timelineRange.js only after " +
    "confirming against Premiere's own duration display.");

  // A stopped-early report still says so.
  assert.match(capability.formatTransformReport({ complete: false, findings: [] }), /\(stopped early\)$/);
});

test("the transform report renders the real probe output as text", async () => {
  const text = capability.formatTransformReport(await capability.probeTransformParams(makeHost()));
  assert.match(text, /^Transform & Align Phase 0 probe — components, params, units \(complete\)/);
  assert.match(text, /AE\.ADBE Motion/);
  assert.match(text, /Anchor Point/);
});

// --- wiring: the probe is reachable from the real entry point ------------------------------
// The five links, machine-checked so a rename cannot quietly orphan the menu item. Without
// this, "Check Transform" could go on rendering while clicking it did nothing.


test("the Check Transform menu item is wired through to the probe", () => {
  const html = read("uxp/cutdeck/index.html");
  const panelJs = read("uxp/cutdeck/core/panel.js");
  const probesJs = read("uxp/cutdeck/features/probes.js");

  // reachable: the control exists in the document the panel actually loads
  assert.match(html, /id="transformprobe"/, "no #transformprobe control in index.html");

  // invoked: a click on it raises the intent
  assert.match(panelJs, /\$\("transformprobe"\)/, "panel.js never looks the control up");
  assert.match(panelJs, /intents\.onProbe\("transform"\)/, "panel.js never raises the transform intent");

  // routed: the controller handles that intent name and calls the probe + its formatter
  assert.match(probesJs, /name === "transform"/, "probes.js has no branch for the transform intent");
  assert.match(probesJs, /capability\.probeTransformParams\(ppro\)/, "probes.js never calls the probe");
  assert.match(probesJs, /capability\.formatTransformReport\(/, "probes.js never renders the report");

  // registered: both are exported from the module probes.js requires
  const exports = Object.keys(require("../uxp/cutdeck/capabilityProbe.js"));
  for (const name of ["probeTransformParams", "formatTransformReport"]) {
    assert.ok(exports.includes(name), `capabilityProbe.js does not export ${name}`);
  }

  // and the menu closes on click, like every other probe entry
  assert.match(panelJs, /"effectprobe", "transformprobe"/, "the menu will not close after clicking it");
});
