"""xml_export.py — CutPlan → FCP7 (xmeml v5) XML for Premiere (IMPLEMENT_CUTDECK.md §B.3, Phase 2).

One ``<sequence>`` = the rough cut. Every KEEP span becomes one video clipitem +
linked audio clipitems, laid end-to-end on the timeline (cuts are *omitted* from
the sequence, not the plan). All clipitems reference a single ``<file>`` element
(Premiere convention: the full listing appears once, later refs point back by id).

Frame math goes through ``transcribe.timebase`` only — no float fps ever touches
a frame number, so a cut at the 60-minute mark lands on the intended frame.

GAP-2: a VFR source has no single frame grid to export against, so export
**refuses** rather than emit silently-wrong frame numbers.

The clip name carries the round-trip key ``cd{job}_p{plan}_s{span}`` so the
re-import (Phase 3) can match Premiere's edited clips back to plan spans.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from xml.etree import ElementTree as ET

from cutdeck.contracts import KEEP, CutPlan, Timebase
from cutdeck.plan import load_plan
from transcribe.timebase import ms_to_frame

# FCP7 stereo convention: two mono audio tracks linked to the video clip. Most
# Premiere projects are stereo; mono sources still import (the second track is
# simply silent). ponytail: fixed at 2, make it probe channel count if a real
# mono/5.1 source ever needs exact channel mapping.
AUDIO_CHANNELS = 2


def name_key(job_id: int, plan_id: int, span_idx: int) -> str:
    """The round-trip key embedded in clip name + comments (e.g. cd042_p007_s0012)."""
    return f"cd{job_id:03d}_p{plan_id:03d}_s{span_idx:04d}"


def _pathurl(abs_path: str) -> str:
    """``file://localhost/`` URL for an absolute path.

    Windows drive letters must be percent-encoded (``C:`` → ``C%3A``) but the
    path separators stay as ``/``. Tested against the real machine — see module
    acceptance in IMPLEMENT_CUTDECK.md.
    """
    p = str(abs_path).replace("\\", "/").lstrip("/")
    return "file://localhost/" + quote(p, safe="/")


def _rate(parent: ET.Element, tb: Timebase) -> None:
    """Append an FCP7 ``<rate>`` block: integer timebase + ntsc flag.

    fps_den==1001 → ntsc TRUE, timebase = round(fps_num/1000) (30000/1001 → 30).
    Otherwise ntsc FALSE, timebase = round(fps_num/fps_den) (25/1 → 25).
    """
    rate = ET.SubElement(parent, "rate")
    ET.SubElement(rate, "timebase").text = str(round(tb.fps_num / tb.fps_den))
    ET.SubElement(rate, "ntsc").text = "TRUE" if tb.fps_den == 1001 else "FALSE"


def _file_element(parent: ET.Element, file_id: str, media_path: str, tb: Timebase,
                  total_src_frames: int, full: bool) -> None:
    """A ``<file>`` ref. ``full=True`` emits the one complete listing; else a stub
    that points back to it by id (Premiere de-dupes on the id attribute)."""
    f = ET.SubElement(parent, "file", id=file_id)
    if not full:
        return
    ET.SubElement(f, "name").text = Path(media_path).name
    ET.SubElement(f, "pathurl").text = _pathurl(Path(media_path).resolve())
    _rate(f, tb)
    ET.SubElement(f, "duration").text = str(total_src_frames)
    media = ET.SubElement(f, "media")
    ET.SubElement(media, "video")
    audio = ET.SubElement(media, "audio")
    ET.SubElement(audio, "channelcount").text = str(AUDIO_CHANNELS)


def _link(clipitem: ET.Element, ref_id: str, mediatype: str, trackindex: int,
          clipindex: int) -> None:
    """A ``<link>`` joining video+audio clipitems so Premiere moves them as one."""
    link = ET.SubElement(clipitem, "link")
    ET.SubElement(link, "linkclipref").text = ref_id
    ET.SubElement(link, "mediatype").text = mediatype
    ET.SubElement(link, "trackindex").text = str(trackindex)
    ET.SubElement(link, "clipindex").text = str(clipindex)


def to_xml(plan: CutPlan, media_path: str, plan_id: int,
           sequence_name: Optional[str] = None) -> str:
    """Render a CutPlan's KEEP spans as an FCP7 XML string.

    Raises ValueError on a VFR timebase (GAP-2) or a plan with no keep spans.
    """
    tb = plan.timebase
    if tb.is_vfr:
        raise ValueError(
            "refusing to export VFR source: no single frame grid for frame-accurate "
            "cuts (GAP-2). Conform a CFR proxy first."
        )
    keeps = [s for s in plan.spans if s.action == KEEP]
    if not keeps:
        raise ValueError("plan has no keep spans — nothing to export")

    file_id = "file-1"
    total_src_frames = ms_to_frame(plan.duration_ms, tb)

    # Pre-compute each keep span's source + timeline frame positions.
    clips = []          # (span, src_in, src_out, tl_start, tl_end)
    tl = 0
    for s in keeps:
        src_in = ms_to_frame(s.src_in_ms, tb)
        src_out = ms_to_frame(s.src_out_ms, tb)
        dur = src_out - src_in
        if dur <= 0:     # span shorter than one frame after rounding — drop it
            continue
        clips.append((s, src_in, src_out, tl, tl + dur))
        tl += dur
    if not clips:
        raise ValueError("every keep span rounds to zero frames — nothing to export")
    seq_frames = tl

    xmeml = ET.Element("xmeml", version="5")
    seq = ET.SubElement(xmeml, "sequence", id=f"cd{plan.job_id:03d}_p{plan_id:03d}")
    ET.SubElement(seq, "name").text = sequence_name or name_key(plan.job_id, plan_id, 0)[:-6] + "rough"
    ET.SubElement(seq, "duration").text = str(seq_frames)
    _rate(seq, tb)
    media = ET.SubElement(seq, "media")
    video = ET.SubElement(media, "video")
    vtrack = ET.SubElement(video, "track")
    audio = ET.SubElement(media, "audio")
    atracks = [ET.SubElement(audio, "track") for _ in range(AUDIO_CHANNELS)]

    first = True
    for clip_i, (s, src_in, src_out, tl_start, tl_end) in enumerate(clips):
        key = name_key(plan.job_id, plan_id, s.idx)
        vid = f"v{clip_i}"
        aids = [f"a{ch}_{clip_i}" for ch in range(AUDIO_CHANNELS)]

        def add_clip(track, cid, mediatype, trackindex):
            nonlocal first
            ci = ET.SubElement(track, "clipitem", id=cid)
            ET.SubElement(ci, "name").text = key
            ET.SubElement(ci, "duration").text = str(src_out - src_in)
            _rate(ci, tb)
            ET.SubElement(ci, "start").text = str(tl_start)
            ET.SubElement(ci, "end").text = str(tl_end)
            ET.SubElement(ci, "in").text = str(src_in)
            ET.SubElement(ci, "out").text = str(src_out)
            _file_element(ci, file_id, media_path, tb, total_src_frames, full=first)
            first = False
            if mediatype == "audio":
                st = ET.SubElement(ci, "sourcetrack")
                ET.SubElement(st, "mediatype").text = "audio"
                ET.SubElement(st, "trackindex").text = str(trackindex)
            # Links: each clip references every clip in the group (video + audio).
            _link(ci, vid, "video", 1, clip_i + 1)
            for ch, aid in enumerate(aids):
                _link(ci, aid, "audio", ch + 1, clip_i + 1)
            cm = ET.SubElement(ci, "comments")
            ET.SubElement(cm, "mastercomment1").text = key
            ET.SubElement(cm, "mastercomment2").text = (
                f"{s.reason or 'keep'} ({s.source or 'rule'})"
            )

        add_clip(vtrack, vid, "video", 1)
        for ch in range(AUDIO_CHANNELS):
            add_clip(atracks[ch], aids[ch], "audio", ch + 1)

    body = ET.tostring(xmeml, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body + "\n"


# ── CLI ───────────────────────────────────────────────────────────────────────

_DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "transcribe" / "config.yaml"


def _conform_vfr_enabled(config_path: Optional[str]) -> bool:
    """Read ``conform_vfr`` from the pipeline config (GAP-2). Defaults False —
    missing/unreadable config means export keeps refusing VFR, not silently
    conforming."""
    path = Path(config_path) if config_path else _DEFAULT_CONFIG
    try:
        import yaml
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return False
    return bool(cfg.get("conform_vfr", False))


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Export a CutDeck plan to FCP7 XML for Premiere.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan-id", type=int, help="cut_plan row to export")
    g.add_argument("--job-id", type=int, help="export the latest plan for this job")
    ap.add_argument("--out", default=None, help="output .xml path (default cd<job>_p<plan>.xml)")
    ap.add_argument("--db", default=None, help="SQLite path (defaults to store default)")
    ap.add_argument("--config", default=None,
                     help="pipeline config.yaml (for conform_vfr); "
                          "defaults to transcribe/config.yaml")
    args = ap.parse_args(argv)

    from transcribe.db import store

    conn = store.connect(Path(args.db)) if args.db else store.connect()
    try:
        if args.plan_id is not None:
            plan_id = args.plan_id
        else:
            plans = store.get_cut_plans_for_job(conn, args.job_id)
            if not plans:
                raise SystemExit(f"no cut_plan rows for job {args.job_id}")
            plan_id = plans[0].id

        plan = load_plan(conn, plan_id)
        if plan is None:
            raise SystemExit(f"cut_plan {plan_id} not found")
        media = store.get_media(conn, store.get_job(conn, plan.job_id).media_id)
        if media is None:
            raise SystemExit(f"media for job {plan.job_id} not found")

        media_path = media.path
        if plan.timebase.is_vfr and _conform_vfr_enabled(args.config):
            from transcribe.timebase import conform_vfr
            print(f"source is VFR — conforming a CFR proxy (fps {plan.timebase.fps_num}/{plan.timebase.fps_den})...")
            media_path, plan.timebase = conform_vfr(media.path, plan.timebase)
            print(f"conformed proxy: {media_path}")

        xml = to_xml(plan, media_path, plan_id)
        out = Path(args.out) if args.out else Path(f"cd{plan.job_id:03d}_p{plan_id:03d}.xml")
        out.write_text(xml, encoding="utf-8")
        store.update_cut_plan_status(conn, plan_id, "exported")
        print(f"wrote {out} ({sum(1 for s in plan.spans if s.action == KEEP)} keep clips)")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
