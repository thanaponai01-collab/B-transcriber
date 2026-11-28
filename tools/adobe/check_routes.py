"""CLAUDE.md rule 2 for routes: every command in the table cutdeck/driver_commands.py (family code in
cutdeck/commands/) takes only routes proven live, and none that is off limits.

    python tools/adobe/check_routes.py [--json] [--commands MODULE] [--facts PATH]

Fails (exit 1) when a command has no LIVE row with a Premiere version in docs/PREMIERE_FACTS.md
"Route proof per command", when its row names other routes than the command declares, when it
declares an off-limits or unknown route, or when the code it reaches names Premiere's first-party
scripting (hSLScripting, the built-in MCP server). Run by tests/cutdeck_route_proof.test.cjs.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SECTION = "## Route proof per command"
# First-party only: PREMIERE_FACTS "UXP platform" rows on hSLScripting and the built-in MCP server.
OFF_LIMITS = {"first_party_mcp", "hsl_scripting"}
OFF_LIMITS_CODE = re.compile(r"hSLScripting|EnableMCPServer|(?:localhost|127\.0\.0\.1|::1)\W{1,4}3111\b")
# Panel code that names first-party scripting yet no agent command can run: the "List Premiere MCP
# Tools" probe, a button only the user clicks. The helper's run_probe list must leave it out.
PANEL_ONLY = {"uxp/cutdeck/mcpToolsProbe.js": "mcptools"}
ROW = re.compile(r"^\|\s*`([A-Za-z0-9_]+)`\s*\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|([^|]*)\|\s*$")


def proof_rows(facts: Path) -> tuple[dict[str, dict], list[str]]:
    text = facts.read_text(encoding="utf-8")
    start = text.find(SECTION)
    if start < 0:
        return {}, []
    body = text[start + len(SECTION):]
    end = body.find("\n## ")
    rows, repeated = {}, []
    for line in (body if end < 0 else body[:end]).splitlines():
        m = ROW.match(line)
        if m:
            name, routes, status, version, date, proof = (g.strip() for g in m.groups())
            if name in rows:
                repeated.append(name)
            rows[name] = {"routes": tuple(r.strip() for r in routes.split(",") if r.strip()),
                          "status": status, "version": version, "date": date, "proof": proof}
    return rows, repeated


def code_files() -> list[Path]:
    """Everything a command can reach: all helper code and all panel code."""
    return sorted(ROOT.glob("cutdeck/**/*.py")) + sorted(p for p in ROOT.glob("uxp/cutdeck/**/*.js") if "node_modules" not in p.parts)


def check(commands_module: str, facts: Path) -> dict:
    sys.path.insert(0, str(ROOT))
    if commands_module.endswith(".py"):  # a test's stand-in table
        spec = importlib.util.spec_from_file_location("commands_under_test", commands_module)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    else:
        module = importlib.import_module(commands_module)
    commands, routes = module.COMMANDS, module.ROUTES
    rows, repeated = proof_rows(facts)
    problems = [f"{name}: more than one row" for name in repeated]
    for name, command in commands.items():
        declared = tuple(command.routes)
        for route in declared:
            if route in OFF_LIMITS:
                problems.append(f"{name}: route {route} is off limits")
            elif route not in routes:
                problems.append(f"{name}: route {route} is not one of ROUTES")
        if command.run is not None and OFF_LIMITS_CODE.search(inspect.getsource(command.run)):
            problems.append(f"{name}: its code reaches Premiere's first-party scripting")
        row = rows.get(name)
        if row is None:
            problems.append(f"{name}: no row in PREMIERE_FACTS \"Route proof per command\"")
            continue
        if row["status"] != "LIVE":
            problems.append(f"{name}: status {row['status']!r}, not LIVE")
        if not re.fullmatch(r"\d+\.\d+(\.\d+)*", row["version"]):
            problems.append(f"{name}: no Premiere version ({row['version']!r})")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["date"]) or not row["proof"]:
            problems.append(f"{name}: needs a date and a proof")
        if set(row["routes"]) != set(declared):
            problems.append(f"{name}: row says routes {', '.join(row['routes'])}, command declares {', '.join(declared)}")
    for name in rows.keys() - commands.keys():
        problems.append(f"{name}: row for a command that does not exist")
    for f in [Path(module.__file__)] + code_files():
        rel = f.resolve().relative_to(ROOT).as_posix() if f.resolve().is_relative_to(ROOT) else str(f)
        if rel not in PANEL_ONLY and OFF_LIMITS_CODE.search(f.read_text(encoding="utf-8")):
            problems.append(f"{rel}: names Premiere's first-party scripting")
    probe_gate = inspect.getsource(module._run_probe_arguments)
    for rel, probe in PANEL_ONLY.items():
        if f'"{probe}"' in probe_gate:
            problems.append(f"run_probe: lets agents run the {probe} probe ({rel})")
    return {"commands": len(commands), "rows": len(rows), "problems": problems}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--commands", default="cutdeck.driver_commands")
    parser.add_argument("--facts", type=Path, default=ROOT / "docs/PREMIERE_FACTS.md")
    args = parser.parse_args()
    result = check(args.commands, args.facts)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"{result['commands']} commands, {result['rows']} proof rows")
        for problem in result["problems"]:
            print("  " + problem)
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
