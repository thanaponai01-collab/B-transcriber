/* The one CutDeck panel (docs/research/cutdeck-one-panel-plan.md): four tabs, a busy dot on the
   tab a job started on, Transform reads only on the Transform and Align tabs, the fx block
   reset, and the Align tab's frame drawing. Premiere's real layout stays a live check (plan
   step 8); this file proves the wiring and the arithmetic. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const html = fs.readFileSync(path.join(root, "uxp", "cutdeck", "index.html"), "utf8");
const mainJs = fs.readFileSync(path.join(root, "uxp", "cutdeck", "main.js"), "utf8");

// A small DOM: ids, classes, attributes, style, clientWidth, children, listeners.
function makeDom() {
  const nodes = new Map();
  function el(id, attrs = {}) {
    const classes = new Set();
    const attributes = { ...attrs };
    const listeners = {};
    const node = {
      id, hidden: false, disabled: false, children: [], parentElement: null, style: {}, clientWidth: 0,
      textContent: "",
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
      getAttribute: (n) => (n in attributes ? attributes[n] : null),
      setAttribute: (n, v) => { attributes[n] = String(v); },
      removeAttribute: (n) => { delete attributes[n]; },
      appendChild(child) { node.children.push(child); child.parentElement = node; return child; },
      querySelectorAll(sel) {
        const m = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(sel);
        const out = [];
        (function walk(n) {
          for (const c of n.children) {
            if (m && c.getAttribute(m[1]) !== null && (m[2] === undefined || c.getAttribute(m[1]) === m[2])) out.push(c);
            walk(c);
          }
        })(node);
        return out;
      },
      querySelector(sel) { return node.querySelectorAll(sel)[0] || null; },
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      click() { (listeners.click || []).forEach((fn) => fn({ stopPropagation() {} })); },
    };
    if (id) nodes.set(id, node);
    return node;
  }
  const doc = {
    getElementById: (id) => nodes.get(id) || null,
    querySelectorAll: () => [],
    addEventListener() {},
    createElement: () => el(null),
  };
  return { nodes, el, doc };
}

function fresh(modulePath) {
  delete require.cache[require.resolve(modulePath)];
  return require(modulePath);
}

// --- tabs ---------------------------------------------------------------------------------

const TAB_IDS = { edit: "tab-edit", adj: "tab-adj", transform: "tab-transform", align: "tab-align" };
const VIEW_IDS = ["view-edit", "view-adj", "view-transform", "view-align"];

function loadPanel() {
  const dom = makeDom();
  for (const id of [...Object.values(TAB_IDS), ...VIEW_IDS, "view-tools"]) dom.el(id);
  global.document = dom.doc;
  const panel = fresh("../uxp/cutdeck/core/panel.js");
  return { ...dom, panel };
}

test("index.html has the four tabs in order, and none carries data-act (busy never disables a tab)", () => {
  const order = [...html.matchAll(/id="(tab-[a-z]+)"/g)].map((m) => m[1]);
  assert.deepEqual(order, ["tab-edit", "tab-adj", "tab-transform", "tab-align"]);
  for (const id of order) {
    const tag = html.slice(html.lastIndexOf("<", html.indexOf(`id="${id}"`)), html.indexOf(">", html.indexOf(`id="${id}"`)));
    assert.equal(/data-act=/.test(tag), false, `${id} has a data-act`);
  }
});

test("the panel has no brand row and the sequence card sits in the Cut view", () => {
  assert.equal(/class="brand"/.test(html), false);
  const cut = html.slice(html.indexOf('id="view-edit"'), html.indexOf('id="view-adj"'));
  assert.ok(cut.includes('id="seq-card"'), "the sequence card is not in the Cut view");
  assert.ok(cut.includes('id="job-banner"'), "the resume banner is not in the Cut view");
});

test("clicking each tab raises onTab with its name", () => {
  const { nodes, panel } = loadPanel();
  const raised = [];
  panel.bind({ onTab: (name) => raised.push(name) });
  for (const id of Object.values(TAB_IDS)) nodes.get(id).click();
  assert.deepEqual(raised, ["edit", "adj", "transform", "align"]);
  delete global.document;
});

test("render shows exactly one view per tab, and #view-tools for Transform and Align", () => {
  const { nodes, panel } = loadPanel();
  for (const [tab, tabId] of Object.entries(TAB_IDS)) {
    panel.render({ tab, busy: false, status: { text: "Ready", level: "ready" } });
    const shown = VIEW_IDS.filter((id) => nodes.get(id).classList.contains("active"));
    assert.equal(shown.length, 1, `${tab}: ${shown}`);
    assert.equal(nodes.get(tabId).classList.contains("active"), true);
    assert.equal(nodes.get("view-tools").classList.contains("active"), tab === "transform" || tab === "align");
  }
  delete global.document;
});

test("the tab a job started on keeps a busy dot after switching tabs, and loses it when the job ends", () => {
  const { nodes, panel } = loadPanel();
  const status = { text: "Rough cut…", level: "busy" };
  panel.render({ tab: "edit", busy: true, status });
  panel.render({ tab: "align", busy: true, status });
  assert.equal(nodes.get("tab-edit").classList.contains("busy"), true);
  assert.equal(nodes.get("tab-align").classList.contains("busy"), false);
  panel.render({ tab: "align", busy: false, status: { text: "Done", level: "ready" } });
  assert.equal(nodes.get("tab-edit").classList.contains("busy"), false);
  delete global.document;
});

test("main.js remembers the tab, defaulting to FX when storage is missing or holds junk", () => {
  assert.match(mainJs, /tab: loadTab\(\)/);
  const body = mainJs.slice(mainJs.indexOf("function loadTab()"), mainJs.indexOf("function saveTab("));
  const loadTab = new Function("storage", "TABS", "TAB_KEY", `${body}; return loadTab();`);
  const TABS = ["edit", "adj", "transform", "align"];
  assert.equal(loadTab({ getItem: () => "align" }, TABS, "cutdeck.tab"), "align");
  assert.equal(loadTab({ getItem: () => "junk" }, TABS, "cutdeck.tab"), "adj");
  assert.equal(loadTab(null, TABS, "cutdeck.tab"), "adj");
  assert.equal(loadTab({ getItem: () => { throw new Error("blocked"); } }, TABS, "cutdeck.tab"), "adj");
});

// --- Transform reads follow the tab ---------------------------------------------------------

test("a transform poll reads nothing while neither Transform nor Align is showing", async () => {
  const { createAlignFeature } = fresh("../uxp/cutdeck/features/align.js");
  const { createController } = require("../uxp/cutdeck/features/controller.js");
  let reads = 0;
  const ppro = { Project: { getActiveProject: async () => { reads++; return null; } } };
  const ctl = createController({ render: () => {}, initialState: { sequence: null, frame: null, transform: null } });
  let tab = "edit";
  const align = createAlignFeature({ ppro, ctl, isMounted: () => tab === "transform" || tab === "align" });
  await align.poll();
  assert.equal(reads, 0, "polled Premiere on the Cut tab");
  tab = "align";
  await align.poll();
  assert.ok(reads > 0, "did not poll on the Align tab");
});

// --- Transform tab: fx blocks ---------------------------------------------------------------

function loadAlignPanel() {
  const dom = makeDom();
  const tools = dom.el("view-tools");
  global.document = dom.doc;
  global.window = undefined;
  return { ...dom, tools, alignPanel: fresh("../uxp/cutdeck/core/alignPanel.js") };
}

test("an fx block's header reset resets each of its rows, skipping a disabled row", () => {
  const { el, tools, alignPanel } = loadAlignPanel();
  const motion = tools.appendChild(el("fx-block-motion"));
  const header = motion.appendChild(el(null, { "data-act": "align-reset", "data-reset-block": "motion" }));
  for (const row of ["position", "scale", "rotation"]) {
    motion.appendChild(el(`reset-${row}`, { "data-act": "align-reset", "data-block": "motion", "data-reset": row }));
  }
  tools.appendChild(el("reset-opacity", { "data-act": "align-reset", "data-block": "opacity", "data-reset": "opacity" }));
  motion.children.find((c) => c.id === "reset-scale").disabled = true;
  const reset = [];
  alignPanel.bind({ onResetField: (row) => reset.push(row) });
  header.click();
  assert.deepEqual(reset, ["position", "rotation"]);
  delete global.document;
});

test("index.html: every Motion and Opacity row reset names its block, and Crop sits inside Motion", () => {
  const motion = html.slice(html.indexOf('id="fx-block-motion"'), html.indexOf('id="fx-block-opacity"'));
  const opacity = html.slice(html.indexOf('id="fx-block-opacity"'), html.indexOf('id="view-align"'));
  const rows = (part, block) => [...part.matchAll(new RegExp(`data-block="${block}" data-reset="([^"]+)"`, "g"))].map((m) => m[1]);
  assert.deepEqual(rows(motion, "motion"), ["position", "scale", "scale-width", "uniform-scale", "rotation", "anchor",
    "anti-flicker", "crop-left", "crop-top", "crop-right", "crop-bottom"]);
  assert.deepEqual(rows(opacity, "opacity"), ["opacity", "blend-mode"]);
});

test("folding an fx block hides its rows and flips its arrow", () => {
  const { el, tools, alignPanel } = loadAlignPanel();
  const block = tools.appendChild(el("fx-block-motion"));
  const toggle = block.appendChild(el(null, { "data-fold": "fx-block-motion" }));
  const arrow = toggle.appendChild(el(null, { class: "fx-arrow" }));
  toggle.querySelector = () => arrow;
  alignPanel.bind({});
  toggle.click();
  assert.equal(block.classList.contains("closed"), true);
  assert.equal(arrow.textContent, "▸");
  toggle.click();
  assert.equal(block.classList.contains("closed"), false);
  assert.equal(arrow.textContent, "▾");
  delete global.document;
});

// --- Align tab: the frame drawing -----------------------------------------------------------

function loadFrame(width) {
  const loaded = loadAlignPanel();
  const { el, tools } = loaded;
  const wrap = tools.appendChild(el("align-frame-wrap"));
  wrap.clientWidth = width;
  const frame = wrap.appendChild(el("align-frame"));
  for (const edge of ["left", "right", "top", "bottom", "hcenter", "vcenter"]) {
    frame.appendChild(el(`align-line-${edge}`, { "data-act": "align-edge", "data-align": edge }));
  }
  const box = frame.appendChild(el("align-clip-box"));
  for (const a of ["top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right"]) {
    box.appendChild(el(`dot-${a}`, { "data-act": "align-anchor", "data-anchor": a }));
  }
  return loaded;
}
const size = (node) => [node.style.width, node.style.height];
const at = (node) => [node.style.left, node.style.top];

test("the frame drawing takes a 16:9 sequence's shape at the full width", () => {
  const { nodes, alignPanel } = loadFrame(300);
  alignPanel.render({ frame: { width: 1920, height: 1080 }, transform: null, status: null });
  assert.deepEqual(size(nodes.get("align-frame")), ["300px", "169px"]);
  // Inside the 1px border: 298 x 167.
  assert.deepEqual(at(nodes.get("align-line-right")), ["286px", "0px"]);
  assert.deepEqual(at(nodes.get("align-line-bottom")), ["12px", "155px"]);
  delete global.document;
});

test("a 9:16 sequence is capped at 200px tall and drawn narrower", () => {
  const { nodes, alignPanel } = loadFrame(300);
  alignPanel.render({ frame: { width: 1080, height: 1920 }, transform: null, status: null });
  assert.deepEqual(size(nodes.get("align-frame")), ["113px", "200px"]);
  delete global.document;
});

test("with no sequence frame the drawing is 16:9, and nothing is laid out while the tab is hidden", () => {
  const shown = loadFrame(320);
  shown.alignPanel.render({ frame: null, transform: null, status: null });
  assert.deepEqual(size(shown.nodes.get("align-frame")), ["320px", "180px"]);
  delete global.document;

  const hidden = loadFrame(0);
  hidden.alignPanel.render({ frame: { width: 1920, height: 1080 }, transform: null, status: null });
  assert.deepEqual(size(hidden.nodes.get("align-frame")), [undefined, undefined]);
  delete global.document;
});

test("the nine anchor dots sit on the clip box's corners, edge midpoints and center", () => {
  const { nodes, alignPanel } = loadFrame(300);
  alignPanel.render({ frame: { width: 1920, height: 1080 }, transform: null, status: null });
  const box = nodes.get("align-clip-box");
  const boxW = parseFloat(box.style.width);
  const boxH = parseFloat(box.style.height);
  const center = nodes.get("dot-center");
  assert.equal(parseFloat(center.style.left) + 7.5, Math.round(boxW / 2 - 7.5) + 7.5);
  assert.equal(nodes.get("dot-bottom-right").style.top, `${Math.round(boxH - 7.5)}px`);
  assert.equal(nodes.get("dot-top-left").style.left, `${Math.round(-7.5)}px`);
  delete global.document;
});

test("each frame line and anchor dot raises the same intent and value the old buttons did", () => {
  const { nodes, alignPanel } = loadFrame(300);
  const aligned = [];
  const anchored = [];
  alignPanel.bind({ onAlign: (edge, to) => aligned.push(`${edge}/${to}`), onAnchor: (a) => anchored.push(a) });
  for (const edge of ["left", "hcenter", "right", "top", "vcenter", "bottom"]) nodes.get(`align-line-${edge}`).click();
  nodes.get("dot-bottom-right").click();
  assert.deepEqual(aligned, ["left/frame", "hcenter/frame", "right/frame", "top/frame", "vcenter/frame", "bottom/frame"]);
  assert.deepEqual(anchored, ["bottom-right"]);
  delete global.document;
});

// --- ⋯ menu and Settings --------------------------------------------------------------------

test("every probe except Copy Status sits under the menu's Probes item", () => {
  const sub = html.slice(html.indexOf('id="menu-probes"'), html.indexOf('id="menu-item-reload"'));
  const all = [...html.matchAll(/data-probe="([^"]+)"/g)].map((m) => m[1]);
  const folded = [...sub.matchAll(/data-probe="([^"]+)"/g)].map((m) => m[1]);
  assert.deepEqual(folded, all.filter((p) => p !== "copystatus"));
  assert.ok(folded.length >= 10, "expected the probes to be folded");
});

test("Settings no longer carries the shortcuts guide; the FX tab has its one-line hint", () => {
  assert.equal(/setting-help-box/.test(html), false);
  const fx = html.slice(html.indexOf('id="view-adj"'), html.indexOf('id="view-tools"'));
  assert.match(fx, /class="view-hint">Click spans all · Ctrl each clip · Shift every cut</);
});
