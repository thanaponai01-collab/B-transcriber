"""Every HKS user correction reaches a registry rule, and the loop that takes it there can't be skipped.

The ledger is projects/hks/registry/corrections/K<n>.json; a rule cites its corrections. A
correction only memory tells, a rule written around tools/hks_correct.py, a rule doc edited by hand
and a contradicting rule each turn a test here red (the plants at the end prove it).
"""
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from cutdeck import hks_registry
from cutdeck.hks_rule_conflicts import lexical

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / hks_registry.REGISTRY
CORRECT = ROOT / "tools/hks_correct.py"
BUILD = ROOT / "tools/hks_registry_build.py"
MEMORY = "projects/hks/memory"
# rules.md and principles.md were where rules were written by hand until 2026-11-26. They keep the
# history and the why; a new rule goes through tools/hks_correct.py. registry/frozen.json pins their bytes.
FROZEN = ["projects/hks/rules.md", "projects/hks/principles.md"]


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def correction_problems(corrections, rules):
    schema = load(REGISTRY / "rules.schema.json")
    v = Draft202012Validator({"$ref": "#/$defs/correction", "$defs": schema["$defs"]})
    out = [f"{c.get('id')} {list(e.absolute_path)}: {e.message}" for c in corrections for e in v.iter_errors(c)]
    ids = {c["id"] for c in corrections}
    cited = {k for r in rules for k in r["corrections"]}
    out += [f"{k}: no rule cites it (run tools/hks_correct.py)" for k in sorted(ids - cited)]
    out += [f"{r['id']}: cites {k}, which is not in corrections/" for r in rules for k in r["corrections"] if k not in ids]
    out += [f"{c['id']}: repeat_of {k} is not a correction" for c in corrections for k in c["repeat_of"] if k not in ids]
    return out


def unjudged_pairs(rules, conflicts):
    """Rule pairs the lexical check flags that conflicts.json doesn't list."""
    known = {tuple(p["pair"]) for p in conflicts["pairs"]}
    active = [{"id": r["id"], "text": r["text"]} for r in rules if r["status"] == "active"]
    flags = {tuple(sorted([f["a"], f["b"]], key=hks_registry.id_key)) for f in lexical(active)}
    return sorted(flags - known)


def untagged_memory_corrections(root):
    """Memory paragraphs that quote the user and carry neither a (K<n>) tag nor "(not a correction)"."""
    out = []
    for path in sorted((Path(root) / MEMORY).glob("*.md")):
        for para in correction_blocks(path.read_text(encoding="utf-8")):
            if not re.search(r"\(K\d+[a-z]?[,)]|\(not a correction\)", para):
                out.append(f"{path.name}: {para[:120]}")
    return out


# How memory quotes a correction: 'User, after v1: "..."', '**user: "..."**', '**User correction (...):** "..."'.
# Scored on the 2026-11-26 matrix: 11 of 14 quoted corrections found, 9 of 12 paragraphs real. Prose that
# retells a correction without quoting it is not found (gates/data/correction-loop-20261126/).
USER_QUOTE = re.compile(r"\b[Uu]ser(?:'s)?\b[^\"“\n]{0,80}?:\s*\**\s*[\"“][^\"”]{6,}|\*\*User correction")


def correction_blocks(text):
    """Paragraphs of a memory file that quote the user's correction, or quote anyone under a heading
    that names corrections."""
    out, heading = [], ""
    for para in re.split(r"\n\s*\n", text):
        heading = next((ln for ln in reversed(para.splitlines()) if ln.startswith("#")), heading)
        quotes = re.search(r"[\"“][^\"”]{6,}", para)
        if USER_QUOTE.search(para) or (quotes and re.search(r"\bcorrections?\b", heading, re.I)
                                       and not para.startswith("#")):
            out.append(para)
    return out


def test_every_correction_is_valid_and_cited_by_a_rule():
    assert correction_problems(hks_registry.load_corrections(), hks_registry.load_rules()) == []


def episodes_without_corrections(root):
    """Episode memory files (yt-<YYYYMMDD>-*.md) whose episode has no correction in the ledger. Coarse:
    it catches an episode whose corrections never reached the ledger, not one prose correction among
    others."""
    episodes = {c["episode"] for c in hks_registry.load_corrections(root)}
    files = [p.name for p in (Path(root) / MEMORY).glob("yt-*.md")]
    return [f for f in files if (m := re.match(r"yt-(\d{8})-", f)) and m.group(1) not in episodes]


def test_every_episode_in_memory_has_its_corrections_in_the_ledger():
    assert episodes_without_corrections(ROOT) == []


def test_every_correction_memory_quotes_carries_a_k_id():
    assert untagged_memory_corrections(ROOT) == []


LAST_HAND_RULE = "HKS-X114"  # every rule after it was written by tools/hks_correct.py


def hand_written_rules(rules):
    """Rules after LAST_HAND_RULE that didn't come through the intake, so no conflict check saw them."""
    last = hks_registry.id_key(LAST_HAND_RULE)
    return [r["id"] for r in rules if r["id"].startswith("HKS-X") and hks_registry.id_key(r["id"]) > last
            and not (r["kind_source"] == "hks_correct" and r["source"]["file"].startswith(f"{hks_registry.REGISTRY}/corrections/"))]


def test_new_rules_come_through_the_intake():
    assert hand_written_rules(hks_registry.load_rules()) == []


def test_no_unjudged_rule_conflict():
    assert unjudged_pairs(hks_registry.load_rules(), load(REGISTRY / "conflicts.json")) == []


def digest(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def test_rule_docs_are_frozen():
    pins = load(REGISTRY / "frozen.json")
    assert sorted(pins) == sorted(FROZEN)
    assert {rel: digest(ROOT / rel) for rel in pins} == pins, \
        "rules.md and principles.md are frozen; add a rule with tools/hks_correct.py"


# --- tools/hks_correct.py, on a copy of the registry -------------------------------------------

def copy_repo(tmp_path):
    for rel in [hks_registry.REGISTRY, MEMORY]:
        shutil.copytree(ROOT / rel, tmp_path / rel)
    (tmp_path / "projects/hks/gates").mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / "projects/hks/gates/registry.json", tmp_path / "projects/hks/gates/registry.json")
    for rel in ["projects/hks/before-you-cut.md", *FROZEN]:
        shutil.copy(ROOT / rel, tmp_path / rel)
    shutil.copytree(ROOT / ".claude/skills", tmp_path / ".claude/skills")
    return tmp_path


def correct(root, *args):
    return subprocess.run([sys.executable, str(CORRECT), *args, "--root", str(root), "--method", "lexical",
                           "--now", "2026-11-27 10:00"], capture_output=True, text=True, encoding="utf-8")


def build_check(root):
    return subprocess.run([sys.executable, str(BUILD), "--check", "--root", str(root)], capture_output=True,
                          text=True, encoding="utf-8")


NEW = ["the end card goes after the sting, not before", "--episode", "20261127", "--stage", "build",
       "--title", "End card after the sting.", "--text", "End card after the sting: the sting plays first."]


def test_intake_asks_gate_or_note_and_writes_nothing(tmp_path):
    root = copy_repo(tmp_path)
    before = sorted(p.name for p in (root / hks_registry.REGISTRY / "corrections").iterdir())
    run = correct(root, *NEW)
    assert run.returncode == 2 and "Gate or note?" in run.stdout
    assert sorted(p.name for p in (root / hks_registry.REGISTRY / "corrections").iterdir()) == before


def test_intake_writes_the_correction_the_rule_and_the_skills(tmp_path):
    root = copy_repo(tmp_path)
    run = correct(root, *NEW, "--note", "Where is the end card, and does the sting play first?")
    assert run.returncode == 0, run.stdout + run.stderr
    kid, rid = re.match(r"(K\d+) -> (HKS-X\d+)", run.stdout).groups()
    rule = load(hks_registry.rule_path(rid, root))
    assert rule["corrections"] == [kid] and rule["stage"] == "build" and rule["kind"] == "do_confirm"
    assert load(hks_registry.correction_path(kid, root))["words"] == NEW[0]
    assert rid in (root / ".claude/skills/hks-build/SKILL.md").read_text(encoding="utf-8")
    assert build_check(root).returncode == 0
    assert correction_problems(hks_registry.load_corrections(root), hks_registry.load_rules(root)) == []
    assert unjudged_pairs(hks_registry.load_rules(root), load(root / hks_registry.REGISTRY / "conflicts.json")) == []


def test_intake_on_an_existing_rule_marks_the_repeat(tmp_path):
    root = copy_repo(tmp_path)
    earlier = load(hks_registry.rule_path("HKS-C28", root))["corrections"]
    args = ["again a piece ends mid-thought", "--episode", "20261127", "--rule", "HKS-C28"]
    run = correct(root, *args)
    assert run.returncode == 2 and "Gate or note?" in run.stdout and "--as-is" in run.stdout
    run = correct(root, *args, "--as-is")
    assert run.returncode == 0, run.stdout + run.stderr
    kid = re.match(r"(K\d+)", run.stdout).group(1)
    assert load(hks_registry.correction_path(kid, root))["repeat_of"] == earlier
    assert kid in load(hks_registry.rule_path("HKS-C28", root))["corrections"]


def test_intake_names_a_conflicting_rule_and_supersede_resolves_it(tmp_path):
    root = copy_repo(tmp_path)
    words = "zoom full screen inserts to hide the clock and the logo"
    args = [words, "--episode", "20261127", "--stage", "build", "--title", "Zoom full-screen inserts.",
            "--text", "Zoom full-screen inserts to hide the clock and the logo.", "--note", "Which inserts did you zoom?"]
    run = correct(root, *args)
    assert run.returncode == 2 and "may contradict" in run.stdout
    flagged = re.findall(r"^  (HKS-\w+):", run.stdout, re.M)
    assert flagged
    run = correct(root, *args, *[a for f in flagged for a in ("--keep", f)])
    assert run.returncode == 0, run.stdout + run.stderr
    assert unjudged_pairs(hks_registry.load_rules(root), load(root / hks_registry.REGISTRY / "conflicts.json")) == []


# --- Step 4 of the 2026-11-26 brief: plant each break, the matching check turns red --------------

def memory_check(root):
    return untagged_memory_corrections(root)


def ledger_check(root):
    return correction_problems(hks_registry.load_corrections(root), hks_registry.load_rules(root))


def skills_check(root):
    return build_check(root).stdout.splitlines()


def conflicts_check(root):
    return unjudged_pairs(hks_registry.load_rules(root), load(root / hks_registry.REGISTRY / "conflicts.json"))


def schema_check(root):
    schema = load(root / hks_registry.REGISTRY / "rules.schema.json")
    return [f"{r['id']}: {e.message}" for r in hks_registry.load_rules(root)
            for e in Draft202012Validator(schema).iter_errors(r)]


def frozen_check(root):
    pins = load(root / hks_registry.REGISTRY / "frozen.json")
    return [rel for rel, h in pins.items() if digest(root / rel) != h]


def plant_memory_only_correction(root):
    p = root / MEMORY / "yt-20261126-draft.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n**User correction (2026-11-27):** \"never put the logo "
                 "over a face\". Moved the logo.\n", encoding="utf-8")


def plant_ledger_only_correction(root):
    c = copy.deepcopy(hks_registry.load_corrections(root)[0])
    c["id"] = "K999"
    hks_registry.write_correction(c, root)


def plant_hand_edited_skill(root):
    p = root / ".claude/skills/hks-build/SKILL.md"
    p.write_text(p.read_text(encoding="utf-8") + "- a rule added by hand\n", encoding="utf-8")


def plant_contradicting_rule(root):
    rule = load(hks_registry.rule_path("HKS-X108", root))
    rule.update(id="HKS-X999", corrections=[], text="Keep the host's pauses, restarts and doubled words inside "
                "every passage; never cut fillers.")
    hks_registry.write_rule(rule, root)


def plant_skipped_regenerate(root):
    rule = load(hks_registry.rule_path("HKS-X108", root))
    rule["text"] += " Changed by hand."
    hks_registry.write_rule(rule, root)


def plant_rule_without_stage(root):
    rule = load(hks_registry.rule_path("HKS-X108", root))
    del rule["stage"]
    hks_registry.write_rule(rule, root)


def plant_rule_in_frozen_doc(root):
    p = root / "projects/hks/rules.md"
    p.write_text(p.read_text(encoding="utf-8") + "\n- **New rule:** never zoom the logo.\n", encoding="utf-8")


def episode_check(root):
    return episodes_without_corrections(root)


def plant_new_episode_told_in_prose(root):
    (root / MEMORY / "yt-20261127-draft.md").write_text(
        "# YT 20261127\n\nThe user told me the logo must never sit over a face, so I moved it.\n", encoding="utf-8")


def intake_check(root):
    return hand_written_rules(hks_registry.load_rules(root))


def plant_contradiction_in_other_words(root):
    """The lexical check has no axis for "leave ... in"; the rule skipped the intake's model check."""
    rule = load(hks_registry.rule_path("HKS-X108", root))
    rule.update(id="HKS-X998", corrections=[], text="Leave the host's pauses and doubled words in, as aired.")
    hks_registry.write_rule(rule, root)


PLANTS = [(plant_memory_only_correction, memory_check), (plant_new_episode_told_in_prose, episode_check),
          (plant_ledger_only_correction, ledger_check),
          (plant_hand_edited_skill, skills_check), (plant_contradicting_rule, conflicts_check),
          (plant_contradiction_in_other_words, intake_check), (plant_skipped_regenerate, skills_check),
          (plant_rule_without_stage, schema_check), (plant_rule_in_frozen_doc, frozen_check)]


@pytest.mark.parametrize("plant, check", PLANTS, ids=[p.__name__ for p, _ in PLANTS])
def test_a_planted_break_turns_its_check_red(tmp_path, plant, check):
    root = copy_repo(tmp_path)
    before = check(root)
    plant(root)
    assert set(check(root)) - set(before)


def test_report_counts_repeats_and_only_gates_that_existed_that_day():
    sys.path.insert(0, str(ROOT / "tools"))
    from hks_corrections_report import rows
    c = lambda k, day, rep: {"id": k, "episode": day.replace("-", ""), "date": day, "repeat_of": rep}
    rules = [{"gate": "g", "corrections": ["K1", "K2"]}]
    out = rows([c("K1", "2026-11-24", []), c("K2", "2026-11-27", ["K1"])], rules,
               {"g": {"status": "kept", "added": "2026-11-25"}})
    assert [(r["corrections"], r["repeats"], r["gate_should_have_caught"]) for r in out] == [(1, 0, 0), (1, 1, 1)]
