const test = require("node:test");
const assert = require("node:assert/strict");
const { createHksFeature, POLL_MS } = require("../uxp/cutdeck/features/hks.js");
const { createController } = require("../uxp/cutdeck/features/controller.js");

// What hks_status returns through the helper's premiere request ({result: …}).
const REPLY = {
  project: "C:/hks/day.prproj",
  sequences: [
    { guid: "g-old", name: "Day 20261126", status: "ungated", why: "never gated", new: false },
    { guid: "g-pass", name: "Piece A", status: "pass", failed: [], answers_missing: [], overrides: {},
      body_from: 12.5, checked: "2026-11-26T14:02:11", new: true },
    { guid: "g-fail", name: "Piece B", status: "fail",
      failed: [{ gate: "same_frame_cuts", value: 0.12, line: 0.05 }, { gate: "body_range", value: 0.7, line: 0.8 }],
      warned: [{ gate: "day_setup", value: 1, items: ["no yellow (must-keep / hot spot) on Editing"] }],
      answers_missing: ["R-12", "R-30"], overrides: { visible_cuts_in_speech: { reason: "music", by: "agent" } },
      body_from: 3, checked: "2026-11-26T14:05:00", new: true },
    { guid: "g-edit", name: "Piece C", status: "ungated", why: "changed after its last gate run", new: false },
    { guid: "g-draft", name: "Piece D", status: "ungated", why: "never gated", new: true },
    { guid: "g-unsaved", name: "Piece E", status: "ungated", why: "not saved yet" },
  ],
};

function helper(requests, answer = async () => ({ ok: true, result: REPLY })) {
  return async (req) => { requests.push(req); return answer(req); };
}

function manualTimers() {
  const pending = [];
  return {
    setTimer: (fn, ms) => { const t = { fn, ms }; pending.push(t); return t; },
    clearTimer: (t) => { const i = pending.indexOf(t); if (i >= 0) pending.splice(i, 1); },
    async fire() { const t = pending.shift(); t.fn(); await new Promise((r) => setImmediate(r)); },
    pending,
  };
}

test("refresh asks the helper for hks_status and keeps its rows as given", async () => {
  const requests = [];
  const ctl = createController({ render: () => {} });
  await createHksFeature({ ctl, rpc: helper(requests) }).refresh();
  assert.deepEqual(requests, [{ type: "premiere", command: "hks_status", args: {} }]);
  assert.deepEqual(ctl.state.hks.sequences, REPLY.sequences);
  assert.equal(ctl.state.hks.error, null);
});

test("a failed call keeps the last rows, shows the error in the section, not on the status dot", async () => {
  const ctl = createController({ render: () => {} });
  let fail = false;
  const feature = createHksFeature({ ctl, rpc: helper([], async () => {
    if (fail) throw new Error("Cannot reach CutDeck helper.");
    return { ok: true, result: REPLY };
  }) });
  await feature.refresh();
  ctl.setStatus("12 cuts · 3.0 seconds removed", "ready");
  fail = true;
  await feature.refresh();
  assert.deepEqual(ctl.state.hks.sequences, REPLY.sequences);
  assert.equal(ctl.state.hks.error, "Cannot reach CutDeck helper.");
  assert.equal(ctl.state.status.text, "12 cuts · 3.0 seconds removed");
});

test("the driver's list_project message does not replace the panel status", async () => {
  const ctl = createController({ render: () => {} });
  ctl.setStatus("Rough cut finished", "ready");
  // hks_status runs list_project through this panel's driver, which reports on the dot.
  await createHksFeature({ ctl, rpc: helper([], async () => {
    ctl.setStatus("Done: list project for an outside request.", "ready");
    return { ok: true, result: REPLY };
  }) }).refresh();
  assert.equal(ctl.state.status.text, "Rough cut finished");
});

test("a driver error from a background refresh stays in the section, off the status dot", async () => {
  const ctl = createController({ render: () => {} });
  ctl.setStatus("Ready", "ready");
  // The helper relays the driver's error text unchanged (helper.py _call_driver, driver_reply).
  await createHksFeature({ ctl, rpc: helper([], async () => {
    ctl.setStatus("Open a Premiere project first.", "error");
    throw new Error("Open a Premiere project first.");
  }) }).refresh();
  assert.deepEqual(ctl.state.status, { text: "Ready", level: "ready" });
  assert.equal(ctl.state.hks.error, "Open a Premiere project first.");
});

test("nothing is asked while the panel is busy (the driver would refuse list_project)", async () => {
  const requests = [];
  const ctl = createController({ render: () => {} });
  ctl.state.busy = true;
  await createHksFeature({ ctl, rpc: helper(requests) }).refresh();
  assert.deepEqual(requests, []);
});

test("polls every 30 s, skips a busy tick, and stops on teardown", async () => {
  const requests = [];
  const timers = manualTimers();
  const ctl = createController({ render: () => {} });
  const feature = createHksFeature({ ctl, rpc: helper(requests), ...timers });
  feature.startPolling();
  assert.equal(timers.pending[0].ms, POLL_MS);
  assert.equal(POLL_MS, 30000);
  await timers.fire();
  assert.equal(requests.length, 1);
  ctl.state.busy = true;
  await timers.fire();
  assert.equal(requests.length, 1);
  ctl.state.busy = false;
  feature.stopPolling();
  assert.equal(timers.pending.length, 0);
});

// --- render: a DOM stub with what core/panel.js renderHks touches ----------------------------

function domStub(ids) {
  const make = (id) => {
    const classes = new Set();
    const attrs = {};
    const el = {
      id, children: [], hidden: false, _text: "",
      get textContent() { return el._text; },
      set textContent(v) { el._text = String(v); },
      set innerHTML(_v) { el.children = []; },
      get className() { return [...classes].join(" "); },
      set className(v) { classes.clear(); String(v).split(" ").filter(Boolean).forEach((c) => classes.add(c)); },
      classList: {
        toggle(c, force) { const want = force === undefined ? !classes.has(c) : !!force; if (want) classes.add(c); else classes.delete(c); return want; },
        contains: (c) => classes.has(c),
        add: (c) => classes.add(c), remove: (c) => classes.delete(c),
      },
      getAttribute: (n) => (n in attrs ? attrs[n] : null),
      setAttribute: (n, v) => { attrs[n] = String(v); },
      removeAttribute: (n) => { delete attrs[n]; },
      appendChild(child) { el.children.push(child); return child; },
      addEventListener() {},
    };
    return el;
  };
  const byId = new Map(ids.map((id) => [id, make(id)]));
  return {
    byId,
    document: {
      getElementById: (id) => byId.get(id) || null,
      querySelectorAll: () => [],
      createElement: () => make(undefined),
      addEventListener() {},
    },
  };
}

function renderHks(hks, times = 1) {
  const dom = domStub(["hks-list", "hks-note", "hks-never", "hks-never-count", "hks-never-arrow"]);
  global.document = dom.document;
  delete require.cache[require.resolve("../uxp/cutdeck/core/panel.js")];
  const panel = require("../uxp/cutdeck/core/panel.js");
  const renders = [];
  for (let i = 0; i < times; i++) {
    panel.render({ hks });
    renders.push([...dom.byId.get("hks-list").children]);
  }
  delete global.document;
  if (times > 1) return renders;
  const rows = dom.byId.get("hks-list").children.map((row) => ({
    className: row.className,
    head: row.children[0].children.map((c) => c.textContent),
    lines: row.children.slice(1).map((c) => c.textContent),
  }));
  return { rows, get: (id) => dom.byId.get(id) };
}

test("pass, fail and ungated rows print the helper's verdict; new sequences come first", () => {
  const { rows } = renderHks({ ...REPLY, error: null });
  assert.deepEqual(rows.map((r) => r.head), [
    ["pass", "Piece A · new"], ["fail", "Piece B · new"], ["ungated", "Piece D · new"],
    ["ungated", "Day 20261126"], ["ungated", "Piece C"], ["ungated", "Piece E"],
  ]);
  assert.deepEqual(rows[0].lines, ["body from 12.5 s · checked 2026-11-26 14:02:11"]);
  assert.deepEqual(rows[1].lines, [
    "same_frame_cuts 0.12 vs 0.05",
    "body_range 0.7 vs 0.8",
    "warning day_setup: no yellow (must-keep / hot spot) on Editing",
    "2 answers missing: R-12, R-30",
    "1 overridden: visible_cuts_in_speech",
    "body from 3 s · checked 2026-11-26 14:05:00",
  ]);
  assert.deepEqual(rows[2].lines, ["never gated"]);
  assert.deepEqual(rows[4].lines, ["changed after its last gate run"]);
  assert.deepEqual(rows[5].lines, ["not saved yet"]);
  assert.match(rows[1].className, /hks-fail/);
});

test("never-gated sequences from before the baseline hide behind a count; new ones stay listed", () => {
  const { rows, get } = renderHks({ ...REPLY, error: null });
  const hidden = rows.filter((r) => r.className.includes("hks-hidden")).map((r) => r.head[1]);
  assert.deepEqual(hidden, ["Day 20261126"]);
  assert.equal(get("hks-never-count").textContent, "1 never gated");
  assert.equal(get("hks-never").hidden, false);
  assert.equal(get("hks-note").hidden, true);
});

test("with no baseline (new: null) every never-gated sequence hides behind the count", () => {
  const sequences = REPLY.sequences.map((s) => ({ ...s, new: null }));
  const { rows, get } = renderHks({ project: "p", sequences, error: null });
  assert.deepEqual(rows.map((r) => r.head[1]), ["Day 20261126", "Piece A", "Piece B", "Piece C", "Piece D", "Piece E"]);
  assert.equal(get("hks-never-count").textContent, "2 never gated");
});

test("a second render of the same reply keeps the same row elements", () => {
  const [first, second] = renderHks({ ...REPLY, error: null }, 2);
  assert.equal(first.length, REPLY.sequences.length);
  assert.ok(first.every((row, i) => row === second[i]));
});

test("before the first reply and after a failed one the section says so", () => {
  assert.equal(renderHks(undefined).get("hks-note").textContent, "Not checked yet.");
  const failed = renderHks({ ...REPLY, error: "CutDeck helper timed out." });
  assert.equal(failed.get("hks-note").textContent, "Not updated: CutDeck helper timed out.");
  assert.equal(failed.get("hks-note").hidden, false);
  assert.equal(failed.rows.length, REPLY.sequences.length);
});
