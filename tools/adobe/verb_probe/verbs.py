"""Throwaway differential harness: each verb by its existing tier-2/3 route vs a tier-1 composite
(edit_clips in one call), on the scratch fixture. Every call goes through cdv.py call (evidence).

    python verbs.py fixture | <test name>... | all
"""
import json, os, re, subprocess, sys
from pathlib import Path

R = Path(r"D:\01 - Antigravity\00 Claude\B-transcriber")
P, C = str(R / ".venv/Scripts/python.exe"), str(R / ".claude/skills/verify-cutdeck/scripts/cdv.py")
OUT = Path(__file__).parent / "results.jsonl"
SEQ = "CutDeck verify (scratch)"
SEC, F = 254016000000, 8467200000
MEDIA = str(R / "output/verify-cutdeck/media/verify-clip-1080x1920-30fps.mp4")
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
T = lambda s: str(int(round(s * SEC)))


class Stop(Exception):
    pass


def call(cmd, args=None, label=None):
    r = subprocess.run([P, C, "call", cmd, json.dumps(args or {}, ensure_ascii=False)] + (["--label", label] if label else []),
                       cwd=R, capture_output=True, text=True, encoding="utf-8", env=ENV)
    m = re.search(r"recorded (.+\.json)", r.stderr)
    if not m:
        raise Stop(f"{cmd}: no record\n{r.stderr[-800:]}")
    rec = json.loads(Path(m.group(1)).read_text(encoding="utf-8"))
    if not rec["ok"]:
        raise Stop(f"{cmd} {args}: {rec.get('error')}")
    return rec["result"]


def snap(label="read"):
    t = call("read_timeline", {"sequence": SEQ}, label)
    clips = {tr["id"]: [(int(c["start_ticks"]), int(c["end_ticks"]), int(c["in_ticks"]), int(c["out_ticks"]), c["disabled"])
                        for c in tr["clips"]] for tr in t["tracks"] if tr["clips"]}
    names = {c["id"]: c["name"] for tr in t["tracks"] for c in tr["clips"]}
    return clips, names, t


def show(s):
    return {k: [(a / SEC, b / SEC, i / SEC, o / SEC) + (("off",) if d else ()) for a, b, i, o, d in v] for k, v in s.items()}


def undo_back(before, after, label, max_steps=8):
    """Edit > Undo one step at a time until the scratch reads `before`. A step that leaves the scratch
    as it was undid something else (another sequence, the user's work): Redo it and stop."""
    cur = after
    for n in range(1, max_steps + 1):
        call("menu_command", {"path": "Edit > Undo", "focus": None}, f"{label}-undo{n}")
        s, _, _ = snap(f"{label}-undo{n}-read")
        if s == before:
            return n
        if s == cur:
            call("menu_command", {"path": "Edit > Redo", "focus": None}, f"{label}-redo-foreign")
            raise Stop(f"{label}: undo {n} did not touch the scratch; redone; stopped")
        cur = s
    raise Stop(f"{label}: not back to before after {max_steps} undos")


def edits(*ops):
    return {"sequence": SEQ, "edits": [dict(clip=c, op=o, **kw) for c, o, kw in ops]}


def both(t, op, **kw):
    """The V1 and A1 clip starting at t seconds."""
    return [(f"V1@{T(t)}", op, kw), (f"A1@{T(t)}", op, kw)]


def fixture():
    """From scratch (6 s clip at 0): A 0-4 [src 0-4], B 4-8 [1-5], C 8-13 [1-6] on V1 and A1."""
    call("place_media", {"sequence": SEQ, "media": MEDIA, "at_ticks": T(6), "v": 0, "a": 0}, "fx-place2")
    call("place_media", {"sequence": SEQ, "media": MEDIA, "at_ticks": T(12), "v": 0, "a": 0}, "fx-place3")
    for label, ops in [("fx-A-out", both(0, "trim_out", out_ticks=T(4))), ("fx-B-in", both(6, "trim_in", in_ticks=T(1))),
                       ("fx-B-out", both(7, "trim_out", out_ticks=T(5))), ("fx-C-in", both(12, "trim_in", in_ticks=T(1))),
                       ("fx-B-move", both(7, "move", dt_ticks=T(-3))), ("fx-C-move", both(13, "move", dt_ticks=T(-5)))]:
        call("edit_clips", edits(*ops), label)
    s, _, _ = snap("fx-read")
    want = [(0, 4, 0, 4), (4, 8, 1, 5), (8, 13, 1, 6)]
    for tr in ("V1", "A1"):
        got = [(a / SEC, b / SEC, i / SEC, o / SEC) for a, b, i, o, _ in s.get(tr, [])]
        if got != want:
            raise Stop(f"fixture {tr}: {got}")
    print("fixture ok", show(s))


def playhead(sec, label):
    call("set_playhead", {"sequence": SEQ, "ticks": T(sec)}, label)


def select(*starts, label="select"):
    call("select_clips", {"sequence": SEQ, "clips": [f"{k}@{T(t)}" for t in starts for k in ("V1", "A1")]}, label)


def key(cmd, label):
    call("key_command", {"command": cmd, "focus": "timeline", "sequence": SEQ}, label)


def menu(path, label):
    call("menu_command", {"path": path, "focus": "timeline", "sequence": SEQ}, label)


# test: (setup for the tier-2/3 route, the route, the tier-1 composite as edit_clips ops); times in s
f1 = 1 / 30
TESTS = {
    "ripple_delete": (lambda: select(4, label="rd-sel"), lambda: menu("Edit > Ripple Delete", "rd-route"),
                      [*both(4, "remove", ripple=True)]),
    "ripple_trim": (lambda: playhead(3, "rt-ph"), lambda: key("cmd.sequence.rippletrimnextedittoplayhead", "rt-route"),
                    [*both(0, "trim_out", out_ticks=T(3)), *both(4, "move", dt_ticks=T(-1)), *both(8, "move", dt_ticks=T(-1))]),
    "roll": (lambda: playhead(4, "roll-ph"), lambda: (menu("Sequence > Trim Edit", "roll-trimedit"), key("cmd.sequence.trimforward", "roll-route")),
             [*both(4, "trim_in", in_ticks=T(1 + f1)), *both(0, "trim_out", out_ticks=T(4 + f1))]),
    "slip": (lambda: select(4, label="slip-sel"), lambda: key("cmd.timeline.slip.right.one", "slip-route"),
             [*both(4, "trim_out", out_ticks=T(5 - f1)), *both(4, "move", dt_ticks=T(f1)), *both(4, "trim_in", in_ticks=T(1 - f1))]),
    "slide": (lambda: select(4, label="slide-sel"), lambda: key("cmd.timeline.slide.right.one", "slide-route"),
              [*both(8, "trim_in", in_ticks=T(1 + f1)), *both(4, "move", dt_ticks=T(f1)), *both(0, "trim_out", out_ticks=T(4 + f1))]),
    "lift": (lambda: call("set_in_out", {"sequence": SEQ, "in_ticks": T(3), "out_ticks": T(5)}, "lift-io"),
             lambda: menu("Sequence > Lift", "lift-route"),
             [*both(0, "trim_out", out_ticks=T(3)), *both(4, "trim_in", in_ticks=T(2))]),
    "extract": (lambda: call("set_in_out", {"sequence": SEQ, "in_ticks": T(3), "out_ticks": T(5)}, "ex-io"),
                lambda: menu("Sequence > Extract", "ex-route"),
                [*both(0, "trim_out", out_ticks=T(3)), *both(4, "trim_in", in_ticks=T(2)), *both(4, "move", dt_ticks=T(-2)),
                 *both(8, "move", dt_ticks=T(-2))]),
}


def run(name):
    setup, route, ops = TESTS[name]
    rec = {"test": name}
    base, _, _ = snap(f"{name}-base")
    setup()
    before, _, _ = snap(f"{name}-before")
    rec["setup_changed_clips"] = before != base
    route()
    after_route, _, _ = snap(f"{name}-after-route")
    rec["route_changed"] = after_route != before
    rec["after_route"] = show(after_route)
    if after_route != before:
        rec["route_undo_steps"] = undo_back(before, after_route, f"{name}-route")
    try:
        call("edit_clips", edits(*ops), f"{name}-composite")
        after_c, _, _ = snap(f"{name}-after-composite")
        rec["composite_ok"] = True
    except Stop as e:
        rec["composite_ok"], rec["composite_error"] = False, str(e)[:500]
        after_c, _, _ = snap(f"{name}-after-composite-fail")
    rec["after_composite"] = show(after_c)
    rec["match"] = after_c == after_route
    if after_c != before:
        rec["composite_undo_steps"] = undo_back(before, after_c, f"{name}-composite")
    if before != base:  # the setup's own step (In/Out marks leave no clip change, so nothing to undo here)
        undo_back(base, before, f"{name}-setup")
    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec, indent=1))


if __name__ == "__main__":
    for a in sys.argv[1:]:
        if a == "fixture":
            fixture()
        else:
            for n in (TESTS if a == "all" else [a]):
                run(n)
