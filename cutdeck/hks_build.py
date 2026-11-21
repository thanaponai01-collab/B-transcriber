"""HKS build plan step 1e: replay a finished output sequence with the panel's build_sequence.

The item list comes from the saved project (``prproj_reader``): the footage (video and audio,
paired into one linked placement when in sync), film damage, the V8 clock-blur adjustment layers
and the BGM pieces with their Volume Level. The panel builds it on a cleared copy of the same
sequence and reports every item off by more than one frame.

Motion goes out only where it differs from a freshly placed clip. Scale Width and Uniform Scale
are never sent: Scale Width is ignored while Uniform is on, and writing either is OPEN
(PREMIERE_FACTS "Panel writes of Scale Width, Uniform Scale ...").

Not replayed, and counted in ``skipped`` by cause: disabled and speed-changed clips, keyframed
Motion fields, non-uniform scale, any other effect on a placed clip (``effect dropped: <match
name>``; on film damage that is its Opacity, i.e. the blend mode), blur layers off V8 (their box
was never measured) and every clip of another kind (graphics, AE comps, other adjustment layers,
glitch overlays, SFX). The YT clock blur is an effect mask, which no API can draw (PREMIERE_FACTS,
HKS spike 1b), so a V8 blur layer gets the clock box as a Motion crop instead (route 2), at
Blurriness 60: the reader returns no Gaussian Blur params, so the original value is not known.

``--compare BUILT`` is the offline proof: it reads both sequences from the saved project and
lists every item that is missing, extra, off by more than a frame, or has other Motion or level.

    python -m cutdeck.hks_build test_projects/hks_spike/hks_spike.prproj --smoke --out smoke.json
    python -m cutdeck.hks_build test_projects/hks_spike/hks_spike.prproj --name "HKS build 1e" --run --save
    python -m cutdeck.hks_build test_projects/hks_spike/hks_spike.prproj --compare "HKS build 1e"
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import ntpath
import sys
from collections import Counter
from pathlib import Path

from cutdeck.prproj_reader import PPRO_TICKS_PER_SECOND, read_project

FRAME = 0.04  # one frame at 25 fps
FRAME_TICKS = PPRO_TICKS_PER_SECOND // 25
HALF = FRAME / 2
MATCH_WINDOW = 1.0  # --compare pairs items whose start and source in are both this close (s)
TOL = 1e-4  # saved Motion values are float32
MEDIA_KINDS = {"hks ": "footage", "film_damage": "film damage", "[bgm]": "bgm"}  # file name prefix -> kind
VIDEO_KINDS = {"footage", "film damage", "blur"}
AUDIO_KINDS = {"footage", "bgm"}
MOTION = "AE.ADBE Motion"
BLUR = "AE.ADBE Gaussian Blur 2"
# V8 (index 7): the track of the blur item spike 1b cloned to measure the clock box
# (uxp/cutdeck/hksSpikeProbe.js probeBlur). The V9 blur layers cover another box, never measured.
CLOCK_BLUR_TRACK = 7
# The YT clock box as Motion crop percent, from the 1b clone frame (x 39-446, y 12-154 of 1920x1080).
CLOCK_CROP = {"cropLeft": 2.0, "cropTop": 1.1, "cropRight": 76.7, "cropBottom": 85.7}
# Effects each kind replays; anything else on a placed clip is counted as dropped.
REPLAYED = {"footage": {MOTION}, "film damage": {MOTION}, "blur": {BLUR, MOTION}, "bgm": {"Volume"}}
ZERO_DB = 0.177828  # linear Volume / Channel Volume at 0 dB (PREMIERE_FACTS "Audio clip Volume")
FIXED_AUDIO = {"Volume", "Channel Volume"}
READER_FIELDS = {"position": "position", "scale": "scale", "scale_width": "scaleWidth", "uniform": "uniformScale",
                 "rotation": "rotation", "anchor": "anchorPoint", "crop_left": "cropLeft", "crop_top": "cropTop",
                 "crop_right": "cropRight", "crop_bottom": "cropBottom"}
# Motion on a freshly placed clip (PREMIERE_FACTS "Motion Scale + Position on a freshly placed clip": Scale 100).
FRESH_MOTION = {"position": {"x": 0.5, "y": 0.5}, "anchorPoint": {"x": 0.5, "y": 0.5}, "scale": 100.0,
                "rotation": 0.0, "cropLeft": 0.0, "cropTop": 0.0, "cropRight": 0.0, "cropBottom": 0.0}


def ticks(seconds: float) -> str:
    return str(round(seconds * PPRO_TICKS_PER_SECOND))


def _secs(tick_string: str) -> float:
    return int(tick_string) / PPRO_TICKS_PER_SECOND


def _file(clip: dict) -> str:
    return ntpath.basename(clip.get("media_path") or "").lower()


def _fx(effect: dict) -> str:
    return effect.get("match_name") or effect.get("name") or ""


def media_kind(path: str | None) -> str | None:
    name = ntpath.basename(path or "").lower()
    return next((kind for prefix, kind in MEDIA_KINDS.items() if name.startswith(prefix)), None)


def clip_kind(clip: dict) -> str | None:
    """footage / film damage / bgm by file name, blur for a Gaussian Blur adjustment layer, else None."""
    kind = media_kind(clip.get("media_path"))
    names = {_fx(e) for e in clip["effects"]}
    return kind or ("blur" if BLUR in names and names <= {BLUR, MOTION} else None)


def item_kind(item: dict) -> str:
    """What an item is, for --smoke: one per kind."""
    if "like" in item:
        return "blur"
    kind = media_kind(item["media"])
    if kind != "footage":
        return kind
    return {(True, True): "linked footage", (True, False): "video footage",
            (False, True): "audio footage"}[(item["v"] is not None, item["a"] is not None)]


def _same(a, b) -> bool:
    if isinstance(a, dict):
        return abs(a["x"] - b["x"]) <= TOL and abs(a["y"] - b["y"]) <= TOL
    return abs(a - b) <= TOL


def _motion(clip: dict, skipped: Counter) -> dict | None:
    """The Motion fields to send: those a freshly placed clip does not already have."""
    params = next((e.get("params") or {} for e in clip["effects"] if _fx(e) == MOTION), {})
    fields = {}
    for name, entry in params.items():
        if "keyframes" in entry:
            skipped["keyframed motion field"] += 1
            continue
        value = entry["value"]
        fields[READER_FIELDS[name]] = {"x": value[0], "y": value[1]} if isinstance(value, list) else value
    if fields.pop("uniformScale", True) is False:
        skipped["non-uniform scale"] += 1
    fields.pop("scaleWidth", None)
    out = {f: v for f, v in fields.items() if not _same(v, FRESH_MOTION[f])}
    return out or None


def _untouched(effect: dict) -> bool:
    """A fixed audio component at 0 dB is what a freshly placed clip has: nothing is lost."""
    params = effect.get("params") or {}
    return _fx(effect) in FIXED_AUDIO and all(abs(p.get("value", 0) - ZERO_DB) <= TOL for p in params.values())


def _count_dropped(clip: dict, kind: str, skipped: Counter) -> None:
    for e in clip["effects"]:
        if _fx(e) not in REPLAYED[kind] and not _untouched(e):
            skipped[f"effect dropped: {_fx(e)}"] += 1


def _skip_reason(clip: dict, kind: str | None, side: str, track: int) -> str | None:
    if clip["disabled"]:
        return "disabled"
    if abs((clip["source_out"] - clip["source_in"]) - (clip["end"] - clip["start"])) > HALF:
        return "speed changed"
    if kind not in (VIDEO_KINDS if side == "video" else AUDIO_KINDS):
        return f"{side}: {clip['name'][:40]}"
    if kind == "blur" and track != CLOCK_BLUR_TRACK:
        return f"blur on V{track + 1}: box never measured"
    return None


def items_from(seq: dict) -> tuple[list[dict], Counter]:
    """The build items for one saved sequence, and a count of what was left out and why."""
    skipped: Counter = Counter()
    items: list[dict] = []
    audio_left = [(t["index"], c) for t in seq["audio_tracks"] for c in t["clips"]]

    def item(clip: dict, v: int | None, a: int | None, **extra) -> dict:
        return {"id": f"{'V' if v is not None else 'A'}{(v if v is not None else a) + 1}@{clip['start']:.2f}",
                "in_ticks": ticks(clip["source_in"]), "out_ticks": ticks(clip["source_out"]),
                "at_ticks": ticks(clip["start"]), "v": v, "a": a, **extra}

    def in_sync(video: dict, audio: dict) -> bool:
        return _file(audio) == _file(video) and all(abs(audio[k] - video[k]) <= HALF for k in ("start", "end", "source_in"))

    for track in seq["video_tracks"]:
        v = track["index"]
        for clip in track["clips"]:
            kind = clip_kind(clip)
            reason = _skip_reason(clip, kind, "video", v)
            if reason:
                skipped[reason] += 1
                continue
            _count_dropped(clip, kind, skipped)
            if kind == "blur":
                items.append(item(clip, v, None, like={"kind": "video", "track": v, "start_ticks": ticks(clip["start"])},
                                  blur={"blurriness": 60}, motion=dict(CLOCK_CROP)))
                continue
            pair = None
            if kind == "footage":
                pair = next(((a, c) for a, c in audio_left if in_sync(clip, c) and not _skip_reason(c, "footage", "audio", a)), None)
            if pair:
                audio_left.remove(pair)
                _count_dropped(pair[1], kind, skipped)
            items.append(item(clip, v, pair[0] if pair else None, media=clip["media_path"], motion=_motion(clip, skipped)))
    for a, clip in audio_left:
        kind = clip_kind(clip)
        reason = _skip_reason(clip, kind, "audio", a)
        if reason:
            skipped[reason] += 1
            continue
        _count_dropped(clip, kind, skipped)
        extra = {}
        if kind == "bgm":
            extra["level"] = next((e["params"]["Level"]["value"] for e in clip["effects"] if "Level" in (e.get("params") or {})), None)
        items.append(item(clip, None, a, media=clip["media_path"], **extra))
    items.sort(key=lambda it: int(it["at_ticks"]))
    return items, skipped


def smoke(items: list[dict]) -> list[dict]:
    """The first item of each kind, for a small first live build."""
    first: dict[str, dict] = {}
    for it in items:
        first.setdefault(item_kind(it), it)
    return sorted(first.values(), key=lambda it: int(it["at_ticks"]))


def _lane(item: dict) -> tuple:
    return item["v"], item["a"], "blur" if "like" in item else (item["media"] or "").lower()


def compare(original: list[dict], built: list[dict]) -> list[str]:
    """Every difference between the original's items and the built sequence's, one line each.

    Items pair on the same tracks and media, nearest start and source in (within MATCH_WINDOW).
    Blur items compare timing only: the build crops where the original masks."""
    problems = []
    pool = list(built)
    for it in original:
        def distance(b: dict) -> float:
            return max(abs(_secs(b[k]) - _secs(it[k])) for k in ("at_ticks", "in_ticks"))
        near = [b for b in pool if _lane(b) == _lane(it) and distance(b) <= MATCH_WINDOW]
        if not near:
            problems.append(f"{it['id']}: missing")
            continue
        got = min(near, key=distance)
        pool.remove(got)
        for key in ("at_ticks", "in_ticks", "out_ticks"):
            off = int(got[key]) - int(it[key])
            if abs(off) > FRAME_TICKS:
                problems.append(f"{it['id']}: {key[:-6]} off by {off / PPRO_TICKS_PER_SECOND:+.3f} s")
        if item_kind(it) == "blur":
            continue
        want, have = {**FRESH_MOTION, **(it.get("motion") or {})}, {**FRESH_MOTION, **(got.get("motion") or {})}
        problems += [f"{it['id']}: {f} {want[f]} != {have[f]}" for f in FRESH_MOTION if not _same(want[f], have[f])]
        a, b = it.get("level"), got.get("level")
        if (a is None) != (b is None) or (a is not None and not math.isclose(a, b, rel_tol=TOL)):
            problems.append(f"{it['id']}: level {a} != {b}")
    return problems + [f"{b['id']}: extra" for b in pool]


def _sequence(project: dict, name: str) -> dict:
    found = [s for s in project["sequences"] if s["name"] == name and any(t["clips"] for t in s["video_tracks"])]
    if len(found) != 1:
        raise SystemExit(f'{len(found)} sequences named "{name}" have clips; need exactly one.')
    return found[0]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Replay a saved output sequence through build_sequence (HKS step 1e).")
    p.add_argument("project", help="the saved .prproj (the same project Premiere has open)")
    p.add_argument("--sequence", default="1 YOUTUBE D1")
    p.add_argument("--name", default="HKS build 1e")
    p.add_argument("--out", help="write the build arguments as JSON here")
    p.add_argument("--smoke", action="store_true", help="only the first item of each kind (with --compare: of the original)")
    p.add_argument("--run", action="store_true", help="send it to the CutDeck panel (Premiere must be open)")
    p.add_argument("--save", action="store_true", help="with --run: save the project after the build")
    p.add_argument("--compare", metavar="BUILT", help="compare --sequence with the built sequence BUILT in the saved project")
    args = p.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    project = read_project(args.project)
    items, skipped = items_from(_sequence(project, args.sequence))
    if args.smoke:
        items = smoke(items)
    if args.compare:
        problems = compare(items, items_from(_sequence(project, args.compare))[0])
        print(json.dumps({"compared": len(items), "differences": len(problems), "first": problems[:40]},
                         ensure_ascii=False, indent=1))
        return 1 if problems else 0
    build = {"project": str(Path(args.project).resolve()), "base": args.sequence, "name": args.name,
             "items": items, "save": args.save}
    if args.out:
        Path(args.out).write_text(json.dumps(build, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"items": len(items), "linked": sum(i["v"] is not None and i["a"] is not None for i in items),
                      "kinds": dict(Counter(map(item_kind, items))),
                      "motion fields per item": dict(sorted(Counter(len(i["motion"]) for i in items if i.get("motion")).items())),
                      "skipped": dict(skipped)}, ensure_ascii=False, indent=1))
    if args.run:
        from cutdeck.ai_backend import Backend
        print(json.dumps(asyncio.run(Backend().premiere("build_sequence", build)), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
