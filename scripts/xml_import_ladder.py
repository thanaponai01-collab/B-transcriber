"""xml_import_ladder.py — make the one Premiere session diagnostic.

The real acceptance for ``cutdeck/xml_export.py`` — does an FCP7 XML this repo
emits actually import clean into Premiere on real footage — has been open since
2026-06-19 and cannot be executed from a shell. It needs a human clicking in
Premiere. This script exists so that click is worth spending.

**The problem it solves.** Importing one full export answers one bit: it worked
or it didn't. But the export rests on at least six independent unverified
assumptions, and a single red result cannot say which one broke — leaving the
next session to guess, exactly the failure mode that produced eighteen confident
wrong rounds on the clone route (#18/#24). So instead of one file, this emits a
**cumulative ladder**: each rung adds exactly one assumption to the rung below
it, so the *first* rung that fails names its own cause.

**Why the rungs are generated, not hand-written.** Every rung comes out of the
real ``to_xml`` and is then *reduced* by deleting specific elements. A
hand-authored minimal XML that imports proves something about that file, not
about this exporter. Here the top rung is unmodified ``to_xml`` output, and each
lower rung is that same output minus a named piece — so a green ladder is
evidence about the shipping code path.

Usage (prefer --job-id: it points at real footage on a real Thai path, which is
itself one of the untested assumptions):

    python scripts/xml_import_ladder.py --job-id 29
    python scripts/xml_import_ladder.py --media "D:/footage/clip.mp4" --fps 29.97

Writes the rungs plus a RUNBOOK.md to <media folder>/CutDeck/import_ladder/.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Callable, Optional
from xml.etree import ElementTree as ET

from cutdeck.contracts import BLADE_VAD, BLADE_WORD, CUT, KEEP, CutPlan, CutSpan
from cutdeck.xml_export import to_xml
from transcribe.console import safe_print
from transcribe.timebase import Timebase, ms_to_frame

# Fallback when the media's real duration can't be probed. Long enough that the
# far-offset rung still exercises large frame numbers.
_FALLBACK_TOTAL_MS = 10 * 60 * 1000

# How many clips the <file>-stub rung places. Two clips cannot show a de-dupe
# failure that only becomes obvious as a bin full of duplicate master clips.
_STUB_RUNG_CLIPS = 40

# Below this, rung 4's "far" offset is not far enough for frame drift to be a
# meaningful test. The rung is still emitted — it just says so in the runbook.
_MIN_MEANINGFUL_FAR_MS = 60_000


# ── plan construction ─────────────────────────────────────────────────────────

def _plan(keeps: list[tuple[int, int]], total_ms: int, tb: Timebase,
          blade: str = BLADE_VAD) -> CutPlan:
    """A CutPlan whose spans tile [0, total_ms] exactly.

    CutSpan's contract is that spans tile the media with no gaps and no
    overlaps, so the gaps between the requested KEEPs are filled with real CUT
    spans rather than left absent — this also makes ``plan.duration_ms`` (and
    therefore the ``<file>`` duration ``to_xml`` emits) correct.
    """
    spans: list[CutSpan] = []
    cursor = 0
    for start, end in keeps:
        if start > cursor:
            spans.append(CutSpan(idx=len(spans), src_in_ms=cursor, src_out_ms=start,
                                 action=CUT, reason="silence", blade=blade))
        spans.append(CutSpan(idx=len(spans), src_in_ms=start, src_out_ms=end,
                             action=KEEP, reason="keep"))
        cursor = end
    if cursor < total_ms:
        spans.append(CutSpan(idx=len(spans), src_in_ms=cursor, src_out_ms=total_ms,
                             action=CUT, reason="silence", blade=blade))
    return CutPlan(job_id=999, media_sha256="0" * 64, timebase=tb, spans=spans)


# ── reducers ──────────────────────────────────────────────────────────────────

def _strip_audio_and_links(root: ET.Element) -> None:
    """Video-only: drop the whole <audio> block and every <link>.

    A lone video clipitem needs no links, so removing both together keeps the
    rung internally consistent rather than leaving links pointing at ids that
    no longer exist.
    """
    media = root.find("sequence/media")
    if media is not None:
        for audio in media.findall("audio"):
            media.remove(audio)
    for parent in root.iter():
        for link in parent.findall("link"):
            parent.remove(link)


def _identity(root: ET.Element) -> None:
    """Top rungs ship exactly what to_xml emitted."""


# ── the ladder ────────────────────────────────────────────────────────────────

class Rung:
    def __init__(self, seq: int, slug: str, adds: str, on_failure: str,
                 build: Callable[[int, Timebase], CutPlan],
                 reduce: Callable[[ET.Element], None] = _identity,
                 crossfade_ms: int = 0) -> None:
        self.seq, self.slug, self.adds, self.on_failure = seq, slug, adds, on_failure
        self.build, self.reduce, self.crossfade_ms = build, reduce, crossfade_ms

    @property
    def filename(self) -> str:
        return f"{self.seq:02d}_{self.slug}.xml"


def _far_keeps(total_ms: int) -> list[tuple[int, int]]:
    """A short head clip plus a clip anchored at the far end of the media.

    The point is the *second* clip's source in-point: a large millisecond offset
    converted once through ms_to_frame. Rounding drift that is invisible near
    zero is visible here.

    Clip length scales to the media rather than sitting at a fixed 2 s. A fixed
    length collapses both keeps onto the same region on short media, and to_xml
    then drops the zero-length one — leaving a single-clip rung that still
    claims to be testing a far offset. A diagnostic that quietly tests nothing
    is worse than one that is absent.
    """
    clip = max(200, min(2_000, total_ms // 5))
    tail_start = max(clip, total_ms - clip)
    return [(0, clip), (tail_start, total_ms)]


def _two_clip_keeps(total_ms: int) -> list[tuple[int, int]]:
    """Two keeps separated by one cut, both inside the media.

    Scaled for the same reason as _far_keeps: fixed 5 s / 12 s offsets overrun a
    short source, and the resulting rung fails because it points past the end of
    the file — a failure about the ladder, not about the exporter.
    """
    clip = max(200, min(5_000, total_ms // 3))
    gap = max(100, min(2_000, total_ms // 6))
    return [(0, clip), (clip + gap, min(total_ms, clip + gap + clip))]


def _single_keep(total_ms: int) -> list[tuple[int, int]]:
    """One keep, scaled to fit the media (rungs 1-2)."""
    return [(0, max(200, min(8_000, total_ms)))]


def _many_keeps(total_ms: int) -> list[tuple[int, int]]:
    """Alternating keep/cut across the media, to fill a bin if de-dupe fails.

    The clip *count* scales down on short media as well as the clip length:
    _STUB_RUNG_CLIPS slots at the 200 ms floor need 16 s of source, so asking
    for all of them on a shorter file would run the last clips off the end.
    """
    slot = max(200, total_ms // (_STUB_RUNG_CLIPS * 2))
    count = min(_STUB_RUNG_CLIPS, max(2, total_ms // (2 * slot)))
    return [(i * 2 * slot, i * 2 * slot + slot) for i in range(count)]


def _two_clip_frames(tb: Timebase, total_ms: int) -> int:
    """Expected timeline length, in frames, of the two-clip rungs."""
    (a_in, a_out), (b_in, b_out) = _two_clip_keeps(total_ms)
    return ((ms_to_frame(a_out, tb) - ms_to_frame(a_in, tb))
            + (ms_to_frame(b_out, tb) - ms_to_frame(b_in, tb)))


LADDER: list[Rung] = [
    Rung(
        1, "pathurl_and_rate",
        "the file://localhost/ pathurl form and the integer-timebase + ntsc rate",
        "Media comes in OFFLINE, or the sequence lands at the wrong frame rate.\n"
        "  → _pathurl()'s Windows drive encoding (C: → C%3A) is wrong for this\n"
        "    Premiere build, or _rate()'s ntsc mapping is. Nothing below this\n"
        "    rung can be trusted; fix this first.",
        build=lambda total, tb: _plan(_single_keep(total), total, tb),
        reduce=_strip_audio_and_links,
    ),
    Rung(
        2, "stereo_audio_links",
        "the two linked mono audio tracks and their <sourcetrack> mapping",
        "Audio is missing, silent, doubled, or moves independently of the video.\n"
        "  → the AUDIO_CHANNELS=2 stereo convention or _link()'s\n"
        "    trackindex/clipindex numbering is wrong. Rung 1 passing means the\n"
        "    media and rate are fine and this is purely the link layout.",
        build=lambda total, tb: _plan(_single_keep(total), total, tb),
    ),
    Rung(
        3, "timeline_contiguity",
        "a second clip butted against the first, with the cut omitted",
        "A gap, an overlap, or a black frame appears at the join.\n"
        "  → to_xml's running `tl` accumulator disagrees with how Premiere lays\n"
        "    out start/end. The cut region should be gone entirely, not present\n"
        "    as blank timeline.",
        build=lambda total, tb: _plan(_two_clip_keeps(total), total, tb),
    ),
    Rung(
        4, "far_offset_frame_accuracy",
        "a source in-point at the far end of the media",
        "The second clip starts on the wrong frame — off by one or drifting.\n"
        "  → ms_to_frame's rounding, or the ntsc timebase, disagrees with\n"
        "    Premiere's own conversion at large offsets. This is the specific\n"
        "    risk the ledger's '60-minute mark' acceptance names.",
        build=lambda total, tb: _plan(_far_keeps(total), total, tb),
    ),
    Rung(
        5, "file_stub_dedupe",
        "many clips sharing one <file> listing via id stubs",
        "The project bin fills with one duplicate master clip per placement\n"
        "  instead of one, or later clips come in offline.\n"
        "  → _file_element's full=False stub convention (emit the complete\n"
        "    listing once, then reference by id) is not how this Premiere build\n"
        "    de-dupes. Cosmetic at 2 clips; unusable at the 443 placements job\n"
        "    28 really produces.",
        build=lambda total, tb: _plan(_many_keeps(total), total, tb),
    ),
    Rung(
        6, "word_blade_crossfade",
        "the audio-only crossfade transitionitem on a word-blade join",
        "The file is rejected, or the transition lands off-centre / on video.\n"
        "  → EXPECTED TO BE THE WEAKEST RUNG. _crossfade_transition is a known\n"
        "    approximation: it writes no source overlap or trim, which a real\n"
        "    crossfade needs. A failure here invalidates only the crossfade, not\n"
        "    rungs 1-5 — word-blade cuts are gated off by default\n"
        "    (cut.repeats_enabled / fillers_enabled are both false).",
        build=lambda total, tb: _plan(_two_clip_keeps(total), total, tb,
                                      blade=BLADE_WORD),
        crossfade_ms=20,
    ),
]


# ── media resolution ──────────────────────────────────────────────────────────

def _media_from_job(job_id: int, db: Optional[str]) -> tuple[str, Timebase]:
    from transcribe.db import store

    conn = store.connect(Path(db)) if db else store.connect()
    try:
        job = store.get_job(conn, job_id)
        if job is None:
            raise SystemExit(f"job {job_id} not found")
        media = store.get_media(conn, job.media_id)
        if media is None:
            raise SystemExit(f"media for job {job_id} not found")
        from transcribe.timebase import probe
        return media.path, probe(media.path)
    finally:
        conn.close()


# ── runbook ───────────────────────────────────────────────────────────────────

def _runbook(media_path: str, tb: Timebase, total_ms: int) -> str:
    # Read every expected number back out of the same helpers the rungs are
    # built from — a runbook quoting a constant the plan no longer uses would
    # send the reader hunting a discrepancy the exporter never produced.
    (head_in, head_out), (far_start, _far_end) = _far_keeps(total_ms)
    far_frame = ms_to_frame(far_start, tb)
    head_frames = ms_to_frame(head_out, tb) - ms_to_frame(head_in, tb)
    fps = tb.fps_num / tb.fps_den

    lines = [
        "# Premiere XML import ladder — runbook",
        "",
        f"Source media : `{media_path}`",
        f"Timebase     : {tb.fps_num}/{tb.fps_den} (~{fps:.3f} fps, "
        f"ntsc={'TRUE' if tb.ntsc else 'FALSE'})",
        f"Media length : {total_ms} ms",
        "",
        "## How to run this",
        "",
        "Import the rungs **in numeric order** and stop at the first one that",
        "misbehaves. Each rung adds exactly one assumption to the rung before it,",
        "so the first failure names its own cause — that is the entire point, and",
        "it is lost if you skip ahead or import them all at once.",
        "",
        "In Premiere: `File > Import`, pick the .xml, let it build the sequence.",
        "",
        "**Set the timecode display to Frames** (right-click any timecode field →",
        "Frames) before checking rung 4. Expected values below are frame counts;",
        "drop-frame timecode strings are deliberately not quoted here, because this",
        "repo has never verified how this Premiere build renders them.",
        "",
        "Every rung below was produced by the real `cutdeck.xml_export.to_xml` and",
        "then reduced by deleting named elements. Rungs 2-6 are unmodified exporter",
        "output; only rung 1 is reduced (audio and links removed).",
        "",
        "## What to check, rung by rung",
        "",
    ]

    for r in LADDER:
        lines += [
            f"### {r.filename}",
            "",
            f"**Adds:** {r.adds}",
            "",
            "**Expect:**",
        ]
        if r.seq == 1:
            lines += [
                "- The clip appears online (not red/offline media).",
                f"- The sequence reports ~{fps:.3f} fps.",
                "- Video only — no audio track. That is correct for this rung.",
                "",
            ]
        elif r.seq == 2:
            lines += [
                "- Audio present on two tracks, and audio+video select and move",
                "  together as one unit.",
                "",
            ]
        elif r.seq == 3:
            lines += [
                "- Exactly two clips, butted with no gap and no black frame.",
                f"- Total sequence length = {_two_clip_frames(tb, total_ms)} frames.",
                f"- The {_two_clip_keeps(total_ms)[0][1]}ms-{_two_clip_keeps(total_ms)[1][0]}ms region of the "
                "source is absent, not blank timeline.",
                "",
            ]
        elif r.seq == 4:
            lines += [
                f"- Clip 1 is {head_frames} frames long, starting at source frame 0.",
                f"- Clip 2's **source in-point** is frame **{far_frame}** "
                f"(= {far_start} ms).",
                "- Check that number in the Source monitor, not the timeline.",
                "  An off-by-one here is the whole finding.",
                "",
            ]
            if total_ms < _MIN_MEANINGFUL_FAR_MS:
                lines += [
                    f"> **Weak rung.** This media is only {total_ms} ms long, so the",
                    f"> 'far' offset is just {far_start} ms — nowhere near the",
                    "> 60-minute mark the ledger's acceptance actually names. Passing",
                    "> here is NOT evidence about frame accuracy at scale. Re-run the",
                    "> ladder against a full-length clip to get that answer.",
                    "",
                ]
        elif r.seq == 5:
            lines += [
                f"- {len(_many_keeps(total_ms))} clips on the timeline.",
                "- **Exactly one** master clip in the project bin, not "
                f"{len(_many_keeps(total_ms))}.",
                "- No clip offline.",
                "",
            ]
        else:
            lines += [
                "- The file imports at all.",
                "- A short audio crossfade sits centred on the join between the",
                "  two clips, and there is no video transition.",
                "",
            ]
        lines += ["**If it fails:**", "", f"  {r.on_failure}", ""]

    lines += [
        "## Reporting back",
        "",
        "Record, for each rung: pass / fail, and for a failure exactly what",
        "Premiere did (screenshot or the literal error). Then the next session can",
        "act on evidence instead of re-deriving the question.",
        "",
        "Note what this ladder does **not** cover: it says nothing about the",
        "`assemble` route (`cutdeck/assemble_export.py`), whose primitives have",
        "still never executed once — that needs its own live probe.",
        "",
    ]
    return "\n".join(lines)


# ── main ──────────────────────────────────────────────────────────────────────

def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Emit a staged Premiere XML import ladder for one media file.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--job-id", type=int, help="use this job's real media (preferred)")
    g.add_argument("--media", help="path to a media file")
    ap.add_argument("--fps", type=float, default=None,
                    help="decimal fps, with --media, when ffprobe can't be trusted")
    ap.add_argument("--db", default=None, help="SQLite path (defaults to store default)")
    ap.add_argument("--out-dir", default=None,
                    help="output folder (default: <media folder>/CutDeck/import_ladder)")
    args = ap.parse_args(argv)

    if args.job_id is not None:
        media_path, tb = _media_from_job(args.job_id, args.db)
    else:
        media_path = args.media
        if args.fps is not None:
            tb = Timebase.from_decimal_fps(args.fps)
        else:
            from transcribe.timebase import probe
            tb = probe(media_path)

    if tb.is_vfr:
        raise SystemExit(
            "source is VFR — to_xml refuses these by design (GAP-2), so a ladder "
            "built from it would test nothing. Conform a CFR proxy first.")

    total_ms = tb.duration_ms or _FALLBACK_TOTAL_MS
    if tb.duration_ms is None:
        safe_print(f"warning: could not probe media duration; assuming {total_ms} ms. "
                   "The far-offset rung is weaker than it looks.")
    elif total_ms < _MIN_MEANINGFUL_FAR_MS:
        safe_print(f"warning: media is only {total_ms} ms — rung 4's far offset is "
                   "too small to say anything about frame accuracy at scale. "
                   "Marked as a weak rung in the runbook.")

    out_dir = Path(args.out_dir) if args.out_dir else \
        Path(media_path).parent / "CutDeck" / "import_ladder"
    out_dir.mkdir(parents=True, exist_ok=True)

    for rung in LADDER:
        plan = rung.build(total_ms, tb)
        xml = to_xml(
            plan, media_path, plan_id=rung.seq,
            sequence_name=f"ladder{rung.seq:02d}_{rung.slug}",
            word_blade_crossfade_ms=rung.crossfade_ms or 20,
        )
        root = ET.fromstring(xml)
        rung.reduce(root)
        body = ET.tostring(root, encoding="unicode")
        (out_dir / rung.filename).write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body + "\n",
            encoding="utf-8")
        safe_print(f"  {rung.filename} — {rung.adds}")

    (out_dir / "RUNBOOK.md").write_text(
        _runbook(media_path, tb, total_ms), encoding="utf-8")

    safe_print(f"\nwrote {len(LADDER)} rungs + RUNBOOK.md to {out_dir}")
    safe_print("Import them in order; stop at the first that misbehaves.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
