"""preview.py — ffmpeg concat-demuxer stream-copy preview render (HANDOFF_CUTDECK_WORDLEVEL.md Phase 3).

Every threshold in this system (silence, filler, repeat, blade) was being tuned
blind until this module existed — the real Premiere XML round-trip
(``xml_export.py``) is still an open acceptance item, so this is the only way
to *watch* a rough cut before Phase 4/5 change how it's built.

**This is a sanity watch, not a frame-accuracy check.** Stream-copy ``-ss``/``-to``
snaps to the nearest keyframe on each side of a cut, so a join can be off by up
to one GOP. Frame accuracy is ``xml_export.py``'s job, verified in Premiere, not
here. The output filename and CLI print both say ``approx`` for a stream-copy
render so it's never mistaken for the real thing. ``--reencode`` re-encodes each
kept span (slow) for a frame-accurate render when a boundary is genuinely in
question.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from cutdeck.contracts import KEEP, CutPlan
from cutdeck.plan import load_plan


class FfmpegNotFoundError(RuntimeError):
    """ffmpeg binary not on PATH — raised so the CLI can print a clear message
    instead of letting subprocess's FileNotFoundError surface as a traceback."""


def keep_ranges_ms(plan: CutPlan) -> list[tuple[int, int]]:
    """(start_ms, end_ms) for every KEEP span, in timeline order."""
    return [(s.src_in_ms, s.src_out_ms) for s in plan.spans if s.action == KEEP]


def _check_ffmpeg(ffmpeg_bin: str) -> None:
    if shutil.which(ffmpeg_bin) is None:
        raise FfmpegNotFoundError(
            f"'{ffmpeg_bin}' not found on PATH — install ffmpeg (or pass --ffmpeg-bin) "
            "to render a preview."
        )


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({cmd}):\n{proc.stderr}")


def _extract_segment(ffmpeg_bin: str, media_path: str, start_ms: int, end_ms: int,
                      out_path: Path, reencode: bool) -> None:
    cmd = [
        ffmpeg_bin, "-y",
        "-ss", f"{start_ms / 1000:.3f}",
        "-to", f"{end_ms / 1000:.3f}",
        "-i", str(media_path),
    ]
    cmd += ["-c:v", "libx264", "-c:a", "aac"] if reencode else ["-c", "copy"]
    cmd.append(str(out_path))
    _run(cmd)


def _concat(ffmpeg_bin: str, segment_paths: list[Path], out_path: Path) -> None:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        for p in segment_paths:
            f.write(f"file '{p.resolve().as_posix()}'\n")
        list_path = Path(f.name)
    try:
        cmd = [ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
               "-i", str(list_path), "-c", "copy", str(out_path)]
        _run(cmd)
    finally:
        list_path.unlink(missing_ok=True)


def render_preview(plan: CutPlan, media_path: str, out_path: Path,
                    reencode: bool = False, ffmpeg_bin: str = "ffmpeg") -> Path:
    """Render the plan's KEEP spans, in timeline order, to ``out_path``.

    Raises ``ValueError`` if the plan has no keep spans, ``FfmpegNotFoundError``
    if ffmpeg isn't on PATH (checked up front, no traceback), and
    ``RuntimeError`` wrapping ffmpeg's own stderr on a render failure.
    """
    ranges = keep_ranges_ms(plan)
    if not ranges:
        raise ValueError("plan has no keep spans — nothing to preview")
    _check_ffmpeg(ffmpeg_bin)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = out_path.suffix or ".mp4"

    with tempfile.TemporaryDirectory(prefix="cutdeck_preview_") as tmp:
        tmp_dir = Path(tmp)
        segment_paths = []
        for i, (start_ms, end_ms) in enumerate(ranges):
            seg_path = tmp_dir / f"seg{i:04d}{suffix}"
            _extract_segment(ffmpeg_bin, media_path, start_ms, end_ms, seg_path, reencode)
            segment_paths.append(seg_path)

        if len(segment_paths) == 1:
            shutil.copy(segment_paths[0], out_path)
        else:
            _concat(ffmpeg_bin, segment_paths, out_path)

    return out_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Render an approximate preview of a CutDeck plan's keep spans."
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--plan-id", type=int, help="cut_plan row to preview")
    g.add_argument("--job-id", type=int, help="preview the latest plan for this job")
    ap.add_argument("--out", default="preview.mp4", help="output video path")
    ap.add_argument("--db", default=None, help="SQLite path (defaults to store default)")
    ap.add_argument("--reencode", action="store_true",
                     help="frame-accurate re-encode instead of the fast stream-copy "
                          "approximation (slow)")
    ap.add_argument("--ffmpeg-bin", default="ffmpeg", help="ffmpeg executable to use")
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
        job = store.get_job(conn, plan.job_id)
        if job is None:
            raise SystemExit(f"job {plan.job_id} not found")
        media = store.get_media(conn, job.media_id)
        if media is None:
            raise SystemExit(f"media for job {plan.job_id} not found")

        out = Path(args.out)
        if not args.reencode:
            out = out.with_name(f"{out.stem}_approx{out.suffix or '.mp4'}")

        try:
            result = render_preview(plan, media.path, out,
                                     reencode=args.reencode, ffmpeg_bin=args.ffmpeg_bin)
        except FfmpegNotFoundError as e:
            raise SystemExit(str(e))
        except (ValueError, RuntimeError) as e:
            raise SystemExit(f"preview render failed: {e}")

        n_keep = len(keep_ranges_ms(plan))
        label = "frame-accurate re-encode" if args.reencode else "APPROXIMATE (stream-copy, keyframe-imprecise)"
        print(f"wrote {result} ({n_keep} keep clips, {label}) — "
              "sanity watch only, not a frame-accuracy check; use xml_export.py + "
              "Premiere for that.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
