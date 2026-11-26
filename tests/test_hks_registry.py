"""The HKS rule registry (projects/hks/registry/) is valid, consistent, and the files generated from it are current.

The --check test is the hand-edit guard: this repo has no CI workflow, so pytest runs it.
"""
import copy
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from cutdeck import hks_registry

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / hks_registry.REGISTRY
SCHEMA = REGISTRY / "rules.schema.json"
GATES = ROOT / "projects/hks/gates/registry.json"
BUILD = ROOT / "tools/hks_registry_build.py"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def problems(reg):
    """Schema errors plus the cross-references a schema can't express."""
    schema = load(SCHEMA)
    Draft202012Validator.check_schema(schema)
    top = {k: v for k, v in reg.items() if k != "rules"}
    registry_schema = {"$ref": "#/$defs/registry", "$defs": schema["$defs"]}
    out = [f"registry.json: {e.message}" for e in Draft202012Validator(registry_schema).iter_errors(top)]
    out += [f"{r.get('id')} {list(e.absolute_path)}: {e.message}"
            for r in reg["rules"] for e in Draft202012Validator(schema).iter_errors(r)]
    ids = [r["id"] for r in reg["rules"]]
    gates = load(GATES)["gates"]
    out += [f"duplicate id {i}" for i, n in Counter(ids).items() if n > 1]
    for r in reg["rules"]:
        if r["superseded_by"] and r["superseded_by"] not in ids:
            out.append(f"{r['id']}: superseded_by {r['superseded_by']} is not an id")
        if r["gate"] and r["gate"] not in gates:
            out.append(f"{r['id']}: gate {r['gate']} is not in gates/registry.json")
    return out


def run_build(*args):
    return subprocess.run([sys.executable, str(BUILD), *args], capture_output=True, text=True,
                          encoding="utf-8")


def test_registry_is_valid():
    assert problems(hks_registry.load()) == []


def test_each_rule_file_is_named_by_its_id():
    files = sorted((REGISTRY / "rules").glob("*.json"))
    assert files
    assert [p.stem for p in files if load(p)["id"] != p.stem] == []


def first(reg, **match):
    return next(r for r in reg["rules"] if all(r[k] == v for k, v in match.items()))


def no_confirm(reg):
    first(reg, kind="do_confirm", status="active")["confirm"] = None


def no_replacement(reg):
    first(reg, status="superseded")["superseded_by"] = None


def unknown_replacement(reg):
    first(reg, status="superseded")["superseded_by"] = "HKS-X999"


def unknown_gate(reg):
    first(reg, kind="code_gate")["gate"] = "no_such_gate"


def duplicate_id(reg):
    reg["rules"].append(copy.deepcopy(reg["rules"][0]))


@pytest.mark.parametrize("break_it", [no_confirm, no_replacement, unknown_replacement, unknown_gate,
                                      duplicate_id])
def test_a_broken_entry_fails(break_it):
    reg = copy.deepcopy(hks_registry.load())
    break_it(reg)
    assert problems(reg)


def test_generated_files_match_the_registry():
    result = run_build("--check")
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_catches_a_hand_edit(tmp_path):
    shutil.copytree(REGISTRY, tmp_path / hks_registry.REGISTRY)
    assert run_build("--root", str(tmp_path)).returncode == 0
    assert run_build("--check", "--root", str(tmp_path)).returncode == 0

    page = tmp_path / "projects/hks/before-you-cut.md"
    page.write_text(page.read_text(encoding="utf-8") + "- a rule added by hand\n", encoding="utf-8")
    result = run_build("--check", "--root", str(tmp_path))
    assert result.returncode == 1
    assert "projects/hks/before-you-cut.md" in result.stdout


def test_every_rule_commit_still_matches_git():
    import subprocess
    import sys
    root = Path(__file__).resolve().parent.parent
    run = subprocess.run([sys.executable, str(root / "tools" / "hks_registry_extract.py"), "--check"],
                         cwd=root, capture_output=True, text=True, encoding="utf-8")
    assert run.returncode == 0, run.stdout + run.stderr
