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
  el("align-sequence");
  el("align-status");
  el("align-status-icon");
  el("align-transform-clip");
  el("align-transform-reason");
  el("align-transform-fields");
  el("align-position");
  el("align-scale");
  el("align-rotation");
  el("align-anchor");

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

test("render writes the sequence name, the status, and disables controls while busy", () => {
  const { nodes, probe } = makeStub();
  const alignPanel = loadAlignPanel();

  alignPanel.render({ sequence: { name: "CFD 94" }, busy: true, status: { text: "Working…", level: "busy" } });
  assert.equal(nodes.get("align-sequence").textContent, "CFD 94");
  assert.equal(nodes.get("align-status").textContent, "Working…");
  assert.equal(nodes.get("align-status-icon").className.includes("busy"), true);
  assert.equal(probe.disabled, true, "controls must be disabled while a job runs");

  alignPanel.render({ sequence: null, busy: false, status: { text: "Ready", level: "ready" } });
  assert.equal(nodes.get("align-sequence").textContent, "No sequence open");
  assert.equal(nodes.get("align-status-icon").className.includes("busy"), false);
  assert.equal(probe.disabled, false);
  delete global.document;
});

// --- Phase 1: renderTransform (docs/research/cutdeck-transform-panel-plan.md) --------------

test("renderTransform shows 'No sequence open' and hides both the reason and the field grid when transform is null", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  alignPanel.render({ sequence: null, transform: null, busy: false, status: { text: "Ready", level: "ready" } });
  assert.equal(nodes.get("align-transform-clip").textContent, "No sequence open");
  assert.equal(nodes.get("align-transform-reason").hidden, true);
  assert.equal(nodes.get("align-transform-fields").hidden, true);
  delete global.document;
});

test("renderTransform shows the reason and hides the field grid when the clip has no readable Transform", () => {
  const { nodes } = makeStub();
  const alignPanel = loadAlignPanel();
  alignPanel.render({
    sequence: { name: "CFD 94" },
    transform: { clipName: "AudioOnly.wav", available: false, reason: "This item has no readable Transform.", fields: null },
    busy: false, status: { text: "Ready", level: "ready" },
  });
  assert.equal(nodes.get("align-transform-clip").textContent, "AudioOnly.wav");
  assert.equal(nodes.get("align-transform-reason").textContent, "This item has no readable Transform.");
  assert.equal(nodes.get("align-transform-reason").hidden, false);
  assert.equal(nodes.get("align-transform-fields").hidden, true);
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
  assert.equal(nodes.get("align-transform-clip").textContent, "No clip selected");
  assert.equal(nodes.get("align-transform-reason").textContent, "Select a clip on the timeline.");
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
  assert.equal(nodes.get("align-transform-fields").hidden, false);
  assert.equal(nodes.get("align-transform-reason").hidden, true);
  assert.equal(nodes.get("align-position").textContent, "-510.8, 44.9 px");
  assert.equal(nodes.get("align-scale").textContent, "162%");
  assert.equal(nodes.get("align-rotation").textContent, "0°");
  assert.equal(nodes.get("align-anchor").textContent, "2, 60.5 px");
  delete global.document;
});

test("renderTransform shows 'Animated (keyframed)' for a time-varying field instead of a possibly-wrong static number", () => {
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
  assert.equal(nodes.get("align-position").textContent, "Animated (keyframed)");
  assert.equal(nodes.get("align-scale").textContent, "100%");
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
  assert.equal(nodes.get("align-position").textContent, "—");
  assert.equal(nodes.get("align-rotation").textContent, "—");
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
  assert.match(alignFeatureJs, /readSourceFrameSize\(ppro, item\)/);
  assert.match(alignFeatureJs, /anchorFrame = await transformParams\.readSourceFrameSize\(ppro, item\)/);
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
