const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function harness() {
  const hooks = new Map(), messages = [];
  class Pointer {
    constructor(value, pointer = null) { this.value = value; this.pointer = pointer; }
    add(n) { return new Pointer(this.value + n); }
    readByteArray(n) {
      const bytes = this.value === 0x195a3b50 ? [0x48, 0x8b, 0xc4]
        : this.value === 0x1ba78320 ? [0x48, 0x89, 0x5c, 0x24, 0x18]
        : this.value === 0x199b6410 ? [0x48, 0x8b, 0x09, 0x48, 0x85, 0xc9] : Array(n).fill(0);
      return Uint8Array.from(bytes).buffer;
    }
    readPointer() { return this.pointer || new Pointer(0); }
    readU32() { return 0x11223344; }
    toUInt32() { return this.value; }
    isNull() { return this.value === 0; }
    toString() { return String(this.value); }
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../tools/native-text-bounds/trace-document-layout.js'), 'utf8'), {
    Process: { getModuleByName: () => ({ base: new Pointer(0) }) },
    Checksum: { compute: () => 'hash' },
    Interceptor: { attach: (p, callbacks) => hooks.set(p.value, callbacks) },
    send: message => messages.push(message),
  });
  const document = new Pointer(123);
  const factory = hooks.get(0x195a3b50), layout = hooks.get(0x1ba78320);
  const create = () => {
    const context = {};
    factory.onEnter.call(context, [new Pointer(10, document), new Pointer(20), new Pointer(372)]);
    factory.onLeave.call(context);
  };
  const enterLayout = () => {
    const context = {};
    layout.onEnter.call(context, [new Pointer(10), new Pointer(20, new Pointer(30, document))]);
    return context;
  };
  const leaveLayout = context => { layout.onLeave.call(context); return messages.at(-1); };
  const destroy = () => hooks.get(0x199b6410).onEnter([document]);
  return { create, enterLayout, leaveLayout, destroy };
}

test('destroyed document cannot retain a source ID at a reused address', () => {
  const h = harness();
  h.create();
  assert.equal(h.leaveLayout(h.enterLayout()).sourceId, 1);
  h.destroy();
  assert.equal(h.leaveLayout(h.enterLayout()).sourceId, null);
});

test('replacement during layout invalidates its captured generation', () => {
  const h = harness();
  h.create();
  const pending = h.enterLayout();
  h.destroy(); h.create();
  assert.equal(h.leaveLayout(pending).sourceId, null);
  assert.equal(h.leaveLayout(h.enterLayout()).sourceId, 2);
});

test('factory capture cap invalidates the previous address mapping', () => {
  const h = harness();
  for (let i = 0; i < 512; i++) h.create();
  assert.equal(h.leaveLayout(h.enterLayout()).sourceId, 512);
  h.create();
  assert.equal(h.leaveLayout(h.enterLayout()).sourceId, null);
});
