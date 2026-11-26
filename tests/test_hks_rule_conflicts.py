"""hks_rule_conflicts flags HKS rules that contradict each other or a new user correction.

The unit tests cover the free lexical method. Run this file as a script to score both methods on the
three known rule conflicts (projects/hks/gates/failure-table.md, way D), using the rules as they were
committed when each correction came in:

    python -m tests.test_hks_rule_conflicts [--llm]

The answer key below lives only here; the checker never sees it.
"""
import json
import sys
from pathlib import Path

from cutdeck.hks_rule_conflicts import lexical, llm, snapshot, split_rules


def rules(*texts):
    return [{"id": f"r{i}", "text": t} for i, t in enumerate(texts)]


def test_opposite_instructions_on_one_topic_are_flagged():
    flags = lexical(rules("Cut the host's warm-up questions.", "Keep the host's warm-up questions."))
    assert [(f["a"], f["b"]) for f in flags] == [("r0", "r1")]


def test_same_instruction_twice_is_not_flagged():
    assert lexical(rules("Cut the host's warm-up questions.", "Drop the host's warm-up questions.")) == []


def test_opposite_instructions_on_different_topics_are_not_flagged():
    assert lexical(rules("Cut sponsor reads from the show.", "Keep the guest's first story sentence.")) == []


def test_a_negator_flips_the_instruction():
    flags = lexical(rules("Zoom full-frame film inserts to hide the clock.",
                          "Don't zoom full-frame film inserts."))
    assert len(flags) == 1


def test_cut_as_a_noun_is_not_an_instruction():
    assert lexical(rules("A jump cut in the studio picture shows.", "Keep the studio picture whole.")) == []


def test_numbers_in_a_rule_do_not_split_its_clause():
    flags = lexical(rules("Full-frame film: zoom 152, (0.5, 0.599) to drop the clock.",
                          "Never zoom full-frame film."))
    assert len(flags) == 1


def test_only_returns_pairs_with_the_given_rule():
    rs = rules("Cut host questions.", "Keep host questions.", "Keep host questions always.")
    flags = lexical(rs, only="r0")
    assert {f["b"] for f in flags} == {"r1", "r2"} and all(f["a"] == "r0" for f in flags)


def test_split_rules_gives_one_unit_per_list_item_or_paragraph():
    md = ("---\nname: x\n---\n# Title\n\nIntro line\nwrapped.\n\n1. First rule\n   wrapped.\n"
          "2. Second rule.\n   - nested point\n\n| a | b |\n|---|---|\n")
    assert split_rules(md, "f.md") == [
        {"id": "f.md:L6", "text": "Intro line wrapped."},
        {"id": "f.md:L9", "text": "1. First rule wrapped."},
        {"id": "f.md:L11", "text": "2. Second rule."},
        {"id": "f.md:L12", "text": "- nested point"},
    ]


# ---- scoring on the history ----------------------------------------------------------------------

HKS = "projects/hks/"
BOOK = [HKS + "rules.md", HKS + "principles.md"]
MEMORY = [HKS + "memory/yt-20261123-lessons.md", HKS + "memory/yt-20261124-draft.md"]
SNAPSHOTS = {  # what was read at build time: 1123 read rules.md; 1125 read principles.md + rules.md at 17:14
    "1123": ("19e8864", BOOK),
    "1125": ("90e0e80", BOOK + MEMORY),
    "1125+log": ("90e0e80", BOOK + MEMORY + [HKS + "workflow-log.md"]),  # rules.md points at the log's rules
}
# Each conflict: the rule the user's correction overturned ("rule") and the opposing rule text in the
# book, if any ("partner"). Matched as substrings of a rule unit's text; any listed text counts.
KEY = {
    "K3": {"at": "1123",
           "quote": "You miss some question asking. Yeah, sometimes it needs to be asked before tell the "
                    "story. … asking is the s- is okay to do.",
           "rule": ["Cut host prompts, clarifications and opinions"],
           "partner": []},  # nothing in the 1123 book says a question may stay: not findable pairwise
    "K17": {"at": "1125",
            "quote": "this kind of insert that already full screen dont zoom in, and all the zoom in need "
                     "to be centered",
            "rule": ["full-frame film → 152", "no 3HD bug, no clock"],
            "partner": ["If the clip is already", "full-frame inserts stay at 150%"]},  # log only
    "K21": {"at": "1125",
            "quote": "I feel like you forgot like the context around like the story. … Maybe you can give it "
                     "some taste first, then just go to that story that you pick",
            "rule": ["Get into each story fast", "Drop retellings"],
            "partner": ["let a piece start early for its set-up", "A punchline needs its set-up",
                        "Hook button = set-up + payoff"]},
}
# Controls: corrections that agree with a rule in force (way C or A, not D). Every flag is a false positive.
CONTROLS = {
    "K7a": {"at": "1123", "quote": "the first RAID mark is like a jump cut. … I don't want that ever."},
    "K6": {"at": "1125", "quote": "one thing you forget on all your draft is the color label"},
}
OUT = Path("output/hks_rules/conflicts")


def _has(text, subs):
    return any(s in text for s in subs)


def score_pairs(flags, book, snap):
    text = {r["id"]: r["text"] for r in book}
    hits = {}
    for k, key in KEY.items():
        if not snap.startswith(key["at"]) or not key["partner"]:
            continue
        hits[k] = [i for i, f in enumerate(flags)
                   if (_has(text[f["a"]], key["rule"]) and _has(text[f["b"]], key["partner"]))
                   or (_has(text[f["b"]], key["rule"]) and _has(text[f["a"]], key["partner"]))]
    return hits


def score_correction(flags, book, k):
    text = {r["id"]: r["text"] for r in book}
    other = [f["b"] if f["a"] == "correction" else f["a"] for f in flags]
    return [i for i, o in enumerate(other) if _has(text[o], KEY[k]["rule"])]


def run(method, use_llm):
    OUT.mkdir(parents=True, exist_ok=True)
    books = {s: snapshot(rev, paths) for s, (rev, paths) in SNAPSHOTS.items()}
    report = []

    def keep(name, flags, book, hits, stats=None):
        text = {r["id"]: r["text"] for r in book}
        rows = [{**f, "a_text": text[f["a"]][:300], "b_text": text[f["b"]][:300]} for f in flags]
        rec = {"run": name, "rules": len(book), "flags": len(flags), "hits": hits, "stats": stats}
        (OUT / f"{name}.json").write_text(json.dumps({**rec, "pairs": rows}, ensure_ascii=False,
                                                     indent=1), encoding="utf-8")
        report.append(rec)
        print(json.dumps({k: v for k, v in rec.items() if k != "stats" or v is None} |
                         ({"stats": {k: v for k, v in stats.items() if k != "raw"}} if stats else {}),
                         ensure_ascii=False))

    for snap in ("1123", "1125", "1125+log"):
        book = books[snap]
        flags = lexical(book)
        keep(f"lexical_pairs_{snap}", flags, book, score_pairs(flags, book, snap))
        if use_llm:
            f2, st = llm(book)
            keep(f"llm_book_{snap}", f2, book, score_pairs(f2, book, snap), st)
            if flags:
                f3, st = llm(book, pairs=flags)
                keep(f"llm_filter_{snap}", f3, book, score_pairs(f3, book, snap), st)
    corrections = [(k, KEY[k]["at"]) for k in KEY] + [("K17", "1125+log")]
    corrections += [(k, CONTROLS[k]["at"]) for k in CONTROLS] + [("K3", "1125")]  # K3's rule rewritten by then
    for k, snap in corrections:
        quote = (KEY.get(k) or CONTROLS[k])["quote"]
        book = books[snap] + [{"id": "correction", "text": quote}]
        hits = lambda fl: {k: score_correction(fl, book, k) if k in KEY else "control"}
        flags = lexical(book, only="correction")
        keep(f"lexical_{k}_{snap}", flags, book, hits(flags))
        if use_llm:
            f2, st = llm(book, only="correction")
            keep(f"llm_{k}_{snap}", f2, book, hits(f2), st)
    (OUT / f"summary_{method}.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                                encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    run("llm" if "--llm" in sys.argv else "lexical", "--llm" in sys.argv)
