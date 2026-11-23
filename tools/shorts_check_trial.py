"""Fresh Shorts-check trial on the user's own older Shorts (issue 128).

Protocol: issue 128 comment of 2026-11-23. Runs the trial half; `held` runs the held-out half.
    python tools/shorts_check_trial.py [trial|held]
"""
import glob, json, os, re, sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from cutdeck.prproj_reader import read_project
from cutdeck import shorts_check as sc

ROOT = r"E:\Me\2.Tasks"
SHORT = re.compile(r"\btt\b", re.I)
sys.stdout.reconfigure(encoding="utf-8")

eps = []
for d in sorted(os.listdir(ROOT)):
    if not (d[:8].isdigit() and "20260901" <= d[:8] and d < "20261121"):
        continue
    projs = [p for p in glob.glob(os.path.join(ROOT, d, "**", "*.prproj"), recursive=True) if "Auto-Save" not in p]
    if not projs:
        continue
    p = max(projs, key=os.path.getmtime)
    seqs = [s for s in read_project(p)["sequences"] if s["frame"] == [1080, 1920] and SHORT.search(s["name"])]
    if seqs:
        eps.append((d, p, seqs))

half = eps[1::2] if sys.argv[1:] == ["held"] else eps[0::2]
print("run:", [e[0] for e in half])
pat = re.compile(sc.FEED, re.I)
total = shorts = blind = 0
for d, p, seqs in half:
    for s in seqs:
        flags = sc.check_sequence(s)
        clips = [c for t in s["video_tracks"] if not t["muted"] for c in t["clips"] if not c["disabled"]]
        for a, b in sc._merge([(c["start"], c["end"]) for c in clips]):
            inside = [c for c in clips if sc._clip_in((c["start"], c["end"]), a, b)]
            feed = sum(sc._is_feed(c, pat) and not sc._is_still(c) for c in inside)
            boxes = sum(sc._box(c, s["frame"]) is not None for c in inside)
            title = any(sc._is_text(c) and abs(c["start"] - a) <= sc.TOL for c in inside)
            nested = sum("nested_sequence" in c for c in inside)
            f = [x for x in flags if x["short"] == [round(a, 2), round(b, 2)]]
            shorts += 1; total += len(f); blind += feed == 0
            print(f"{d} | {s['name']} | {a:.2f}-{b:.2f} | feed {feed} boxes {boxes} title {title} nested {nested} | "
                  + json.dumps(f, ensure_ascii=False))
print(f"Shorts {shorts}, flags {total}, moving-video blind {blind}")
