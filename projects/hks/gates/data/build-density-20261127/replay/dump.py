"""Text dump of the agent's 20261126 YT v1 at its HANDOVER OK save (17:41), for the build replay.
Every clip with its track, timeline and source times, scale and effects; body pieces and covers with
the source words they play (questions.lines.json, same source file). Writes timeline.md here."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[5]))
from cutdeck.prproj_reader import read_project  # noqa: E402

DAY = Path("G:/Me/Works/20261126 - โหนกระแส/4. PROJECTS/1. PREMIERE PRO")
SAVE = DAY / "CutDeck/Drafts/1 YOUTUBE agent v1 20261126-174119.prproj"
LINES = Path("E:/Me/5.Claude/Transcriber_v2/test_projects/hks_judge/20261126/questions.lines.json")
SRC = "HKS Facebook 261169 Full.mp4"

lines = json.loads(LINES.read_text(encoding="utf-8"))[SRC]["lines"]


def clock(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def words(a, b):
    return " / ".join(l[3] for l in lines if l[2] > a + 0.05 and l[1] < b - 0.05)


def fx(c):
    out = []
    for e in c.get("effects", []):
        if e["name"] == "Motion":
            p = e["params"]
            out.append(f"scale {p['scale']['value']:.0f} pos {p['position']['value'][0]:.2f},{p['position']['value'][1]:.2f}")
        elif e["name"] not in ("Opacity", "Time Remapping", "Volume", "Channel Volume", "Panner"):
            out.append(e["name"] + (" (off)" if e.get("bypass") else ""))
    return "; ".join(out)


p = read_project(SAVE)
s = next(s for s in p["sequences"] if s["name"] == "1 YOUTUBE agent v1")
end = max(c["end"] for t in s["video_tracks"] + s["audio_tracks"] for c in t.get("clips", []))
out = [f"# Timeline: `1 YOUTUBE agent v1` (saved at handover, {clock(end)} long)", "",
       "Times are m:ss.ss. Timeline = position in the draft; source = position in the broadcast file "
       f"`{SRC}`. Words are the automatic transcript of the source span the clip plays (errors and all).", ""]
for kind, tag in (("video_tracks", "V"), ("audio_tracks", "A")):
    for i, t in enumerate(s[kind], 1):
        cs = t.get("clips", [])
        out.append(f"## {tag}{i}: {len(cs)} clips" + (" (empty)" if not cs else ""))
        out.append("")
        for c in cs:
            src = c["name"] == SRC
            row = (f"- tl {clock(c['start'])}-{clock(c['end'])} ({c['end'] - c['start']:.2f} s) `{c['name']}`"
                   + (f" src {clock(c['source_in'])}-{clock(c['source_out'])}" if src else "")
                   + (" DISABLED" if c.get("disabled") else "") + (f" [{fx(c)}]" if fx(c) else ""))
            if src and kind == "video_tracks" and i >= 3:
                # a cover: what its own source says, and the body words it sits over
                under = [b for b in s["audio_tracks"][0].get("clips", []) if b["start"] < c["end"] and b["end"] > c["start"]]
                said = " | ".join(words(b["source_in"] + max(0, c["start"] - b["start"]),
                                        b["source_in"] + min(b["end"], c["end"]) - b["start"]) for b in under)
                row += f"\n  - cover footage's own words: {words(c['source_in'], c['source_out'])[:200]}\n  - body words under it: {said[:200]}"
            elif src and kind == "audio_tracks" and i == 1:
                row += f"\n  - words: {words(c['source_in'], c['source_out'])}"
            out.append(row)
        out.append("")
(HERE / "timeline.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print(len("\n".join(out)), "chars", clock(end))
