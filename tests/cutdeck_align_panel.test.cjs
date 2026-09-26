/* Phase 0a of the Transform & Align plan (docs/research/cutdeck-transform-panel-plan.md):
   the second panel entrypoint.

   The plan originally called for a second HTML document (align.html) with its own per-
   entrypoint "main". That is not buildable: Adobe's manifest schema allows only type, id,
   label, description, shortcut, icon and the *Size hints on an entrypoint, and `main` is a
   single top-level property. Every panel in a plugin shares ONE document, and extra panels
   are containers moved into their own root by the entrypoints.setup() show() hook. These
   tests pin that corrected shape down.

   What cannot be proven here: that Premiere actually opens the second panel and calls show().
   That needs the host. What IS proven here is everything that would make it fail before it
   got that far — a malformed manifest, a container that does not exist, ids that do not
   resolve, a mount that does not move anything, and a bootstrap that could take the existing
   Cut & Sync panel down with it. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const read = (p) => fs.readFileSync(path.join(root, p), "utf8");

const manifest = JSON.parse(read("uxp/cutdeck/manifest.json"));
const html = read("uxp/cutdeck/index.html");
const mainJs = read("uxp/cutdeck/main.js");
const alignFeatureJs = read("uxp/cutdeck/features/align.js");
const alignJsPath = path.join(root, "uxp", "cutdeck", "core", "alignPanel.js");

// --- manifest ------------------------------------------------------------------------------

test("the manifest declares two panel entrypoints with distinct ids", () => {
  const panels = manifest.entrypoints.filter((e) => e.type === "panel");
  assert.equal(panels.length, 2);
  assert.deepEqual(panels.map((p) => p.id), ["cutdeck.panel", "cutdeck.align.panel"]);
  assert.equal(new Set(panels.map((p) => p.id)).size, 2, "entrypoint ids must be unique");
  for (const p of panels) {
    assert.ok(p.label && p.label.default, `${p.id} needs a label`);
  }
});

test("there is exactly ONE top-level main, and no entrypoint carries its own", () => {
  // The correction this slice is built on. If a future edit adds a per-entrypoint "main" it
  // will be silently ignored by Premiere, and this test says so before the panel ships blank.
  assert.equal(manifest.main, "index.html");
  for (const entry of manifest.entrypoints) {
    assert.equal(entry.main, undefined,
      `entrypoint ${entry.id} has a "main" field; UXP has no such thing and will ignore it`);
  }
});

test("the manifest enables the ipc permission multi-panel plugins need", () => {
  assert.equal(manifest.requiredPermissions.ipc.enablePluginCommunication, true);
});

test("the existing Cut & Sync entrypoint is untouched", () => {
  // This slice must not regress the shipped panel to add a new one.
  const first = manifest.entrypoints.find((e) => e.id === "cutdeck.panel");
  assert.equal(first.label.default, "CutDeck");
  assert.equal(first.type, "panel");
  assert.deepEqual(first.minimumSize, { width: 300, height: 420 });
});

// --- the container and its ids -------------------------------------------------------------

test("the transform container exists and ships hidden", () => {
  assert.match(html, /<div id="view-transform" hidden>/,
    "the container must ship hidden or it flashes inside the Cut & Sync panel");
});

test('every $("id") in core/alignPanel.js resolves to an id in index.html', () => {
  // The same bar core/panel.js is held to by panel_ui_contract.test.cjs.
  const source = fs.readFileSync(alignJsPath, "utf8");
  const ids = new Set([...source.matchAll(/\$\("([a-zA-Z0-9_-]+)"\)/g)].map((m) => m[1]));
  const htmlIds = new Set([...html.matchAll(/\bid="([a-zA-Z0-9_-]+)"/g)].map((m) => m[1]));
  assert.ok(ids.size >= 3, "expected alignPanel.js to reference several ids");
  const misses = [...ids].filter((id) => !htmlIds.has(id));
  assert.deepEqual(misses, [], `alignPanel.js references ids missing from index.html: ${misses}`);
});

test("the transform panel's ids do not collide with the Cut & Sync panel's", () => {
  // One shared document means one shared id namespace. A collision would have one panel
  // silently rendering into the other's nodes.
  const source = fs.readFileSync(alignJsPath, "utf8");
  const alignIds = [...source.matchAll(/\$\("([a-zA-Z0-9_-]+)"\)/g)].map((m) => m[1]);
  const panelIds = new Set(
    [...fs.readFileSync(path.join(root, "uxp", "cutdeck", "core", "panel.js"), "utf8")
      .matchAll(/\$\("([a-zA-Z0-9_-]+)"\)/g)].map((m) => m[1]));
  const collisions = alignIds.filter((id) => panelIds.has(id));
  assert.deepEqual(collisions, [], `both seams claim these ids: ${collisions}`);
});

// --- mount / render, against a DOM stub ------------------------------------------------------

function makeStub() {
  const nodes = new Map();
  function el(id) {
    let text = "";
    const classes = new Set();
    const attrs = {};
    const node = {
      id, hidden: false, disabled: false, parentElement: null, children: [],
      get textContent() { return text; },
      set textContent(v) { text = String(v); },
      classList: {
        add: (c) => classes.add(c),
        remove: (c) => classes.delete(c),
        toggle(c, force) {
          const want = force === undefined ? !classes.has(c) : !!force;
          if (want) classes.add(c); else classes.delete(c);
          return want;
        },
        contains: (c) => classes.has(c),
      },
      get className() { return [...classes].join(" "); },
      getAttribute: (n) => (n in attrs ? attrs[n] : null),
      setAttribute: (n, v) => { attrs[n] = String(v); },
      appendChild(child) {
        if (child.parentElement) {
          child.parentElement.children = child.parentElement.children.filter((c) => c !== child);
        }
        node.children.push(child);
        child.parentElement = node;
        return child;
      },
      querySelectorAll: (sel) =>
        (sel === "[data-act]" ? node.children.filter((c) => c.getAttribute("data-act") !== null) : []),
      addEventListener(type, fn) { (node.listeners[type] = node.listeners[type] || []).push(fn); },
      listeners: {},
    };
    nodes.set(id, node);
    return node;
  }

  const container = el("view-transform");
  container.hidden = true;
  const probe = el("align-probe");
  probe.setAttribute("data-act", "align-probe");
  container.appendChild(probe);
  const anchorCell = el("anchor-cell-test");
  anchorCell.setAttribute("data-act", "align-anchor");
  anchorCell.setAttribute("data-needs-clip", "");
  container.appendChild(anchorCell);
  el("align-refresh").setAttribute("data-act", "align-refresh");
  el("align-status-card");
  el("align-status");
  el("align-status-icon");
  el("align-transform-clip");
  el("align-transform-fields");
  el("align-scale-reset");
  el("align-rotation-reset");
  for (const [id, field] of [["align-position-x", "position-x"], ["align-position-y", "position-y"],
    ["align-scale", "scale"], ["align-rotation", "rotation"], ["align-anchor-x", "anchor-x"], ["align-anchor-y", "anchor-y"]]) {
    el(id).setAttribute("data-field", field);
  }

  const body = el("__body__");
  body.appendChild(container);

  global.document = { getElementById: (id) => nodes.get(id) || null };
  global.window = undefined;
  return { nodes, container, body, probe };
}

function loadAlignPanel() {
  delete require.cache[require.resolve("../uxp/cutdeck/core/alignPanel.js")];
  return require("../uxp/cutdeck/core/alignPanel.js");
}

/* Stands in for the rootNode Premiere hands show(). It must reparent the way a real
   appendChild does — detaching the node from its previous parent — or the test would pass
   while the container stayed in the shared body in the real host. */
function makePanelRoot() {
  return {
    children: [],
    appendChild(child) {
      if (child.parentElement) {
        child.parentElement.children = child.parentElement.children.filter((c) => c !== child);
      }
      this.children.push(child);
      child.parentElement = this;
      return child;
    },
  };
}

test("mount moves the container into the given root and reveals it", () => {
  const { container, body } = makeStub();
  const alignPanel = loadAlignPanel();
  const panelRoot = makePanelRoot();

  assert.equal(container.hidden, true, "precondition: ships hidden");
  assert.equal(alignPanel.mount(panelRoot), true);
  assert.equal(container.parentElement, panelRoot, "container did not move into the panel root");
  assert.equal(container.hidden, false, "mount must reveal the container");
  assert.equal(body.children.includes(container), false, "container is still in the shared body");

  delete global.document;
});

test("mount is idempotent and a second mount into the same root moves nothing", () => {
  makeStub();
  const alignPanel = loadAlignPanel();
  const panelRoot = { children: [], appendChild(c) { this.children.push(c); c.parentElement = this; } };
  alignPanel.mount(panelRoot);
  alignPanel.mount(panelRoot);
  assert.equal(panelRoot.children.length, 1, "the container was appended twice");
  delete global.document;
});

test("mount reports failure instead of pretending, when there is nothing to mount", () => {
  global.document = { getElementById: () => null };
  const alignPanel = loadAlignPanel();
  assert.equal(alignPanel.mount({ appendChild() {} }), false, "no container should be a reported failure");
  assert.equal(alignPanel.mount(null), false, "no root should be a reported failure");
  delete global.document;
});

test("unmount hides the container again", () => {
  const { container } = makeStub();
  const alignPanel = loadAlignPanel();
  alignPanel.mount({ appendChild(c) { c.parentElement = this; } });
  assert.equal(alignPanel.isMounted(), true);
  assert.equal(alignPanel.unmount(), true);
  assert.equal(container.hidden, true);
  assert.equal(alignPanel.isMounted(), false);
  delete global.document;
});

test("render is idempotent: a second call with the same state changes nothing further", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  const state = { sequence: { name: "Sequence 1" }, busy: true, status: { text: "Working…", level: "busy" } };

  const snapshot = () => [...nodes.values()].map((n) => ({
    id: n.id, textContent: n.textContent, hidden: n.hidden, disabled: n.disabled, className: n.className,
    childCount: n.children.length,
  }));

  alignPanel.render(state);
  const first = snapshot();
  alignPanel.render(state);
  assert.deepEqual(snapshot(), first);
  delete global.document;
});

test("render puts the sequence name in the clip line's tooltip and disables every control while busy", () => {
  const { nodes, probe } = makeStub();
  const alignPanel = loadAlignPanel();

  alignPanel.render({ sequence: { name: "CFD 94" }, busy: true, status: { text: "Working…", level: "busy" } });
  assert.equal(nodes.get("align-transform-clip").getAttribute("title"), "CFD 94");
  assert.equal(nodes.get("align-status-icon").className.includes("busy"), true);
  assert.equal(probe.disabled, true, "controls must be disabled while a job runs");

  alignPanel.render({ sequence: null, busy: false, status: { text: "Ready", level: "ready" } });
  assert.equal(nodes.get("align-transform-clip").getAttribute("title"), "No sequence open");
  assert.equal(probe.disabled, false);
  delete global.document;
});

test("the status bar stays hidden unless there is an error or a skipped clip", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  const card = () => nodes.get("align-status-card").hidden;
  alignPanel.render({ sequence: null, busy: false, status: { text: "Ready", level: "ready" } });
  assert.equal(card(), true);
  alignPanel.render({ sequence: null, busy: true, status: { text: "Processing…", level: "busy" } });
  assert.equal(card(), true);
  alignPanel.render({ sequence: null, busy: false, status: { text: "Skipped: x", level: "warn" } });
  assert.equal(card(), false);
  assert.equal(nodes.get("align-status").textContent, "Skipped: x");
  alignPanel.render({ sequence: null, busy: false, status: { text: "Open a sequence first.", level: "error" } });
  assert.equal(card(), false);
  alignPanel.render({ sequence: null, busy: false, status: { text: "Transform report…", level: "info" } });
  assert.equal(card(), false, "a Check Transform report must be visible");
  delete global.document;
});

test("anchor and align controls are disabled while there is no editable clip; refresh and probe are not", () => {
  const { nodes, probe } = makeStub();
  const alignPanel = loadAlignPanel();
  const noClip = { clipName: null, available: false, reason: "Select a clip on the timeline.", fields: null };
  alignPanel.render({ sequence: { name: "S" }, transform: noClip, busy: false, status: { text: "Ready", level: "ready" } });
  assert.equal(nodes.get("anchor-cell-test").disabled, true);
  assert.equal(nodes.get("align-refresh").disabled, false);
  assert.equal(probe.disabled, false);
  delete global.document;
});

// --- Phase 1: renderTransform (docs/research/cutdeck-transform-panel-plan.md) --------------

test("renderTransform shows 'No sequence open' and blanks and disables every field when transform is null", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  alignPanel.render({ sequence: null, transform: null, busy: false, status: { text: "Ready", level: "ready" } });
  assert.equal(nodes.get("align-transform-clip").textContent, "No sequence open");
  assert.equal(nodes.get("align-scale").value, "");
  assert.equal(nodes.get("align-scale").disabled, true);
  delete global.document;
});

test("renderTransform shows the reason in the clip line and disables the fields when the clip has no readable Transform", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  alignPanel.render({
    sequence: { name: "CFD 94" },
    transform: { clipName: "AudioOnly.wav", available: false, reason: "This item has no readable Transform.", fields: null },
    busy: false, status: { text: "Ready", level: "ready" },
  });
  assert.equal(nodes.get("align-transform-clip").textContent, "This item has no readable Transform.");
  assert.equal(nodes.get("align-position-x").disabled, true);
  delete global.document;
});

test("renderTransform shows 'Select a clip on the timeline.' when nothing is selected", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  alignPanel.render({
    sequence: { name: "CFD 94" },
    transform: { clipName: null, available: false, reason: "Select a clip on the timeline.", fields: null },
    busy: false, status: { text: "Ready", level: "ready" },
  });
  assert.equal(nodes.get("align-transform-clip").textContent, "Select a clip on the timeline.");
  delete global.document;
});

test("renderTransform formats Position/Scale/Rotation/Anchor to one decimal, matching Effect Controls", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  alignPanel.render({
    sequence: { name: "CFD 94" },
    transform: {
      clipName: "Lowerthird 2026.png",
      available: true,
      reason: null,
      fields: {
        position: { known: true, animated: false, x: -510.77, y: 44.92 },
        scale: { known: true, animated: false, value: 162 },
        rotation: { known: true, animated: false, value: 0 },
        anchor: { known: true, animated: false, x: 1.953, y: 60.54 },
      },
    },
    busy: false, status: { text: "Ready", level: "ready" },
  });
  assert.equal(nodes.get("align-transform-clip").textContent, "Lowerthird 2026.png");
  const values = ["align-position-x", "align-position-y", "align-scale", "align-rotation", "align-anchor-x", "align-anchor-y"]
    .map((id) => nodes.get(id).value);
  assert.deepEqual(values, ["-510.8", "44.9", "162", "0", "2", "60.5"]);
  assert.equal(nodes.get("align-scale").disabled, false);
  delete global.document;
});

test("renderTransform empties and disables a keyframed field instead of showing a possibly-wrong static number", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  alignPanel.render({
    sequence: { name: "CFD 94" },
    transform: {
      clipName: "clip A",
      available: true,
      reason: null,
      fields: {
        position: { known: true, animated: true },
        scale: { known: true, animated: false, value: 100 },
        rotation: { known: true, animated: false, value: 0 },
        anchor: { known: true, animated: false, x: 960, y: 540 },
      },
    },
    busy: false, status: { text: "Ready", level: "ready" },
  });
  for (const id of ["align-position-x", "align-position-y"]) {
    assert.equal(nodes.get(id).value, "");
    assert.equal(nodes.get(id).disabled, true);
    assert.equal(nodes.get(id).getAttribute("placeholder"), "keyframed");
  }
  assert.equal(nodes.get("align-scale").value, "100");
  assert.equal(nodes.get("align-scale").disabled, false);
  delete global.document;
});

test("renderTransform shows '—' for a field that could not be read at all", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  alignPanel.render({
    sequence: { name: "CFD 94" },
    transform: {
      clipName: "clip A",
      available: true,
      reason: null,
      fields: {
        position: { known: false },
        scale: { known: true, animated: false, value: 100 },
        rotation: { known: false },
        anchor: { known: true, animated: false, x: 960, y: 540 },
      },
    },
    busy: false, status: { text: "Ready", level: "ready" },
  });
  for (const id of ["align-position-x", "align-rotation"]) {
    assert.equal(nodes.get(id).value, "");
    assert.equal(nodes.get(id).disabled, true);
    assert.equal(nodes.get(id).getAttribute("placeholder"), "—");
  }
  delete global.document;
});

test("bind raises the transform intent when the probe button is clicked", () => {
  const { probe } = makeStub();
  const alignPanel = loadAlignPanel();
  const raised = [];
  alignPanel.bind({ onProbe: (name) => raised.push(name), onRefresh: () => raised.push("refresh") });

  probe.listeners.click.forEach((fn) => fn());
  assert.deepEqual(raised, ["transform"]);
  delete global.document;
});

// --- bootstrap: the new panel must not be able to take the shipped one down -----------------

test("entrypoints.setup registers BOTH panel ids", () => {
  for (const id of ["cutdeck.panel", "cutdeck.align.panel"]) {
    assert.ok(mainJs.includes(`"${id}"`), `main.js never registers ${id}`);
  }
  assert.match(mainJs, /entrypoints\.setup\(/, "main.js never calls entrypoints.setup");
  assert.match(mainJs, /alignPanel\.mount\(rootNode\)/, "the show hook never mounts the container");
});

test("entrypoints.setup is guarded, and runs after the main panel is already bound", () => {
  // If setup() throws on a build, the Cut & Sync panel must still work. That is only true if
  // the call is both wrapped and placed after panel.bind().
  const setupAt = mainJs.indexOf("entrypoints.setup(");
  const bindAt = mainJs.indexOf("panel.bind({");
  assert.ok(bindAt !== -1 && setupAt !== -1);
  assert.ok(bindAt < setupAt, "entrypoints.setup() must come after panel.bind()");

  const guarded = /try\s*\{[\s\S]*entrypoints\.setup\([\s\S]*\}\s*catch/.test(mainJs);
  assert.ok(guarded, "entrypoints.setup() must be wrapped in try/catch");
});

// --- Phase 1 wiring: the read-only transform display is reachable from the real entry point -

test("features/align.js requires the transform host-discovery and geometry modules", () => {
  assert.match(alignFeatureJs, /require\("\.\.\/host\/trackItems\.js"\)/);
  assert.match(alignFeatureJs, /require\("\.\.\/transform\/params\.js"\)/);
  assert.match(alignFeatureJs, /require\("\.\.\/transform\/geometry\.js"\)/);
});

test("Anchor Point is converted against the SOURCE frame, never the sequence frame", () => {
  // Part 1a: Anchor Point is normalized to the source, Position to the sequence. Converting
  // Anchor Point against frameSize printed 150, 300 for a 100, 200 anchor on a 720p clip.
  // A Graphic has no project item, so its anchor frame falls back to the sequence frame
  // (transform/params.js readAnchorFrameSize; behaviour covered in cutdeck_transform_params).
  assert.match(alignFeatureJs, /anchorFrame = await transformParams\.readAnchorFrameSize\(ppro, item, seq\)/);
  assert.match(alignFeatureJs, /anchor:\s*describeField\(transform\.anchorPoint,\s*true,\s*anchorFrame\)/);
  assert.match(alignFeatureJs, /position:\s*describeField\(transform\.position,\s*true,\s*frameSize\)/);
});

test("the transform panel's show hook starts the live poll, after mounting and the first read", () => {
  const showAt = mainJs.indexOf('"cutdeck.align.panel"');
  assert.ok(showAt !== -1, "cutdeck.align.panel entrypoint is not registered");
  const showBlock = mainJs.slice(showAt, mainJs.indexOf("},", showAt));
  assert.match(showBlock, /alignPanel\.mount\(rootNode\)/);
  assert.match(showBlock, /align\.refresh\(\)/);
  assert.match(showBlock, /align\.startPolling\(\)/);
  const mountAt = showBlock.indexOf("alignPanel.mount");
  const pollAt = showBlock.indexOf("align.startPolling()");
  assert.ok(mountAt < pollAt, "polling must start after the container is mounted");
});

test("the poll never touches alignState.busy/status, so it cannot flicker the spinner or disable controls", () => {
  const pollAt = alignFeatureJs.indexOf("async function pollAlignTransform");
  assert.ok(pollAt !== -1, "pollAlignTransform is not defined");
  const pollBody = alignFeatureJs.slice(pollAt, alignFeatureJs.indexOf("\n  function startAlignPolling", pollAt));
  assert.equal(/ctl\.state\.busy\s*=/.test(pollBody), false, "poll must not set busy");
  assert.equal(/ctl\.state\.status\s*=/.test(pollBody), false, "poll must not set status");
});

test("no hide or destroy hook is registered", () => {
  // Adobe documents both as not working as expected in Premiere; depending on them would be
  // depending on something known broken.
  //
  // Comments are stripped and the anchor includes the opening brace: main.js explains itself
  // with the words "entrypoints.setup()" several times before the real call, and an earlier
  // version of this test matched that prose instead of a registered hook.
  const code = mainJs.replace(/^\s*\/\/.*$/gm, "");
  const setupAt = code.indexOf("entrypoints.setup({");
  assert.ok(setupAt !== -1, "no entrypoints.setup({ ... }) call found in main.js");
  const setupBlock = code.slice(setupAt);
  assert.equal(/\bhide\s*\(/.test(setupBlock), false, "a hide() hook was registered");
  assert.equal(/\bdestroy\s*\(/.test(setupBlock), false, "a destroy() hook was registered");
});

// --- event-driven refresh (review 2026-09-24 item 2) ---------------------------------------

function withFakeInterval(fn) {
  const orig = global.setInterval;
  const origClear = global.clearInterval;
  const calls = [];
  const cleared = [];
  global.setInterval = (cb, ms) => { calls.push(ms); return calls.length; };
  global.clearInterval = (id) => { cleared.push(id); };
  let out;
  try { out = fn(calls, cleared); } catch (e) { global.setInterval = orig; global.clearInterval = origClear; throw e; }
  return Promise.resolve(out).finally(() => { global.setInterval = orig; global.clearInterval = origClear; });
}

test("Transform panel attaches selection to the active sequence and moves it on switch", async () => {
  const { createAlignFeature } = require("../uxp/cutdeck/features/align.js");
  const seqA = { name: "A" }, seqB = { name: "B" };
  let active = seqA;
  const globals = {}, attached = [], removed = [];
  const ppro = {
    Constants: { SequenceEvent: { ACTIVATED: "a", SELECTION_CHANGED: "s" } },
    EventManager: {
      addGlobalEventListener: (name, h) => { globals[name] = h; },
      addEventListener: (target, name) => attached.push([target.name, name]),
      removeEventListener: (target, name) => removed.push([target.name, name]),
    },
    Project: { getActiveProject: async () => ({ getActiveSequence: async () => active }) },
  };
  await withFakeInterval(async (calls) => {
    const f = createAlignFeature({ ppro, ctl: { state: {}, render() {} } });
    f.startPolling();
    f.startPolling();
    await new Promise((r) => setTimeout(r, 10));
    assert.deepEqual(Object.keys(globals), ["a"]); // no global SELECTION_CHANGED: it never fires live
    assert.deepEqual(attached, [["A", "s"]]);
    assert.deepEqual(calls, [150]); // keeps heartbeat poll for timeline clicks where Premiere fires no event
    active = seqB;
    globals.a();
    await new Promise((r) => setTimeout(r, 10));
    assert.deepEqual(removed, [["A", "s"]]);
    assert.deepEqual(attached, [["A", "s"], ["B", "s"]]);
  });
});


test("stopPolling unregisters global and target listeners and clears interval", async () => {
  const { createAlignFeature } = require("../uxp/cutdeck/features/align.js");
  const seqA = { name: "A" };
  const removedTarget = [];
  const removedGlobals = [];
  const ppro = {
    Constants: { SequenceEvent: { ACTIVATED: "a", SELECTION_CHANGED: "s" } },
    EventManager: {
      addGlobalEventListener: (name, h) => {},
      addEventListener: (target, name) => {},
      removeEventListener: (target, name) => removedTarget.push([target.name, name]),
      removeGlobalEventListener: (name, h) => removedGlobals.push(name),
    },
    Project: { getActiveProject: async () => ({ getActiveSequence: async () => seqA }) },
  };
  await withFakeInterval(async (calls, cleared) => {
    const f = createAlignFeature({ ppro, ctl: { state: {}, render() {} } });
    f.startPolling();
    await new Promise((r) => setTimeout(r, 10));
    assert.deepEqual(calls, [150]);
    f.stopPolling();
    assert.deepEqual(cleared, [1]);
    assert.deepEqual(removedTarget, [["A", "s"]]);
    assert.deepEqual(removedGlobals, ["a"]);
  });
});

test("Transform panel falls back to the fast poll without EventManager", async () => {
  const { createAlignFeature } = require("../uxp/cutdeck/features/align.js");
  await withFakeInterval((calls) => {
    createAlignFeature({ ppro: {}, ctl: { state: {}, render() {} } }).startPolling();
    assert.deepEqual(calls, [150]);
  });
});

test("a burst of events collapses into at most two reads", async () => {
  const { createAlignFeature } = require("../uxp/cutdeck/features/align.js");
  let handler = null;
  let reads = 0;
  const ppro = {
    Constants: { SequenceEvent: { ACTIVATED: "a", SELECTION_CHANGED: "s" } },
    EventManager: { addGlobalEventListener() {}, addEventListener: (t, name, h) => { handler = h; } },
    Project: { getActiveProject: async () => { reads++; await new Promise((r) => setImmediate(r)); return { getActiveSequence: async () => seq }; } },
  };
  const seq = { name: "A" };
  await withFakeInterval(async () => {
    createAlignFeature({ ppro, ctl: { state: {}, render() {} } }).startPolling();
    await new Promise((r) => setTimeout(r, 10));
    reads = 0;
    for (let i = 0; i < 10; i++) handler();
    await new Promise((r) => setTimeout(r, 20));
  });
  assert.ok(reads >= 1 && reads <= 2, `expected 1-2 reads, got ${reads}`);
});

test("readAlignTransform names the clip via getName() (track items have no .name)", async () => {
  const { readAlignTransform } = require("../uxp/cutdeck/features/align.js");
  const item = { getName: async () => "Interview_A.mp4", getIsSelected: async () => true };
  const seq = { getSelection: async () => ({ getTrackItems: async () => [item] }) };
  const out = await readAlignTransform(seq, null);
  assert.equal(out.clipName, "Interview_A.mp4");
});

test("bind raises onSetField with the field name and typed text when an input changes", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  const raised = [];
  alignPanel.bind({ onProbe() {}, onRefresh() {}, onSetField: (f, v) => raised.push([f, v]), onAnchor() {}, onAlign() {} });
  nodes.get("align-anchor-y").listeners.change.forEach((fn) => fn({ target: { value: "12.5" } }));
  assert.deepEqual(raised, [["anchor-y", "12.5"]]);
  delete global.document;
});

test("clicking reset buttons raises onSetField with default values", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  const raised = [];
  alignPanel.bind({ onProbe() {}, onRefresh() {}, onSetField: (f, v) => raised.push([f, v]), onAnchor() {}, onAlign() {} });
  nodes.get("align-scale-reset").listeners.click.forEach((fn) => fn());
  nodes.get("align-rotation-reset").listeners.click.forEach((fn) => fn());
  assert.deepEqual(raised, [["scale", "100"], ["rotation", "0"]]);
  delete global.document;
});

test("a field the user is typing in is not overwritten by a re-render", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  const typing = nodes.get("align-scale");
  typing.value = "15";
  global.document.activeElement = typing;
  alignPanel.render({
    sequence: { name: "S" },
    transform: { clipName: "c", available: true, reason: null, fields: {
      position: { known: true, animated: false, x: 1, y: 2 }, scale: { known: true, animated: false, value: 100 },
      rotation: { known: true, animated: false, value: 0 }, anchor: { known: true, animated: false, x: 3, y: 4 } } },
    busy: false, status: { text: "Ready", level: "ready" },
  });
  assert.equal(typing.value, "15");
  assert.equal(nodes.get("align-rotation").value, "0");
  delete global.document;
});

test("index.html has nine anchor cells and six align buttons, each with a value the feature knows", () => {
  const { ANCHOR_TARGETS, ALIGN_EDGES } = require("../uxp/cutdeck/transform/geometry.js");
  const anchors = [...html.matchAll(/data-anchor="([^"]+)"/g)].map((m) => m[1]);
  const edges = [...html.matchAll(/data-align="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual([...anchors].sort(), Object.keys(ANCHOR_TARGETS).sort());
  assert.deepEqual([...edges].sort(), [...ALIGN_EDGES].sort());
});

test("index.html's Phase 6 controls carry values the feature knows: two align targets, four distributions", async () => {
  const targets = [...html.matchAll(/data-align-to="([^"]+)"/g)].map((m) => m[1]);
  const kinds = [...html.matchAll(/data-distribute="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(targets, ["frame", "selection"]);
  assert.deepEqual([...kinds].sort(), ["h-centers", "h-gaps", "v-centers", "v-gaps"]);
  // Each kind must be one distribute() accepts (it throws "Unknown distribution" otherwise; here
  // it fails on the missing project first, which proves only that the name was not rejected).
  const { distribute } = require("../uxp/cutdeck/features/align.js");
  for (const kind of kinds) {
    await assert.rejects(() => distribute({}, kind), (e) => !/Unknown distribution/.test(e.message));
  }
});

test("scrubby drag raises onSlideField with intermediate values and onCommitField on release", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  const slideCalls = [];
  const commitCalls = [];
  const winListeners = {};
  global.window = {
    addEventListener: (type, fn) => { (winListeners[type] = winListeners[type] || []).push(fn); },
    removeEventListener: (type, fn) => {
      winListeners[type] = (winListeners[type] || []).filter((h) => h !== fn);
    },
  };

  alignPanel.bind({
    onProbe() {}, onRefresh() {}, onSetField() {},
    onSlideField: (f, v) => slideCalls.push([f, v]),
    onCommitField: (f, v) => commitCalls.push([f, v]),
    onAnchor() {}, onAlign() {},
  });

  const scaleInput = nodes.get("align-scale");
  scaleInput.value = "100";
  // Pointerdown at x = 100
  scaleInput.listeners.pointerdown[0]({ clientX: 100, button: 0, preventDefault() {} });

  // Move by +10px (dx = 10, step = 1 -> nextVal = 110)
  winListeners.pointermove[0]({ clientX: 110 });
  assert.equal(scaleInput.value, "110");
  assert.deepEqual(slideCalls, [["scale", "110"]]);

  // Move by +20px (dx = 20 -> nextVal = 120)
  winListeners.pointermove[0]({ clientX: 120 });
  assert.equal(scaleInput.value, "120");
  assert.deepEqual(slideCalls, [["scale", "110"], ["scale", "120"]]);

  // Pointerup
  winListeners.pointerup[0]();
  assert.deepEqual(commitCalls, [["scale", "120"]]);

  delete global.window;
  delete global.document;
});

test("arrow keys raise onSlideField with stepped values", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  const slideCalls = [];
  alignPanel.bind({
    onProbe() {}, onRefresh() {}, onSetField() {},
    onSlideField: (f, v) => slideCalls.push([f, v]),
    onAnchor() {}, onAlign() {},
  });

  const rotInput = nodes.get("align-rotation");
  rotInput.value = "0";
  rotInput.listeners.keydown[0]({ key: "ArrowUp", preventDefault() {} });
  assert.equal(rotInput.value, "1");
  assert.deepEqual(slideCalls, [["rotation", "1"]]);

  rotInput.listeners.keydown[0]({ key: "ArrowDown", preventDefault() {} });
  assert.equal(rotInput.value, "0");
  assert.deepEqual(slideCalls, [["rotation", "1"], ["rotation", "0"]]);

  delete global.document;
});
