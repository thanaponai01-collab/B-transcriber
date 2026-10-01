/* The Settings page shows only settings something reads, and every captured preset gets a quick
   button. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const { createAdjustFeature, DEFAULT_SETTINGS } = require("../uxp/cutdeck/features/adjust.js");

test("there is no Project Bin setting: nothing reads it, so the page must not offer it", () => {
  const html = fs.readFileSync(path.join(__dirname, "../uxp/cutdeck/index.html"), "utf8");
  assert.equal(html.includes('id="setting-bin"'), false);
  assert.equal(Object.prototype.hasOwnProperty.call(DEFAULT_SETTINGS, "bin"), false);
  const ctl = { state: { settings: { ...DEFAULT_SETTINGS } }, render() {} };
  createAdjustFeature({ ppro: {}, ctl, storage: null }).applySettingChange({ bin: "Elsewhere", frames: 8 });
  assert.equal(ctl.state.settings.frames, 8);
  assert.equal("bin" in ctl.state.settings, false);
});

function fakeDom() {
  const make = () => {
    const attrs = {};
    const el = { children: [], attrs, className: "", textContent: "", title: "",
      setAttribute: (k, v) => { attrs[k] = String(v); }, getAttribute: (k) => (k in attrs ? attrs[k] : null),
      appendChild(child) { el.children.push(child); return child; },
      classList: { contains: (c) => el.className.split(/\s+/).includes(c), add() {}, remove() {}, toggle() {} } };
    let html = "";
    Object.defineProperty(el, "innerHTML", { get: () => html, set: (v) => { html = v; if (v === "") el.children = []; } });
    return el;
  };
  const container = make();
  global.document = { getElementById: (id) => (id === "fx-preset-buttons" ? container : null),
    createElement: make, querySelectorAll: () => [] };
  return container;
}

test("every captured preset gets a quick button, rounding the grid up to whole rows of three", () => {
  const container = fakeDom();
  delete require.cache[require.resolve("../uxp/cutdeck/core/panel.js")];
  const panel = require("../uxp/cutdeck/core/panel.js");
  const presets = (n) => Array.from({ length: n }, (_, i) => ({ id: `fx-${i}`, name: `P${i}` }));
  const named = () => container.children.filter((c) => c.getAttribute("data-preset-id")).map((c) => c.textContent);
  try {
    panel.render({ customPresets: presets(2) });
    assert.equal(container.children.length, 9, "a fresh panel keeps its 3x3 grid");
    panel.render({ customPresets: presets(10) });
    assert.equal(named().length, 10, "the tenth preset has no button");
    assert.equal(container.children.length, 12);
  } finally {
    delete global.document;
  }
});
