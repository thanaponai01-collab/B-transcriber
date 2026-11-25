"""hks_cut_check.py: the agent's own HKS cut mistakes, found in a saved sequence before handover.

Rules: projects/hks/rules.md "Trims and split edits" (HKS-32, HKS-33). Three checks, read from the
saved .prproj only (never Premiere), with the picture the viewer sees = the topmost enabled footage
clip (adjustment layers and graphics have no media file and are skipped):

1. ``visible_cuts_in_speech``: a sound cut on A1 that the viewer also sees, because the picture
   there is the speaker's own picture in sync, and the source is not quiet at the cut. That is a cut
   mid-thought (or mid-word) in plain view. The audio decides, not the engine's word boundaries
   (which split Thai words).
2. ``same_frame_cuts``: sound cuts where the picture also changes on the same frame. Not an error
   one by one; the share is compared with the user's (20261124 YT body: 12 of 173, 7%).
3. ``unsafe_holds``: the held picture of a J or L cut, i.e. a clip that plays in sync with A1 in one
   part and out of sync in another, where its own source has words in the out-of-sync part. Someone
   is seen talking without their sound (user, 2026-11-25: hold only a stopped or still person,
   else B-roll). Words in the source don't prove a talking face is on screen (the broadcast may show
   film or a wide shot there): look at the frames of every hold listed.

An edge is in a pause when the audio is quiet there or it sits in a gap of 0.15 s or more between two
words (the broadcast's room tone and music keep the level up through real pauses). On the 20261124 YT
body this lists 14 edges in the agent's v4, 3 after its fixes, and 9 in the user's D1, most of those
the user's cut on a repeated word ("เหรอ | เหรอ"). Holds over film the broadcast cut to are listed too
(words in the source, no face on screen): look at the frames. Fix or justify each item in the handover.

    python -m cutdeck.hks_cut_check --prproj <day>.prproj --sequence "1 YOUTUBE agent v5" [--from 32]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from cutdeck.timeline_transcript import (ENVELOPE_MS, TAIL_DB, noise_floor, source_levels,
                                         source_words, media_sha256)

FOOTAGE = re.compile(r"\.(mp4|mov|mxf|m4v|avi|png|jpe?g|tif{1,2}|psd)$", re.I)
QUIET_REACH_MS = 120   # a cut within this of a quiet 10 ms window sits in a pause
WORD_GAP_S = 0.15      # a gap this long between two words is a pause even over room tone or music
EDGE_TOL_S = 0.04      # an edge this close to such a gap counts as in it
HOLD_MIN_FRAMES = 3    # an out-of-sync stretch shorter than this is a trim rounding, not a hold


def footage(clip: dict) -> bool:
    return not clip.get("disabled") and bool(FOOTAGE.search(clip.get("media_path") or ""))


def visible(video_tracks: list[dict], t: float) -> dict | None:
    """The clip the viewer sees at ``t`` s: topmost enabled footage clip."""
    for track in reversed(video_tracks):
        for c in track.get("clips", []):
            if footage(c) and c["start"] <= t < c["end"]:
                return c
    return None


def src_at(clip: dict, t: float) -> float:
    return clip["source_in"] + (t - clip["start"])


def in_sync(pic: dict | None, snd: dict | None, t: float, frame: float) -> bool:
    return (pic is not None and snd is not None and pic.get("media_path") == snd.get("media_path")
            and abs(src_at(pic, t) - src_at(snd, t)) < frame / 2)


def sound_cuts(audio: list[dict]) -> list[tuple[float, dict | None, dict]]:
    """(time, outgoing clip or None, incoming clip) at every A1 cut that jumps in the source."""
    clips = sorted((c for c in audio if not c.get("disabled")), key=lambda c: c["start"])
    cuts = []
    for prev, cur in zip([None] + clips, clips):
        if (prev is not None and abs(prev["end"] - cur["start"]) < 0.02 and prev.get("media_path") == cur.get("media_path")
                and abs(prev["source_out"] - cur["source_in"]) < 0.02):
            continue  # a through-edit: the source plays on
        cuts.append((cur["start"], prev, cur))
    if clips:
        cuts.append((clips[-1]["end"], clips[-1], None))
    return cuts


def quiet_near(levels, threshold: float, src_s: float) -> bool:
    i = int(src_s * 1000 // ENVELOPE_MS)
    reach = QUIET_REACH_MS // ENVELOPE_MS
    window = levels[max(i - reach, 0):i + reach + 1]
    return bool(len(window)) and float(window.min()) < threshold


def in_word_gap(words, src_s: float) -> bool:
    """Is the edge in a pause between two words? The broadcast's room tone and music keep the level
    up through real pauses, so a gap in the words counts too. A Thai word the engine split in two
    has no gap, so a cut through it is still caught."""
    before = [w for w in words if w.start_ms < src_s * 1000]
    if not before:
        return True
    last = max(before, key=lambda w: w.end_ms)
    after = [w for w in words if w.start_ms >= src_s * 1000 - EDGE_TOL_S * 1000 and w is not last]
    nxt = min((w.start_ms for w in after), default=None)
    if nxt is None:
        return True
    return nxt / 1000 - last.end_ms / 1000 >= WORD_GAP_S and last.end_ms / 1000 <= src_s + EDGE_TOL_S


def words_in(words, a_s: float, b_s: float) -> list[str]:
    # 1 ms inside each end, so a word that only touches the span (float rounding) is not in it
    return [w.text for w in words if w.end_ms > a_s * 1000 + 1 and w.start_ms < b_s * 1000 - 1]


def check(sequence: dict, sources: dict, fps: float = 25.0, body_from: float = 0.0) -> dict:
    """``sources`` maps a media path to (words, levels or None)."""
    frame = 1.0 / fps
    vtracks = sequence["video_tracks"]
    audio = sequence["audio_tracks"][0]["clips"]
    in_speech, same_frame, n_cuts = [], [], 0
    for t, out_clip, in_clip in sound_cuts(audio):
        if t < body_from:
            continue
        n_cuts += 1
        before, after = visible(vtracks, t - frame / 2), visible(vtracks, t + frame / 2)
        if before is not after and in_sync(before, out_clip, t - frame / 2, frame) and in_sync(after, in_clip, t + frame / 2, frame):
            same_frame.append(round(t, 2))
        for side, clip, pic in (("out", out_clip, before), ("in", in_clip, after)):
            if clip is None or not in_sync(pic, clip, t + (frame / 2 if side == "in" else -frame / 2), frame):
                continue  # the viewer doesn't see this side's speaker: the cut is hidden
            words, levels = sources.get(clip.get("media_path"), ([], None))
            edge = clip["source_in"] if side == "in" else clip["source_out"]
            if levels is not None and quiet_near(levels, noise_floor(levels) + TAIL_DB, edge):
                continue
            if in_word_gap(words, edge):
                continue
            in_speech.append({"at_s": round(t, 2), "side": side, "src_s": round(edge, 2),
                              "before": "".join(words_in(words, edge - 1.5, edge)[-4:]),
                              "after": "".join(words_in(words, edge, edge + 1.5)[:4])})
    holds = []
    for track in vtracks:
        for pic in track.get("clips", []):
            if not footage(pic) or pic["end"] <= body_from:
                continue
            words, _ = sources.get(pic.get("media_path"), ([], None))
            if not words:
                continue
            states, t = [], pic["start"] + frame / 2
            while t < pic["end"]:
                shown = visible(vtracks, t) is pic
                snd = next((c for c in audio if not c.get("disabled") and c["start"] <= t < c["end"]), None)
                states.append((t, shown, in_sync(pic, snd, t, frame)))
                t += frame
            if not any(s for _, shown, s in states if shown):
                continue  # never in sync on screen: a cover or cutaway, not a split-edit hold
            run = []
            for t, shown, s in states + [(None, False, True)]:
                if shown and not s:
                    run.append(t)
                    continue
                if len(run) >= HOLD_MIN_FRAMES:
                    a, b = run[0] - frame / 2, run[-1] + frame / 2
                    said = words_in(words, src_at(pic, a), src_at(pic, b))
                    if said:
                        holds.append({"at_s": round(a, 2), "to_s": round(b, 2), "src_s": round(src_at(pic, a), 2),
                                      "words_in_picture": "".join(said)})
                run = []
    return {"sequence": sequence["name"], "sound_cuts": n_cuts,
            "visible_cuts_in_speech": in_speech, "same_frame_cuts": same_frame, "unsafe_holds": holds}


def main(argv: list[str] | None = None) -> int:
    from cutdeck.prproj_reader import read_project
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prproj", required=True)
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--fps", type=float, default=25.0)
    ap.add_argument("--from", dest="body_from", type=float, default=0.0, help="check from this time (s), e.g. after the hook")
    ap.add_argument("--db", default="transcriber.db")
    ap.add_argument("--levels", default="output/timeline_transcripts/levels")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    found = [s for s in read_project(args.prproj)["sequences"]
             if s["name"] == args.sequence and any(t.get("clips") for t in s["audio_tracks"])]
    if not found:
        print(f"no sequence {args.sequence!r} with audio clips", file=sys.stderr)
        return 2
    seq = found[0]
    sources = {}
    for media in {c.get("media_path") for c in seq["audio_tracks"][0]["clips"]} - {None}:
        if Path(media).is_file():
            got = source_words(media, Path(args.db))
            levels = None
            try:
                levels = source_levels(media, Path(args.levels) / f"{media_sha256(media, Path(args.db))}.npy")
            except (RuntimeError, OSError):
                pass
            sources[media] = (got[1] if got else [], levels)
    result = check(seq, sources, args.fps, args.body_from)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        n = result["sound_cuts"]
        print(f"{result['sequence']}: {n} sound cuts")
        print(f"  visible cuts in speech: {len(result['visible_cuts_in_speech'])}")
        for e in result["visible_cuts_in_speech"]:
            print(f"    {e['at_s']:8.2f} {e['side']:3} src {e['src_s']:8.2f}  {e['before']} | {e['after']}")
        print(f"  sound + picture cut on the same frame: {len(result['same_frame_cuts'])} of {n}"
              f" ({100 * len(result['same_frame_cuts']) // max(n, 1)}%; the user's 20261124 YT body: 12 of 173)")
        print(f"  unsafe J/L holds (someone talks in the held picture): {len(result['unsafe_holds'])}")
        for h in result["unsafe_holds"]:
            print(f"    {h['at_s']:8.2f}-{h['to_s']:8.2f} src {h['src_s']:8.2f}  {h['words_in_picture']}")
    return 1 if result["visible_cuts_in_speech"] or result["unsafe_holds"] else 0


if __name__ == "__main__":
    sys.exit(main())
