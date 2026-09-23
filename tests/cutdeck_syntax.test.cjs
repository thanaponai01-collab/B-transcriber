/* Every .js file the UXP panel loads must at least parse. main.js can't be require()d off-host
   (it needs "premierepro"), so a syntax error there passed every other test and only showed up
   in Premiere as a half-drawn, unclickable panel ("SyntaxError: Invalid or unexpected token"
   in UXPLogs, 2026-09-23). `node --check` parses without executing, so no host is needed. */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { execFileSync } = require("node:child_process");

const pluginDir = path.join(__dirname, "..", "uxp", "cutdeck");

function panelJsFiles(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === "package" || entry.name === "node_modules") continue;
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...panelJsFiles(p));
    else if (entry.name.endsWith(".js")) out.push(p);
  }
  return out;
}

const files = panelJsFiles(pluginDir);

test("the plugin has JS files to check", () => {
  assert.ok(files.some((f) => f.endsWith("main.js")));
});

for (const file of files) {
  test(`parses: ${path.relative(pluginDir, file)}`, () => {
    try {
      execFileSync(process.execPath, ["--check", file], { stdio: "pipe" });
    } catch (error) {
      assert.fail(String(error.stderr || error.message));
    }
  });
}
