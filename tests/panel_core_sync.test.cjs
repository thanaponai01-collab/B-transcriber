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
