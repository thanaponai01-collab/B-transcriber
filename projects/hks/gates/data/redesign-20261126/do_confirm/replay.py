"""Replay three do-confirm answer-check designs on 20261125 YT agent v1 (K22, unfinished ends).

    python output/hks_rules/do_confirm/replay.py

Reads only: values copied from the session log (2ce93c3f, constants below), the 19:46 auto-save and the day project (G:, read-only),
transcriber.db and the level cache in the main checkout, projects/hks/gates/data/. Writes
results.json next to this file.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from cutdeck import hks_gates  # noqa: E402
from cutdeck.hks_piece_ends import piece_ends  # noqa: E402
from cutdeck.prproj_reader import read_project  # noqa: E402

HERE = Path(__file__).resolve().parent
MEDIA = "G:\\Me\\Works\\20261125 - โหนกระแส\\1. FOOTAGE\\HKS Facebook 251169 Full.mp4"
PROJ = Path("G:/Me/Works/20261125 - โหนกระแส/4. PROJECTS/1. PREMIERE PRO")
AUTOSAVE_1946 = PROJ / "Adobe Premiere Pro Auto-Save/20261125 - โหนกระแส--e7b6a2f0-896c-40f9-ea09-8348d4c12168-2026-11-25_19-46-22.prproj"
FINAL = PROJ / "20261125 - โหนกระแส.prproj"  # saved 22:02, after the user's edit and D2 export
SEQ = "1 YOUTUBE agent v1"
BODY_FROM = 26.76

# --- v1 A1 as handed over at 19:27, rebuilt from the session's own read-backs -------------------
# 12:18:24Z read_timeline of A1 after keep_words (start, end, src_in, src_out), 40 clips.
KEEP_WORDS_A1 = [
    (0.0, 48.36, 116.56, 164.92), (48.36, 126.6, 266.8, 345.04), (126.6, 145.36, 370.88, 389.64),
    (145.36, 157.84, 406.56, 419.04), (157.84, 160.36, 610.88, 613.4), (160.36, 250.48, 613.4, 703.52),
    (250.48, 261.0, 721.8, 732.32), (261.0, 355.04, 732.32, 826.36), (355.04, 413.88, 1032.72, 1091.56),
    (413.88, 443.04, 1151.84, 1181.0), (443.04, 454.4, 1211.16, 1222.52), (454.4, 475.96, 1540.68, 1562.24),
    (475.96, 491.96, 1757.8, 1773.8), (491.96, 504.0, 1809.04, 1821.08), (504.0, 506.32, 2346.08, 2348.4),
    (506.32, 540.36, 2348.4, 2382.44), (540.36, 566.76, 2411.48, 2437.88), (566.76, 598.96, 2642.8, 2675.0),
    (598.96, 627.68, 2867.96, 2896.68), (627.68, 647.64, 2928.88, 2948.84), (647.64, 651.68, 2954.48, 2958.52),
    (651.68, 688.12, 3013.84, 3050.28), (688.12, 720.92, 3050.28, 3083.08), (720.92, 774.44, 3153.88, 3207.4),
    (774.44, 795.76, 3234.48, 3255.8), (795.76, 873.28, 3271.16, 3348.68), (873.28, 886.48, 3455.08, 3468.28),
    (886.48, 911.88, 3484.68, 3510.08), (911.88, 975.32, 3512.92, 3576.36), (975.32, 992.4, 3931.76, 3948.84),
    (992.4, 1027.96, 4008.32, 4043.88), (1027.96, 1059.52, 4049.48, 4081.04), (1059.52, 1061.12, 4286.84, 4288.44),
    (1061.12, 1098.32, 4288.44, 4325.64), (1098.32, 1139.04, 4549.84, 4590.56), (1139.04, 1181.92, 5012.6, 5055.48),
    (1181.92, 1234.32, 5059.6, 5112.0), (1234.32, 1245.24, 5113.44, 5124.36), (1245.24, 1275.92, 5171.96, 5202.64),
    (1275.92, 1299.24, 5308.16, 5331.48),
]
SWAP = (3455.08, 3484.68)  # 12:18:39Z build_sequence: the daughter's answer after Off's wife
# 12:20:19Z edge moves (side, old src, new src); 12:20:46Z moved 1032.88 on to 1032.04.
EDGES = [("out", 389.64, 389.95), ("out", 826.36, 826.60), ("in", 1032.72, 1032.04), ("out", 1091.56, 1091.90),
         ("out", 1181.00, 1180.92), ("in", 2867.96, 2867.60), ("out", 3348.68, 3347.00), ("out", 4043.88, 4044.20),
         ("in", 5059.60, 5059.20)]
HOOK = [(1211.16, 1217.72), (1734.40, 1738.20), (3331.20, 3344.80)]  # hook in 3331.4 -> 3331.2
# 12:25:20Z read-back after every A1 edit (V2 == A1 then; the J/L calls after it touched V2 only):
# (out src of a piece, in src of the next) at each body cut. 389.96 is 389.95 frame-rounded.
READBACK = [(164.92, 266.8), (345.04, 370.88), (389.96, 406.56), (419.04, 610.88), (703.52, 721.8),
            (2382.44, 2411.48), (2437.88, 2642.8), (2675.0, 2867.6), (2896.68, 2928.88), (2948.84, 2954.48),
            (2958.52, 3013.84), (3083.08, 3153.88), (3207.4, 3234.48), (3255.8, 3271.16), (3347.0, 3484.68),
            (3510.08, 3455.08), (3468.28, 3512.92), (3576.36, 3931.76), (3948.84, 4008.32), (4044.2, 4049.48),
            (4081.04, 4286.84), (4325.64, 4549.84), (4590.56, 5012.6), (5055.48, 5059.2), (5112.0, 5113.44),
            (5124.36, 5171.96), (5202.64, 5308.16)]


# 12:24:57Z cut check --json: same-frame sound cuts after every A1 edit (36 of 39 sound cuts).
LOGGED_CUTS = [6.56, 10.36, 75.32, 153.56, 172.64, 185.12, 277.76, 382.56, 442.44, 471.52, 482.88, 504.44,
               520.44, 532.48, 568.84, 595.24, 627.44, 656.52, 676.48, 680.52, 749.76, 803.28, 824.6, 900.44,
               925.84, 939.04, 1002.48, 1019.56, 1055.44, 1087.0, 1125.8, 1166.52, 1209.4, 1262.2, 1273.12, 1303.8]
BODY_START = 26.96  # the hook in-point moved 3331.4 -> 3331.2, so the body starts 0.2 s later


def frame(s: float) -> float:
    return round(round(s * 25) / 25, 2)


def v1_a1(edges: list = EDGES) -> list[dict]:
    pieces = [[a, b] for _, _, a, b in KEEP_WORDS_A1]
    i, j = (next(k for k, p in enumerate(pieces) if p[0] == s) for s in SWAP)
    pieces[i], pieces[j] = pieces[j], pieces[i]
    for side, old, new in edges:
        k = 0 if side == "in" else 1
        (p,) = [p for p in pieces if abs(p[k] - old) < 0.02]
        p[k] = new
    pieces = [list(h) for h in HOOK] + pieces
    clips, t = [], 0.0
    for n, (a, b) in enumerate(pieces):
        a, b = frame(a), frame(b)
        if n == len(HOOK):
            t = BODY_START
        clips.append({"start": frame(t), "end": frame(t + b - a), "source_in": a, "source_out": b,
                      "disabled": False, "media_path": MEDIA})
        t = frame(t + b - a)
    return clips


def validate(clips: list[dict], ends: list[dict]) -> dict:
    body = [c for c in clips if c["start"] >= BODY_FROM]
    pairs = [(a["source_out"], b["source_in"]) for a, b in zip(body, body[1:])
             if abs(a["source_out"] - b["source_in"]) > 0.02]
    at = [e["at_s"] for e in ends]
    # The 12:25Z read-back skipped cuts within 30 frames of a V3 cover; the 12:24Z cut list has those.
    return {"readback_pairs_missing_from_rebuild": [p for p in READBACK if p not in pairs],
            "readback_pairs_confirmed": sum(p in READBACK for p in pairs),
            "logged_cut_times_matched": sum(any(abs(t - x) < 0.02 for x in at) for t in LOGGED_CUTS if t > BODY_FROM),
            "logged_body_cut_times": sum(t > BODY_FROM for t in LOGGED_CUTS),
            "rebuilt_ends_not_in_logged_cuts": [x for x in at if not any(abs(t - x) < 0.02 for t in LOGGED_CUTS)]}


def a1_of(path: Path) -> list[dict]:
    seq = next(s for s in read_project(path)["sequences"] if s["name"] == SEQ
               and any(t.get("clips") for t in s["audio_tracks"]))
    return seq["audio_tracks"][0]["clips"]


def merged(clips: list[dict]) -> list[dict]:
    """Pieces as the viewer hears them: a razor split where the source plays on is not an end."""
    out = []
    for c in sorted((c for c in clips if not c.get("disabled")), key=lambda c: c["start"]):
        p = out[-1] if out else None
        if p and abs(p["end"] - c["start"]) < 0.02 and p["media_path"] == c["media_path"] \
                and abs(p["source_out"] - c["source_in"]) < 0.02:
            p["end"], p["source_out"] = c["end"], c["source_out"]
        else:
            out.append(dict(c))
    return out


def said(words, a: float, b: float) -> list[str]:
    return [w.text for w in words if a * 1000 <= w.start_ms < b * 1000]


def verdict(src: float, user: list[dict], words) -> tuple[str, str]:
    """The user's verdict on one agent end, by source (backtest.md "Endings"), on merged pieces,
    with "changed" split by direction: played through = the user let it run on (K22's sense)."""
    ends = [c["source_out"] for c in user]
    if any(abs(e - src) <= 0.3 for e in ends):
        return "kept", ""
    over = [c for c in user if c["source_in"] < src - 0.3 and c["source_out"] > src + 0.3]
    if over:
        return "changed: played through", f"user plays on to {over[0]['source_out']:.2f}"
    near = [e for e in ends if abs(e - src) <= 2.0]
    if not near:
        return "dropped", ""
    e = min(near, key=lambda e: abs(e - src))
    cut = said(words, min(e, src), max(e, src))
    if not cut:
        return "kept", f"user ends at {e:.2f} ({e - src:+.2f} s), no word between: a trim in the pause"
    return ("changed: ended later" if e > src else "changed: ended earlier"), \
        f"user ends at {e:.2f} ({e - src:+.2f} s): {' '.join(cut)}"


def unplayed(src: float, user_to: float, v1: list[dict], words) -> str:
    """Words the user played after an agent end that v1 never played anywhere."""
    body = [c for c in v1 if c["start"] >= BODY_FROM]
    return " ".join(w.text for w in words if src * 1000 <= w.start_ms < user_to * 1000
                    and not any(c["source_in"] * 1000 <= w.start_ms < c["source_out"] * 1000 for c in body))


def main() -> int:
    v1 = v1_a1()
    final_all = [c for c in a1_of(FINAL) if not c.get("disabled") and c.get("media_path") == MEDIA]
    # The final opens on a 0-23.36 s hook of body source (828.04-971.04, read from the save): leave it
    # out of the play-through test, or a teaser that spans an agent end would read as "played through".
    hook_end = 23.36
    final = merged([c for c in final_all if c["start"] >= hook_end - 0.05])
    a1946 = a1_of(AUTOSAVE_1946)
    sources = hks_gates.load_sources({"audio_tracks": [{"clips": v1}]}, hks_gates.MAIN / "transcriber.db",
                                     hks_gates.MAIN / "output/timeline_transcripts/levels")
    review = json.loads((ROOT / "projects/hks/gates/data/endings-review.json").read_text(encoding="utf-8"))
    items = [i for i in review["items"] if i["day"] == "20261125" and i["who"] == "agent"]

    def rater(src):
        it = min(items, key=lambda i: abs(i["src_end"] - src))
        if abs(it["src_end"] - src) > 0.5:
            return None
        return {"id": it["id"], "backtest_verdict": it["verdict"],
                "sonnet": review["raters"]["sonnet"]["labels"].get(it["id"]),
                "opus": review["raters"]["opus"]["labels"].get(it["id"])}

    words = sources[MEDIA][0]
    ends = piece_ends(v1, sources, BODY_FROM)
    mismatch = validate(v1, ends)
    body = [c for c in v1 if c["start"] >= BODY_FROM]
    for e in ends:
        e["user"], e["user_detail"] = verdict(e["src_s"], final, words)
        e["rater"] = rater(e["src_s"])
        nxt = next((b["source_in"] for a, b in zip(body, body[1:]) if a["source_out"] == e["src_s"]), None)
        e["v1_next_in"] = nxt
        if e["user"] == "changed: played through":
            to = float(e["user_detail"].split()[-1])
            e["user_detail"] += f"; v1's next piece starts at {nxt}; words v1 never played: {unplayed(e['src_s'], to, v1, words)}"
    ends_1946 = piece_ends(a1946, sources, BODY_FROM)
    for e in ends_1946:
        e["user"], e["user_detail"] = verdict(e["src_s"], final, words)
    # Before the agent moved 10 edges to pauses (12:19Z cut check: 9 visible in speech).
    prefix = piece_ends(v1_a1(edges=[]), sources, BODY_FROM)
    for e in prefix:
        e["user"], e["user_detail"] = verdict(e["src_s"], final, words)
    out = {"prefix_flagged": [e for e in prefix if e["in_speech"] or e["continuation"]], "v1_rebuild_mismatches_vs_readback": mismatch, "final_hook_end_s": hook_end,
           "final_body_pieces": len(final), "v1_body_ends": ends, "autosave_1946_body_ends": ends_1946}
    (HERE / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"rebuild vs 12:25Z read-back: {mismatch}")
    print(f"final: hook ends {hook_end}, body A1 pieces {len(final)}")
    for name, es in (("v1 @19:27 (rebuilt)", ends), ("19:46 auto-save", ends_1946)):
        from collections import Counter
        print(f"\n{name}: {len(es)} body ends; user verdicts {dict(Counter(e['user'] for e in es))}")
        print(f"  in_speech {sum(e['in_speech'] for e in es)}, continuation {sum(bool(e['continuation']) for e in es)}")
    print(f"\nbefore the edge moves: {len(prefix)} ends, flagged:")
    for e in out["prefix_flagged"]:
        print(f"  {e['at_s']:8.2f} src {e['src_s']:8.2f} {e['user']:24} {e['continuation']} …{e['last_words'][-30:]}")
    print("\nv1 ends:")
    for e in ends:
        flag = ("S" if e["in_speech"] else "-") + ("C" if e["continuation"] else "-")
        r = e["rater"] or {}
        print(f"  {e['at_s']:8.2f} src {e['src_s']:8.2f} {flag} {e['user']:24} son {r.get('sonnet')} opus {r.get('opus')}  …{e['last_words'][-40:]}")
        if e.get("user_detail"):
            print(f"           {e['user_detail']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
