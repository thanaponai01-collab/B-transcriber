/* Every Premiere command an agent can run takes only routes proven live, and none that is off
   limits: CLAUDE.md rule 2 for routes, as a test. Runs tools/adobe/check_routes.py, which reads
   cutdeck/driver_commands.py (Command.routes) and docs/PREMIERE_FACTS.md "Route proof per command". */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");

const root = path.join(__dirname, "..");
const script = path.join(root, "tools", "adobe", "check_routes.py");

function check(extraArgs = []) {
  const run = spawnSync("python", [script, "--json", ...extraArgs], { cwd: root, encoding: "utf8" });
  assert.ok(run.stdout, `check_routes.py printed nothing:\n${run.stderr}`);
  return JSON.parse(run.stdout);
}

test("every command has a LIVE route proof and no off-limits route", () => {
  const r = check();
  assert.ok(r.commands > 40, "the command table was read");
  assert.deepEqual(r.problems, []);
});

test("an unproven command, an off-limits route and first-party scripting in a command's code are caught", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cutdeck-routes-"));
  try {
    const table = path.join(dir, "commands.py");
    fs.writeFileSync(table, [
      "import dataclasses",
      "from cutdeck import driver_commands as base",
      "ROUTES = base.ROUTES",
      "_run_probe_arguments = base._run_probe_arguments",
      "COMMANDS = dict(base.COMMANDS)",
      'COMMANDS["fake_unproven"] = dataclasses.replace(base.COMMANDS["read_sequence"])',
      'COMMANDS["fake_off_limits"] = dataclasses.replace(base.COMMANDS["read_sequence"], routes=("first_party_mcp",))',
      'COMMANDS["fake_hsl"] = dataclasses.replace(base.COMMANDS["screenshot"],',
      '    run=lambda args, premiere: premiere("hSLScripting.MCP.razorTrackItems", args))',
    ].join("\n"));
    const r = check([`--commands=${table}`]);
    assert.ok(r.problems.includes('fake_unproven: no row in PREMIERE_FACTS "Route proof per command"'), r.problems.join("\n"));
    assert.ok(r.problems.includes("fake_off_limits: route first_party_mcp is off limits"), r.problems.join("\n"));
    assert.ok(r.problems.includes("fake_hsl: its code reaches Premiere's first-party scripting"), r.problems.join("\n"));
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("a proof row that is not LIVE, has no Premiere version, or names other routes is caught", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "cutdeck-routes-"));
  try {
    const facts = path.join(dir, "facts.md");
    const text = fs.readFileSync(path.join(root, "docs", "PREMIERE_FACTS.md"), "utf8")
      .replace(/^\| `set_speed` \| [^|]+\| LIVE \|/m, "| `set_speed` | premiere_ui, menu, uxp | OPEN |")
      .replace(/^(\| `nest_clips` \| [^|]+\| LIVE \|) 27\.0\.0 \|/m, "$1 unknown |")
      .replace(/^\| `menu_command` \| menu, uxp \|/m, "| `menu_command` | menu |");
    fs.writeFileSync(facts, text);
    const r = check([`--facts=${facts}`]);
    assert.deepEqual(r.problems, [
      "set_speed: status 'OPEN', not LIVE",
      "nest_clips: no Premiere version ('unknown')",
      "menu_command: row says routes menu, command declares menu, uxp",
    ]);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
