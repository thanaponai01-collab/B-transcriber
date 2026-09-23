const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const panelJsPath = path.join(root, "uxp", "cutdeck", "core", "panel.js");
const panelJsSource = fs.readFileSync(panelJsPath, "utf8");
const uxpHtmlPath = path.join(root, "uxp", "cutdeck", "index.html");
const uxpHtml = fs.readFileSync(uxpHtmlPath, "utf8");

/* The UI seam is one file PER PANEL DOCUMENT, not one file forever. Premiere gives a plugin a
   single main HTML document however many panel entrypoints it declares, so both panels share
   index.html — but each owns its own seam module, and DOM access stays confined to these.
   Adding a name here is a deliberate architectural decision (see docs/arch-design-panel-ui.md),
   never a way to quiet this test: anything listed must also be held to the id-resolution and
   render-idempotence tests below. */
const UI_SEAM_FILES = ["core/panel.js", "core/alignPanel.js"];

function idsInHtml(html) {
  return new Set([...html.matchAll(/\bid="([a-zA-Z0-9_-]+)"/g)].map((m) => m[1]));
}
const uxpIds = idsInHtml(uxpHtml);

test("every $(\"id\") in core/panel.js resolves to an id in uxp/cutdeck/index.html", () => {
  const ids = new Set([...panelJsSource.matchAll(/\$\("([a-zA-Z0-9_-]+)"\)/g)].map((m) => m[1]));
  assert.ok(ids.size > 30, "expected panel.js to reference a substantial number of ids");
  const uxpMisses = [];
  for (const id of ids) {
    if (!uxpIds.has(id)) uxpMisses.push(id);
  }
  assert.deepEqual(uxpMisses, [], `panel.js references ids missing from uxp/cutdeck/index.html: ${uxpMisses}`);
});

test(`getElementById/classList/textContent/addEventListener appear in no panel file except ${UI_SEAM_FILES.join(", ")}`, () => {
  const uxpDir = path.join(root, "uxp", "cutdeck");
  const jsFiles = [];
  (function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(p);
      else if (entry.name.endsWith(".js")) jsFiles.push(p);
    }
  })(uxpDir);

  const seamPaths = UI_SEAM_FILES.map((rel) => path.resolve(path.join(uxpDir, rel)));
  const domPatterns = [/getElementById\(/, /\.classList\b/, /\.textContent\b/, /\baddEventListener\(/];
  const offenders = [];
  for (const file of jsFiles) {
    if (seamPaths.includes(path.resolve(file))) continue;
    const text = fs.readFileSync(file, "utf8");
    if (domPatterns.some((re) => re.test(text))) offenders.push(path.relative(root, file));
  }
  assert.deepEqual(offenders, [], `DOM touches found outside the UI seam: ${offenders}`);
});

test("every seam file named in the allowlist actually exists", () => {
  // Guards the allowlist itself: a typo here would silently exempt nothing (harmless) or, on a
  // rename, silently exempt a file that no longer exists while the real one goes unchecked.
  for (const rel of UI_SEAM_FILES) {
    assert.ok(fs.existsSync(path.join(root, "uxp", "cutdeck", rel)), `uxp/cutdeck/${rel} missing`);
  }
});

test("no #rrggbb literal outside core/theme.css (within uxp/cutdeck)", () => {
  const uxpDir = path.join(root, "uxp", "cutdeck");
  const files = [];
  (function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const p = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(p);
      else if (/\.(js|html|css)$/.test(entry.name) && entry.name !== "theme.css") files.push(p);
    }
  })(uxpDir);

  const hexPattern = /#[0-9a-fA-F]{6}\b/;
  const offenders = [];
  for (const file of files) {
    const text = fs.readFileSync(file, "utf8");
    if (hexPattern.test(text)) offenders.push(path.relative(root, file));
  }
  assert.deepEqual(offenders, [], `hex color literals found outside theme.css: ${offenders}`);
});

test("panel.render is idempotent: a second call with the same state mutates nothing further", () => {
  const { document, elementSnapshot } = makeDomStub();
  global.document = document;
  global.window = { location: { reload: () => {} } };
  global.navigator = {};
  delete require.cache[require.resolve("../uxp/cutdeck/core/panel.js")];
  const panel = require("../uxp/cutdeck/core/panel.js");

  const fixtureState = {
    sequence: { name: "Sequence 1", inSeconds: 12.5, outSeconds: 45.75, audioTrackCount: 2 },
    tab: "edit",
    cutMode: "silence",
    audioTrack: 1,
    settings: {
      frames: 20, bin: "MyBin", color: "Mango", clamp: false, activeFx: "Zoom Out",
      fxList: ["Zoom In", "Zoom Out", "Whip Pan L"],
    },
    job: { id: "job-1", state: "running" },
    busy: true,
    status: { text: "Working…", level: "busy" },
  };

  panel.render(fixtureState);
  const after1 = elementSnapshot();
  panel.render(fixtureState);
  const after2 = elementSnapshot();

  assert.deepEqual(after2, after1, "render(state) called twice must leave the DOM stub unchanged");

  delete global.document;
  delete global.window;
  delete global.navigator;
});

// --- a minimal, hand-rolled DOM stub -----------------------------------------------------
// No jsdom in this repo (no build step, no new runtime deps per CLAUDE.md) — this covers
// exactly the subset of the DOM API core/panel.js uses.

function makeDomStub() {
  const elements = [];

  function makeElement(id, tag) {
    let text = "";
    const classes = new Set();
    const attributes = {};
    const listeners = {};
    const el = {
      id,
      tagName: tag || "div",
      value: "",
      checked: false,
      hidden: false,
      disabled: false,
      children: [],
      parentElement: null,
      get textContent() { return text; },
      set textContent(v) { text = String(v); },
      get innerHTML() { return ""; },
      set innerHTML(_v) { el.children = []; },
      classList: {
        add: (...cls) => cls.forEach((c) => classes.add(c)),
        remove: (...cls) => cls.forEach((c) => classes.delete(c)),
        toggle(c, force) {
          const has = classes.has(c);
          const want = force === undefined ? !has : !!force;
          if (want) classes.add(c); else classes.delete(c);
          return want;
        },
        contains: (c) => classes.has(c),
      },
      get className() { return Array.from(classes).join(" "); },
      getAttribute(name) {
        return Object.prototype.hasOwnProperty.call(attributes, name) ? attributes[name] : null;
      },
      setAttribute(name, v) { attributes[name] = String(v); },
      removeAttribute(name) { delete attributes[name]; },
      appendChild(child) { el.children.push(child); child.parentElement = el; return child; },
      contains(other) {
        let n = other;
        while (n) { if (n === el) return true; n = n.parentElement; }
        return false;
      },
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    };
    return el;
  }

  // Every id core/panel.js references via $(...), plus a few `.pill-mini` and `[data-act]`
  // fixtures so render()'s querySelectorAll paths have something to walk.
  const ids = [
    "audio", "badge-active-fx", "badge-active-fx-text", "badge-transition",
    "badge-transition-text", "btn-adj", "btn-capture-preset", "btn-fx", "close-settings",
    "copystatus", "cut", "dismiss", "dot", "frame-dec", "frame-inc", "job-banner",
    "menu-item-reload", "menu-item-settings", "mode", "overflow-menu", "pill-silence",
    "pill-speech", "range", "refresh", "resume", "seq-card", "sequence", "setting-active-fx",
    "setting-bin", "setting-clamp", "setting-color", "setting-frames", "settings-modal",
    "status", "status-icon", "sync", "tab-adj", "tab-edit", "timingprobe",
    "tools-toggle", "view-adj", "view-edit",
  ];
  const dataActIds = new Set([
    "audio", "badge-active-fx", "badge-transition", "btn-adj",
    "btn-capture-preset", "btn-fx", "copystatus", "cut", "frame-dec", "frame-inc",
    "menu-item-reload", "menu-item-settings", "mode", "pill-silence", "pill-speech",
    "refresh", "seq-card", "setting-active-fx", "setting-bin", "setting-clamp",
    "setting-color", "setting-frames", "sync", "tab-adj", "tab-edit",
    "timingprobe", "tools-toggle",
  ]);

  ids.forEach((id) => {
    const tag = id === "mode" || id === "audio" || id === "setting-color" || id === "setting-active-fx"
      ? "select" : "div";
    const el = makeElement(id, tag);
    if (dataActIds.has(id)) el.setAttribute("data-act", id);
    elements.push(el);
  });

  for (let i = 0; i < 5; i++) {
    const frames = [8, 12, 16, 20, 24][i];
    const mini = makeElement(undefined, "div");
    mini.classList.add("pill-mini");
    mini.setAttribute("data-frames", String(frames));
    mini.setAttribute("data-act", "pill-mini");
    elements.push(mini);
  }

  const byId = new Map(elements.map((e) => [e.id, e]));
  const docListeners = {};

  const document = {
    getElementById: (id) => byId.get(id) || null,
    querySelectorAll: (selector) => {
      if (selector === "[data-act]") return elements.filter((e) => e.getAttribute("data-act") !== null);
      if (selector === ".pill-mini") return elements.filter((e) => e.className.split(" ").includes("pill-mini"));
      return [];
    },
    createElement: (tag) => {
      const el = makeElement(undefined, tag);
      elements.push(el);
      return el;
    },
    addEventListener: (type, fn) => { (docListeners[type] = docListeners[type] || []).push(fn); },
  };

  function elementSnapshot() {
    return elements.map((e) => ({
      id: e.id,
      textContent: e.textContent,
      value: e.value,
      checked: e.checked,
      hidden: e.hidden,
      disabled: e.disabled,
      className: e.className,
      childCount: e.children.length,
    }));
  }

  return { document, elementSnapshot };
}
