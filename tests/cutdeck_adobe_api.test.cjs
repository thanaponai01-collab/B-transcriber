/* Every member name the UXP panel reads must exist in Adobe's typings or docs
   (reference/adobe/), JS/DOM built-ins, CutDeck's own code or the helper's reply fields.
   A name found in none of them was written from memory: CLAUDE.md rule 2, as a test.
   Runs tools/adobe/check-api.mjs, which needs TypeScript: `npm ci --prefix tools/adobe` once. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const root = path.join(__dirname, "..");
const script = path.join(root, "tools", "adobe", "check-api.mjs");

function check(extraArgs = []) {
  if (!fs.existsSync(path.join(root, "tools", "adobe", "node_modules", "typescript"))) {
    assert.fail("TypeScript is not installed for the API check. Run: npm ci --prefix tools/adobe");
  }
  return JSON.parse(execFileSync(process.execPath, [script, "--json", ...extraArgs], { encoding: "utf8" }));
}

test("every member name the panel reads is accounted for", () => {
  const r = check();
  assert.ok(r.files > 10, "panel files were found");
  assert.deepEqual(r.unknown.map((u) => `${u.name} at ${u.where}`), []);
  assert.deepEqual(r.staleAllow, [], "allowlist entries that are now known elsewhere should be removed");
});

test("an API written from memory is caught", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cutdeck-api-"));
  try {
    fs.writeFileSync(path.join(dir, "bad.js"), [
      'const ppro = require("premierepro");',
      "async function go(seq) {",
      "  const editor = ppro.SequenceEditor.getEditor(seq);", // real
      "  return editor.createRazorAtPlayheadAction(seq);",    // invented
      "}",
      "module.exports = { go };",
    ].join("\n"));
    const r = check([`--panel=${dir}`]);
    assert.deepEqual(r.unknown.map((u) => u.name), ["createRazorAtPlayheadAction"]);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
