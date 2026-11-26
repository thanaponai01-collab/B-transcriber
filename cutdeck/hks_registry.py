"""The HKS rule registry: projects/hks/registry/registry.json (schema, stages) plus one file per
rule, projects/hks/registry/rules/<id>.json. One file per rule keeps concurrent edits from
conflicting in git. Standard library only, so the tools can import it without the helper's deps.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = "projects/hks/registry"


def id_key(rule_id: str) -> tuple[str, int]:
    """HKS-X9 sorts before HKS-X10: the prefix, then the number."""
    prefix, number = re.fullmatch(r"(.*?)(\d+)", rule_id).groups()
    return prefix, int(number)


def rule_path(rule_id: str, root: Path = ROOT) -> Path:
    return Path(root) / REGISTRY / "rules" / f"{rule_id}.json"


def load_rules(root: Path = ROOT) -> list[dict]:
    """Every rule, sorted by id_key."""
    rules = [json.loads(p.read_text(encoding="utf-8")) for p in (Path(root) / REGISTRY / "rules").glob("*.json")]
    return sorted(rules, key=lambda r: id_key(r["id"]))


def correction_path(correction_id: str, root: Path = ROOT) -> Path:
    return Path(root) / REGISTRY / "corrections" / f"{correction_id}.json"


def load_corrections(root: Path = ROOT) -> list[dict]:
    """Every user correction (corrections/K<n>.json), sorted by id_key."""
    out = [json.loads(p.read_text(encoding="utf-8")) for p in (Path(root) / REGISTRY / "corrections").glob("*.json")]
    return sorted(out, key=lambda c: id_key(c["id"].rstrip("abcd")) + (c["id"],))


def load(root: Path = ROOT) -> dict:
    """registry.json with the rules under "rules"."""
    reg = json.loads((Path(root) / REGISTRY / "registry.json").read_text(encoding="utf-8"))
    return {**reg, "rules": load_rules(root)}


def dumps(rule: dict) -> str:
    return json.dumps(rule, ensure_ascii=False, indent=1) + "\n"


def write_rule(rule: dict, root: Path = ROOT) -> None:
    _write(rule_path(rule["id"], root), rule)


def write_correction(correction: dict, root: Path = ROOT) -> None:
    _write(correction_path(correction["id"], root), correction)


def _write(path: Path, rule: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(rule))
    os.replace(tmp, path)
