"""hks_rule_conflicts.py: find HKS editing rules that contradict each other, or a new correction.

Input is a list of rules, ``{"id": str, "text": str}``. Output is a list of flagged pairs,
``{"a": id, "b": id, "reason": str}``. Two methods:

- ``lexical``: free and deterministic. Split each rule into clauses, give each clause a polarity on
  a few axes (keep/cut, always/never, zoom, short/long; a negator just before flips it, a determiner
  just before marks a noun like "a cut" and skips it), and flag
  two rules when clauses on the same axis have opposite polarity and share topic words.
- ``llm``: ``claude -p`` reads the rule list (or the candidate pairs) and names the pairs in tension.

A user correction is checked the same way: it is one more rule, and only pairs that include it count.

    python -m cutdeck.hks_rule_conflicts --rev 90e0e80 [--method lexical|llm] [--correction "..."]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import time

AXES = {  # axis -> (positive words, negative words), matched on stems
    "keep/cut": ({"keep", "kept", "stay", "add", "allow", "okay", "ok", "include", "need"},
                 {"cut", "drop", "skip", "remov", "omit", "delet"}),
    "always/never": ({"always", "every", "must"}, {"never"}),
    "zoom": ({"zoom", "scale"}, set()),
    "short/long": ({"fast", "quick", "short", "shorten", "tight", "tighten"},
                   {"slow", "long", "longer", "lengthen", "extend"}),
}
NEGATORS = {"no", "not", "never", "don", "dont", "without", "nor"}
NOUN_BEFORE = {"a", "an", "the", "each", "every", "this", "that", "my", "your", "their", "his", "its",
               "s", "jump", "sound", "picture", "hard", "visible", "same", "first", "last", "one"}
STOP = set("""a an the and or but if of to in on at by for from with as is are was were be been it its
this that these those there here then than so such each any all one two only also just more most
very can could would should may might will do does did done who what which when where how why
he she they them his her their we you your i me my our us up out into over under about after before
same other own still yet first last s t""".split())


def stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s", "e"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]
            return w[:-1] if w[-1] == w[-2] and w[-1] not in "aeiouls" else w
    return w


AXES = {k: ({stem(w) for w in p}, {stem(w) for w in n}) for k, (p, n) in AXES.items()}
POLAR = set().union(*(p | n for p, n in AXES.values())) | NEGATORS


def _clauses(text: str) -> list[list[str]]:
    parts = re.split(r"(?<!\d)[.;!?](?!\d)|\s[-–—]\s|\bbut\b|\bunless\b|\bexcept\b", text.lower())
    return [[stem(w) for w in re.findall(r"[a-z]+", p.replace("'", ""))] for p in parts]


def _claims(text: str) -> list[tuple[str, int, str, frozenset]]:
    """(axis, polarity, trigger word, topic stems) for each polar word in each clause."""
    out = []
    for words in _clauses(text):
        topic = frozenset(w for w in words if w not in STOP and w not in POLAR and len(w) > 2)
        for i, w in enumerate(words):
            for axis, (pos, neg) in AXES.items():
                pol = 1 if w in pos else -1 if w in neg else 0
                if not pol or (i and words[i - 1] in NOUN_BEFORE):  # "a cut", "jump cuts": a noun
                    continue
                if NEGATORS & set(words[max(0, i - 3):i]):
                    pol = -pol
                out.append((axis, pol, w, topic))
    return out


def lexical(rules: list[dict], min_shared: int = 2, only: str | None = None) -> list[dict]:
    """Flag rule pairs with opposite polarity on one axis and >= min_shared topic words, most
    shared first. With ``only``, return just the pairs that include that rule id."""
    claims = {r["id"]: _claims(r["text"]) for r in rules}
    ids = [r["id"] for r in rules]
    flags = []
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            if only and only not in (a, b):
                continue
            best = None
            for axis, pa, wa, ta in claims[a]:
                for axis_b, pb, wb, tb in claims[b]:
                    shared = ta & tb
                    if axis == axis_b and pa != pb and len(shared) >= min_shared:
                        if not best or len(shared) > len(best[3]):
                            best = (axis, wa, wb, shared)
            if best:
                axis, wa, wb, shared = best
                flags.append({"a": a, "b": b, "shared": len(shared), "reason": f"{axis}: '{wa}' "
                              f"vs '{wb}' on {', '.join(sorted(shared))}"})
    return sorted(flags, key=lambda f: -f["shared"])


def _claude(prompt: str, model: str) -> tuple[str, dict]:
    """One ``claude -p`` call with no tools, from an empty folder (no repo, no CLAUDE.md)."""
    t0 = time.time()
    with tempfile.TemporaryDirectory() as cwd:
        p = subprocess.run(["claude", "-p", "--model", model, "--tools", "", "--strict-mcp-config",
                            "--no-session-persistence", "--output-format", "json"],
                           input=prompt, capture_output=True, text=True, encoding="utf-8",
                           cwd=cwd, timeout=900)
    res = json.loads(p.stdout)
    u = res.get("usage", {})
    return res.get("result", ""), {"raw": res.get("result", ""),
        "cost_usd": res.get("total_cost_usd", 0.0), "seconds": round(time.time() - t0, 1),
        "input_tokens": u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        + u.get("cache_read_input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}


def _json_list(text: str) -> list:
    m = re.search(r"\[.*\]", text, re.S)
    return json.loads(m.group(0)) if m else []


ASK = """You check a video editor's rule book for contradictions. Two rules contradict when an editor
who follows one would, in a real case, break the other, and neither rule names the other as its
exception or replacement. Ignore rules that merely cover different cases or repeat each other.
Name rules only by their number (#12 -> 12)."""
BOOK_ASK = """You check a video editor's rule book for tensions. Two rules are in tension when they pull
an editor opposite ways on the same kind of material, so that an editor who follows one fully would,
in a real case, break the other, and neither rule names the other as its exception or replacement.
Name rules only by their number (#12 -> 12)."""


def llm(rules: list[dict], model: str = "sonnet", pairs: list[dict] | None = None,
        only: str | None = None) -> tuple[list[dict], dict]:
    """Whole list (default), a filter over candidate ``pairs``, or the pairs with rule ``only``.
    Rules are shown as #1..#n, not by id: given file:line ids, the model named wrong ones."""
    num = {r["id"]: str(i) for i, r in enumerate(rules, 1)}
    back = {v: k for k, v in num.items()}
    text = {r["id"]: " ".join(r["text"].split()) for r in rules}
    book = "\n".join(f"#{num[r['id']]} {text[r['id']]}" for r in rules if r["id"] != only)
    if pairs is not None:
        cands = "\n\n".join(f"PAIR {i}\nA {text[p['a']]}\nB {text[p['b']]}" for i, p in enumerate(pairs))
        prompt = (f"{ASK}\n\nFor each pair below, decide whether A and B contradict.\n\n{cands}\n\n"
                  'Reply with only a JSON array of the contradicting pairs: [{"pair": <n>, "reason": '
                  '"<one line>"}]. Reply [] if none.')
    elif only:
        prompt = (f"{ASK}\n\nThe editor's user just said this (a new correction):\n{text[only]}\n\n"
                  "Which rules in the book does it contradict (the rule told the editor to do what the "
                  "user now objects to, or the reverse)? List only rules it contradicts.\n\n"
                  f"RULE BOOK:\n{book}\n\n"
                  'Reply with only a JSON array, most direct first: [{"rule": <n>, "reason": "<one '
                  'line>"}]. Reply [] if none.')
    else:
        prompt = (f"{BOOK_ASK}\n\nRULE BOOK:\n{book}\n\nReply with only a JSON array, strongest first, "
                  'at most 30: [{"a": <n>, "b": <n>, "reason": "<one line>"}]. Reply [] if none.')
    out, stats = _claude(prompt, model)
    found, rid = _json_list(out), lambda v: back.get(str(v).lstrip("#"))
    if pairs is not None:
        found = [{**pairs[f["pair"]], "reason": f["reason"]} for f in found]
    elif only:
        found = [{"a": only, "b": rid(f["rule"]), "reason": f["reason"]} for f in found]
    else:
        found = [{"a": rid(f["a"]), "b": rid(f["b"]), "reason": f["reason"]} for f in found]
    stats["unknown_ids"] = sum(1 for f in found if not (f["a"] and f["b"]))
    return [f for f in found if f["a"] and f["b"]], stats


def split_rules(markdown: str, source: str) -> list[dict]:
    """Rule units of a markdown file: each list item (with its wrapped lines) or paragraph.
    Headings, tables, code fences and front matter are skipped."""
    rules, cur, start, fence = [], [], 0, False
    lines = markdown.splitlines()
    if lines and lines[0] == "---":
        end = lines.index("---", 1)
        lines = [""] * (end + 1) + lines[end + 1:]

    def flush():
        if cur:
            rules.append({"id": f"{source}:L{start}", "text": " ".join(cur)})
            cur.clear()

    for n, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith("```"):
            fence = not fence
            flush()
            continue
        if fence or not s or s.startswith(("#", "|")):
            flush()
            continue
        if re.match(r"(\d+\.|[-*])\s", s) or not cur:
            flush()
            start = n
        cur.append(s)
    flush()
    return rules


def snapshot(rev: str, paths: list[str]) -> list[dict]:
    """The rules in ``paths`` as committed at ``rev`` (paths missing there are skipped)."""
    rules = []
    for path in paths:
        p = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True, encoding="utf-8")
        if p.returncode == 0:
            rules += split_rules(p.stdout, path.rsplit("/", 1)[-1])
    return rules


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rev", default="HEAD")
    ap.add_argument("--paths", nargs="+",
                    default=["projects/hks/rules.md", "projects/hks/principles.md"])
    ap.add_argument("--method", choices=["lexical", "llm"], default="lexical")
    ap.add_argument("--correction", help="a new user correction, checked against the rules")
    ap.add_argument("--model", default="sonnet")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    rules = snapshot(a.rev, a.paths)
    only = None
    if a.correction:
        only = "correction"
        rules.append({"id": only, "text": a.correction})
    if a.method == "lexical":
        out = {"flags": lexical(rules, only=only)}
    else:
        flags, stats = llm(rules, a.model, only=only)
        out = {"flags": flags, "stats": stats}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
