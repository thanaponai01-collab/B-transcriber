"""Take one HKS user correction into the rule registry: the only way a correction becomes a rule.

    python tools/hks_correct.py "<the user's words>" --episode 20261127 --stage build \
        --title "<the rule in one line>" --text "<the rule>" (--gate <gate id> | --note "<question>")
    python tools/hks_correct.py "<the user's words>" --episode 20261127 --rule HKS-22 (--gate ... | --note ...)

It writes nothing until every question is answered. A question prints and exits 2; ask the user,
then rerun with the answer:

1. Conflicts. hks_rule_conflicts checks the words against every active registry rule (`llm` by
   default, `lexical` offline). Each flagged rule needs `--supersedes <id>` (the new rule replaces
   it) or `--keep <id>` (both stay).
2. Already a rule? The model names active rules that already state the lesson. If one does, this is
   a repeat: rerun with `--rule <id>`; if none does, `--new`.
3. Gate or note? `--gate` names a gate in projects/hks/gates/registry.json that measures the rule;
   `--note` is the do-confirm question the handover asks. With `--rule` (a rule broken again) the
   question is whether to escalate it; `--as-is` keeps it.

Then it writes corrections/K<n>.json, the rule (a new HKS-X<n>, or the correction added to
`--rule`), the judged pairs into conflicts.json, and regenerates the pages and skills
(tools/hks_registry_build.py). Paste the memory line it prints where memory tells the story.
`--repeat-of K<n>` names an earlier correction of the same mistake: tools/hks_corrections_report.py
counts those per episode.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cutdeck import hks_registry  # noqa: E402
from cutdeck.hks_rule_conflicts import _claude, _json_list, lexical, llm  # noqa: E402
from hks_registry_build import write_all  # noqa: E402

GATES = "projects/hks/gates/registry.json"
CONFLICTS = f"{hks_registry.REGISTRY}/conflicts.json"


def next_id(ids, prefix):
    return prefix + str(max((int(i[len(prefix):].rstrip("abcd")) for i in ids if i.startswith(prefix)), default=0) + 1)


def probe(words):
    """A phrase of the words that appears verbatim in the correction's JSON file (no quote, backslash
    or newline, which JSON escapes), for tools/hks_registry_extract.py to find the commit by."""
    return max(re.split(r'["\\\n]', words), key=len).strip()[:60]


def read_json(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return json.load(f)


def flagged(words, rules, method, model):
    active = [{"id": r["id"], "text": r["text"]} for r in rules if r["status"] == "active"]
    book = active + [{"id": "correction", "text": words}]
    if method == "lexical":
        found = lexical(book, only="correction")
    else:
        found, _ = llm(book, model, only="correction")
    return sorted({f["b"] if f["a"] == "correction" else f["a"] for f in found}, key=hks_registry.id_key)


def restating(words, rules, method, model):
    """Active rules whose text already states the lesson (the model matcher; precision and recall
    0.78 on the 2026-11-26 matrix). The lexical method has no matcher and returns none."""
    if method == "lexical":
        return []
    active = [r for r in rules if r["status"] == "active"]
    book = "\n".join(f"{r['id']} {r['text']}" for r in active)
    text, _ = _claude("A video editor's rule book is below, then a correction the editor's user gave. Name "
                      "the rules whose text states the lesson, so that an editor following the rule would "
                      f"not have made the mistake. Name none if no rule states it.\n\nRULE BOOK:\n{book}\n\n"
                      f"CORRECTION: {words}\n\nReply with only a JSON array of rule ids, [] if none.", model)
    ids = {r["id"] for r in active}
    return [i for i in _json_list(text) if i in ids]


def questions(args, rules, gates, flags, known):
    """What the user still has to answer, as lines; empty when the command may write."""
    out = []
    ids = {r["id"] for r in rules}
    for rid in [args.rule, *args.supersedes, *args.keep]:
        if rid and rid not in ids:
            out.append(f"{rid} is not a registry rule.")
    ledger = {c["id"] for c in hks_registry.load_corrections(args.root)}
    out += [f"--repeat-of {k} is not a correction." for k in args.repeat_of or [] if k not in ledger]
    if args.rule and args.supersedes:
        out.append("--supersedes is for a new rule; with --rule the correction joins that rule.")
    if not args.rule and not (args.stage and args.title and args.text):
        out.append("A new rule needs --stage, --title and --text (or pass --rule <id> if a rule already says it).")
    unanswered = [f for f in flags if f not in args.supersedes and f not in args.keep and f != args.rule]
    if unanswered:
        out.append("These active rules may contradict the correction. For each, ask the user which wins, then "
                   "pass --supersedes <id> (the new rule replaces it) or --keep <id> (both stay):")
        out += [f"  {r['id']}: {r['text'][:160]}" for r in rules if r["id"] in unanswered]
    if args.rule and args.rule in ids and next(r for r in rules if r["id"] == args.rule)["status"] != "active":
        out.append(f"{args.rule} is not active; name the rule that replaced it.")
    if args.gate and args.gate not in gates:
        out.append(f"--gate {args.gate} is not in {GATES}.")
    elif args.gate and gates[args.gate]["status"] != "kept" and not args.note:
        out.append(f"Gate {args.gate} is {gates[args.gate]['status']}, not kept, so the handover still asks: "
                   "add --note \"<do-confirm question>\".")
    if known and not args.rule and not args.new:
        out.append("These rules may already say this. If one does, the user is correcting it again: rerun "
                   "with --rule <id>. If none does, add --new:")
        out += [f"  {r['id']}: {r['text'][:160]}" for r in rules if r["id"] in known]
    if not (args.gate or args.note or (args.rule and args.as_is)):
        out.append("Gate or note? Ask the user: should a code gate measure this (--gate <id from "
                   f"{GATES}>), or is it a note the handover asks about (--note \"<do-confirm question>\")?"
                   + (" For a rule broken again, --as-is keeps it as it is." if args.rule else ""))
    return out


def apply_kind(rule, gate, note, gates):
    """A kept gate makes the rule a code gate; otherwise a note makes it a do-confirm question."""
    if gate:
        rule["gate"] = gate
    if gate and gates[gate]["status"] == "kept":
        rule["kind"], rule["confirm"] = "code_gate", None
    elif note:
        rule["kind"], rule["confirm"] = "do_confirm", note


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("words", help="the user's words, verbatim")
    ap.add_argument("--episode", required=True, help="YYYYMMDD of the day being edited")
    ap.add_argument("--source", choices=["verbal", "red_marker", "diff"], default="verbal")
    ap.add_argument("--session", help="first 8 characters of the session id")
    ap.add_argument("--memory", help="the memory file that tells the story (repo-relative)")
    ap.add_argument("--rule", help="an existing rule this correction enforces again")
    ap.add_argument("--new", action="store_true", help="no rule says this yet (after the restating check)")
    ap.add_argument("--as-is", action="store_true", help="with --rule: keep the rule's gate or note as it is")
    ap.add_argument("--stage", choices=["day_setup", "paper_edit", "build", "handover"])
    ap.add_argument("--title")
    ap.add_argument("--text")
    ap.add_argument("--gate")
    ap.add_argument("--note")
    ap.add_argument("--supersedes", action="append", default=[])
    ap.add_argument("--keep", action="append", default=[])
    ap.add_argument("--repeat-of", action="append", default=None, metavar="K<n>",
                    help="an earlier correction of the same mistake (default with --rule: that rule's corrections)")
    ap.add_argument("--method", choices=["llm", "lexical"], default="llm")
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--root", default=ROOT)
    ap.add_argument("--now", help=argparse.SUPPRESS)  # tests: fixed "YYYY-MM-DD HH:MM"
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    root = args.root

    rules = hks_registry.load_rules(root)
    corrections = hks_registry.load_corrections(root)
    gates = read_json(root, GATES)["gates"]
    flags = flagged(args.words, rules, args.method, args.model)
    known = [] if args.rule or args.new else restating(args.words, rules, args.method, args.model)
    todo = questions(args, rules, gates, flags, known)
    if todo:
        print("\n".join(todo))
        return 2

    now = dt.datetime.strptime(args.now, "%Y-%m-%d %H:%M") if args.now else dt.datetime.now()
    kid = next_id([c["id"] for c in corrections], "K")
    by_id = {r["id"]: r for r in rules}
    if args.rule:
        rule = by_id[args.rule]
        repeat_of = list(rule["corrections"])
    else:
        rule = {"id": next_id(by_id, "HKS-X"), "aliases": [], "title": args.title, "text": args.text,
                "source": {"file": f"{hks_registry.REGISTRY}/corrections/{kid}.json", "heading": kid},
                "status": "active", "superseded_by": None, "confirmed": True, "kind": "do_confirm",
                "kind_source": "hks_correct", "stage": args.stage, "corrections": [], "gate": None,
                "confirm": None, "probe": [probe(args.words)], "commit": None,
                "added": now.strftime("%Y-%m-%d")}
        repeat_of = []
    if args.repeat_of is not None:
        repeat_of = args.repeat_of
    apply_kind(rule, args.gate, args.note, gates)
    rule["corrections"].append(kid)
    correction = {"id": kid, "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M"),
                  "episode": args.episode, "session": args.session, "source": args.source, "words": args.words,
                  "way": None, "repeat_of": repeat_of, "memory": args.memory}

    hks_registry.write_correction(correction, root)
    for old in args.supersedes:
        by_id[old].update(status="superseded", superseded_by=rule["id"], confirm=None)
        hks_registry.write_rule(by_id[old], root)
    hks_registry.write_rule(rule, root)
    cleared = [f["b"] if f["a"] == rule["id"] else f["a"] for f in lexical(
        [{"id": r["id"], "text": r["text"]} for r in hks_registry.load_rules(root) if r["status"] == "active"],
        only=rule["id"])]
    record_pairs(root, rule["id"], kid, kept=args.keep,
                 cleared=[c for c in cleared if c not in args.keep and c not in flags])
    write_all(root)
    print(f"{kid} -> {rule['id']} ({rule['kind']}{', gate ' + rule['gate'] if rule['gate'] else ''})"
          + (f", repeats {', '.join(repeat_of)}" if repeat_of else ""))
    print(f"In memory, tell the story under this line (a test looks for the form and the id):\n"
          f"**User correction ({correction['date']}) ({kid}):** \"{args.words}\"")
    return 0


def record_pairs(root, rule_id, kid, kept, cleared):
    """Pairs judged at intake go into conflicts.json, so the lexical ratchet
    (tests/test_hks_corrections.py) accepts them: "kept" by the user, or "cleared" when the lexical
    check flags a pair the conflict check run here did not."""
    path = os.path.join(root, CONFLICTS)
    data = read_json(root, CONFLICTS)
    known = {tuple(p["pair"]) for p in data["pairs"]}
    for status, others in (("kept", kept), ("cleared", cleared)):
        for other in others:
            pair = sorted([rule_id, other], key=hks_registry.id_key)
            if tuple(pair) not in known:
                data["pairs"].append({"pair": pair, "status": status, "by": kid})
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=1) + "\n")


if __name__ == "__main__":
    sys.exit(main())
