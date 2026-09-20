const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const source = path.join(root, "panel", "core");
const mirrors = ["cep/cutdeck/client/core", "uxp/cutdeck/core"];

for (const mirror of mirrors) {
  test(`${mirror} matches panel/core (run scripts/sync_panel_core.py)`, () => {
    const files = fs.readdirSync(source).filter((f) => f.endsWith(".js"));
    assert.ok(files.length >= 2);
    for (const name of files) {
      const a = fs.readFileSync(path.join(source, name), "utf8").replace(/\r\n/g, "\n");
      const b = fs.readFileSync(path.join(root, mirror, name), "utf8").replace(/\r\n/g, "\n");
      assert.equal(b, a, `${mirror}/${name} drifted from panel/core/${name}`);
    }
  });
}

/* Wiring: every shared-module reference in a panel file must resolve to a real file next to it. */
const callers = [
  "cep/cutdeck/client/main.js", "cep/cutdeck/client/helper_manager.js",
  "cep/cutdeck/client/index.html", "uxp/cutdeck/main.js",
];
for (const caller of callers) {
  test(`${caller} references only existing shared modules`, () => {
    const text = fs.readFileSync(path.join(root, caller), "utf8");
    const refs = [...text.matchAll(/(?:require\("|src=")(\.\/)?((?:core\/)?(?:rpc|progressText|progress_text)\.js)"/g)]
      .map((m) => m[2]);
    assert.ok(refs.length >= 1, `${caller} no longer references a shared module`);
    for (const ref of refs) {
      assert.ok(fs.existsSync(path.join(root, path.dirname(caller), ref)), `${caller} -> ${ref} not found`);
    }
  });
}
