/* Typed-field edge cases: a bad frame count snaps back, and Enter on a Transform field
   commits once (Enter runs exitEditMode AND the browser then fires a change event). */
const test = require("node:test");
const assert = require("node:assert/strict");

function stubInput(attrs = {}) {
  const listeners = {};
  return {
    value: "", disabled: false, parentElement: null, listeners,
    getAttribute: (n) => (n in attrs ? attrs[n] : null),
    addEventListener(t, fn) { (listeners[t] = listeners[t] || []).push(fn); },
  };
}

test("an invalid frame count snaps the box back to the current setting", () => {
  const frames = stubInput();
  global.document = { getElementById: (id) => (id === "setting-frames" ? frames : null),
    querySelectorAll: () => [], createElement: () => ({}), addEventListener() {} };
  try {
    delete require.cache[require.resolve("../uxp/cutdeck/core/panel.js")];
    const panel = require("../uxp/cutdeck/core/panel.js");
    const raised = [];
    panel.bind({ onSettingChange: (s) => raised.push(s) });
    panel.render({ settings: { frames: 16 } });
    frames.value = "abc";
    frames.listeners.change.forEach((fn) => fn({ target: frames }));
    assert.deepEqual(raised, []);
    assert.equal(String(frames.value), "16");
    frames.value = "500";
    frames.listeners.change.forEach((fn) => fn({ target: frames }));
    assert.equal(String(frames.value), "16");
  } finally {
    delete global.document;
  }
});

test("Enter on a Transform field raises onSetField once, not twice", () => {
  const input = stubInput({ "data-field": "rotation" });
  const classes = new Set(["active-editing"]);
  input.parentElement = { addEventListener() {}, querySelector: () => null,
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) } };
  global.document = { getElementById: (id) => (id === "align-rotation" ? input : null) };
  global.window = undefined;
  try {
    delete require.cache[require.resolve("../uxp/cutdeck/core/alignPanel.js")];
    const alignPanel = require("../uxp/cutdeck/core/alignPanel.js");
    const raised = [];
    alignPanel.bind({ onProbe() {}, onRefresh() {}, onSetField: (f, v) => raised.push([f, v]), onAnchor() {}, onAlign() {} });
    input.value = "5";
    input.listeners.keydown.forEach((fn) => fn({ key: "Enter" }));
    input.listeners.change.forEach((fn) => fn({ target: input }));
    input.listeners.blur.forEach((fn) => fn());
    assert.deepEqual(raised, [["rotation", "5"]]);
  } finally {
    delete global.document;
    delete global.window;
  }
});
