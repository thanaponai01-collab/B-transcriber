"""xml_recut.py — recut an editor's own exported FCP7 XML sequence in place
(``recut_sequence`` mode, ``docs/HANDOFF_CUTDECK_XML_RECUT.md`` Phase 2).

**Method: surgical tree rewrite, not model-and-regenerate.** Parse the editor's
XML into an ElementTree and mutate only the numbers that must change; every
element the transform doesn't understand round-trips structurally unchanged
(ElementTree re-serialization reformats whitespace, but touches no tag,
attribute, or text the transform didn't explicitly edit). This is deliberately
the opposite strategy from ``xml_export.py``
(which builds a fresh tree from a ``CutPlan``) — here the input tree already
carries structure this codebase has never modeled (logging metadata, color
info, per-track UI state), and inventing a model for all of it would silently
drop whatever nobody thought to model.

**The core invariant:** a cut is a global time-domain operation, not a
per-clip edit. Everything at or after a cut point — every track's clipitems,
gaps, sequence markers, locked/muted/disabled tracks — shifts left by the
cut's frame count, with no exemptions. Sync is preserved *by construction*:
for every pair of clipitems on different tracks, their relative timeline
offset is unchanged unless one of them fell inside a cut region.

Frame math goes through ``transcribe.timebase`` exclusively — the XML's own
``<sequence><rate>`` is the one authority for what a "frame" means here (a
``CutPlan`` derived from an audio-only mixdown may carry a fabricated 25fps
Timebase; see ``sequence_mixdown.py``'s own warning — a disagreement between
that and the XML's real rate is a hard refusal in the CLI's duration guard,
never a silent reconcile).

**Refusal list is strict, on purpose.** Any ``<transitionitem>`` anywhere in
the sequence, any nested ``<sequence>`` clip, and a clipitem carrying a
``<filter>`` that a cut boundary lands inside all raise ``XmlRecutRefusal``
naming the exact clip (or transition) and its timecode, rather than guessing
at a safe rewrite. Permissive would generate a wrong-but-plausible sequence
nobody audits; strict generates a loud stop the first time real footage has
something this transform doesn't yet understand, and that structure gets
added to the recognised list with a test. **Known gap:** speed/time-remap
clips have no dedicated check yet — none has been seen in a real fixture
(see `docs/HANDOFF_CUTDECK_XML_RECUT.md`'s note on today's sequences); add
one, with a test, before trusting this transform on footage that uses it.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from xml.etree import ElementTree as ET

from cutdeck.contracts import CUT, KEEP, CutPlan, Timebase
from transcribe.timebase import ms_to_frame

# Tags that, if found on a clipitem straddling a cut boundary, make a razor
# unsafe to perform blindly — the refusal list (see module docstring).
_UNSAFE_CLIP_TAGS = ("filter",)

# Premiere's internal high-precision tick rate (ticks/sec), constant across
# every frame rate — confirmed against a real export's own pproTicksOut
# (278977305600000 ticks for a 32948-frame @30fps clip => exactly
# 254016000000 ticks/sec, 2026-08-29). <pproTicksIn>/<pproTicksOut> are what
# Premiere's *audio* engine reads for playback precision; <in>/<out> are the
# frame-based numbers video playback and the rest of this transform use.
# Trimming a clip and updating only <in>/<out> leaves pproTicks pointing at
# the ORIGINAL untrimmed source range — video then plays from the right
# frame while audio silently plays from wherever the stale ticks pointed
# (confirmed on a real Premiere import, 2026-08-29: cuts landed correctly,
# every audio track was silent). Every trim must update both.
_PPRO_TICKS_PER_SECOND = 254016000000


def _frame_to_ticks(frame: int, tb: Timebase) -> int:
    exact = Fraction(frame * _PPRO_TICKS_PER_SECOND * tb.fps_den, tb.fps_num)
    return exact.numerator // exact.denominator


class XmlRecutRefusal(ValueError):
    """Raised when the transform hits something it must not guess about."""


@dataclass
class RecutReport:
    """What happened during a recut, for the CLI to print."""
    cuts_applied: int
    clips_removed: int
    clips_trimmed: int
    clips_shifted: int
    markers_dropped: int


def _text(el, tag, default=None):
    child = el.find(tag)
    return child.text if child is not None and child.text is not None else default


def _timecode(frame: int, tb: Timebase) -> str:
    """Best-effort HH:MM:SS:FF for a refusal message (not written to output)."""
    fps = round(tb.fps_num / tb.fps_den)
    if fps <= 0:
        return str(frame)
    total_seconds, ff = divmod(frame, fps)
    hh, rem = divmod(total_seconds, 3600)
    mm, ss = divmod(rem, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def _clip_name(clipitem: ET.Element) -> str:
    return _text(clipitem, "name", clipitem.get("id", "?"))


def _sequence_timebase(sequence: ET.Element) -> Timebase:
    rate = sequence.find("rate")
    if rate is None:
        raise XmlRecutRefusal("sequence has no <rate> — cannot recut without a frame grid")
    timebase_el = rate.find("timebase")
    ntsc_el = rate.find("ntsc")
    if timebase_el is None or timebase_el.text is None:
        raise XmlRecutRefusal("sequence <rate> has no <timebase>")
    timebase_int = int(timebase_el.text)
    is_ntsc = (ntsc_el is not None and (ntsc_el.text or "").strip().upper() == "TRUE")
    fps_num, fps_den = (timebase_int * 1000, 1001) if is_ntsc else (timebase_int, 1)
    return Timebase(fps_num=fps_num, fps_den=fps_den)


def _cut_spans_frames(plan: CutPlan, tb: Timebase) -> list[tuple[int, int]]:
    """CUT spans as (start_frame, end_frame), ascending, non-overlapping."""
    out = []
    for s in plan.spans:
        if s.action != CUT:
            continue
        start = ms_to_frame(s.src_in_ms, tb)
        end = ms_to_frame(s.src_out_ms, tb)
        if end > start:
            out.append((start, end))
    out.sort()
    return out


def _shift_for_frame(frame: int, cuts: list[tuple[int, int]]) -> int:
    """Total frames removed strictly before ``frame`` by every cut span."""
    shift = 0
    for c_start, c_end in cuts:
        if c_end <= frame:
            shift += c_end - c_start
        elif c_start < frame:
            # frame falls inside this cut — caller should have trimmed/removed
            # the element already; shift it fully out of the cut region.
            shift += frame - c_start
    return shift


def _overlapping_cut(start: int, end: int, cuts: list[tuple[int, int]]) -> tuple[int, int] | None:
    """First cut span that overlaps [start, end), or None."""
    for c_start, c_end in cuts:
        if c_start < end and c_end > start:
            return (c_start, c_end)
    return None


def _shift_point(frame: int, cuts: list[tuple[int, int]]) -> int:
    """New frame position for a point (marker, gap edge) wholly outside all cuts."""
    return frame - _shift_for_frame(frame, cuts)


def _refuse_if_unsafe(clipitem: ET.Element, tb: Timebase, start: int, end: int) -> None:
    for tag in _UNSAFE_CLIP_TAGS:
        if clipitem.find(tag) is not None:
            raise XmlRecutRefusal(
                f"clip {_clip_name(clipitem)!r} at {_timecode(start, tb)}-{_timecode(end, tb)} "
                f"carries a <{tag}> and a cut boundary lands inside it — refusing rather than "
                f"guessing how the effect should split"
            )


def _keep_subranges(start: int, end: int,
                     cuts: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """[start, end) minus every overlapping cut, as the surviving sub-ranges,
    in order. A clip untouched by any cut returns ``[(start, end)]``."""
    kept: list[tuple[int, int]] = []
    cursor = start
    for c_start, c_end in cuts:
        if c_end <= cursor or c_start >= end:
            continue
        if c_start > cursor:
            kept.append((cursor, min(c_start, end)))
        cursor = max(cursor, c_end)
        if cursor >= end:
            break
    if cursor < end:
        kept.append((cursor, end))
    return kept


def _clone_clipitem(clipitem: ET.Element, new_id: str) -> ET.Element:
    import copy
    clone = copy.deepcopy(clipitem)
    clone.set("id", new_id)
    return clone


def _process_track(track: ET.Element, cuts: list[tuple[int, int]], tb: Timebase,
                    report: RecutReport) -> None:
    """Rewrite every clipitem on one ``<track>`` in place, per the case table
    in the module docstring. Locked/enabled flags are read but never used to
    skip a clip — every track shifts identically, no exemptions.

    A clip may need to become zero, one, or several output clipitems: zero if
    it falls wholly inside one cut, several if it spans a cut on both sides
    (an ordinary full-length clip with a mid-clip cut is the common case, not
    an edge case). Multi-piece splits get cloned ids and lose their <link> —
    see the module-level link-stripping pass below.
    """
    for clipitem in list(track.findall("clipitem")):
        if clipitem.tag != "clipitem":
            continue
        start = int(_text(clipitem, "start", "0"))
        end = int(_text(clipitem, "end", "0"))

        if _overlapping_cut(start, end, cuts) is None:
            # Wholly outside every cut: shift left by whatever was removed before it.
            new_start = _shift_point(start, cuts)
            new_end = _shift_point(end, cuts)
            if new_start != start:
                report.clips_shifted += 1
            clipitem.find("start").text = str(new_start)
            clipitem.find("end").text = str(new_end)
            continue

        _refuse_if_unsafe(clipitem, tb, start, end)
        keeps = _keep_subranges(start, end, cuts)
        pos = list(track).index(clipitem)
        track.remove(clipitem)
        if not keeps:
            report.clips_removed += 1
            continue

        in_ = int(_text(clipitem, "in", "0"))
        out_ = int(_text(clipitem, "out", "0"))
        # Piece 0 keeps the original element/id; later pieces are clones with
        # a derived id, so a single-piece trim (the common case) is id-stable.
        pieces = [clipitem] + [
            _clone_clipitem(clipitem, f"{clipitem.get('id')}__cd{i}")
            for i in range(1, len(keeps))
        ]
        for i, (piece, (k_start, k_end)) in enumerate(zip(pieces, keeps)):
            new_in = in_ + (k_start - start)
            new_out = out_ + (k_end - end)
            piece.find("in").text = str(new_in)
            piece.find("out").text = str(new_out)
            piece.find("start").text = str(_shift_point(k_start, cuts))
            piece.find("end").text = str(_shift_point(k_end, cuts))
            ticks_in_el = piece.find("pproTicksIn")
            if ticks_in_el is not None:
                ticks_in_el.text = str(_frame_to_ticks(new_in, tb))
            ticks_out_el = piece.find("pproTicksOut")
            if ticks_out_el is not None:
                ticks_out_el.text = str(_frame_to_ticks(new_out, tb))
            track.insert(pos + i, piece)
        report.clips_trimmed += len(keeps)


def _dedupe_file_listings(sequence: ET.Element) -> None:
    """Collapse every duplicate "full" ``<file>`` listing (one with children —
    ``<pathurl>``, ``<media>``, etc.) down to an empty stub, keeping only the
    first full listing seen per file id, in document order.

    FCP7 convention is exactly one full listing per file id; every other
    clipitem referencing that source carries a bare ``<file id="..."/>``
    stub that resolves back to it. ``_clone_clipitem``'s deepcopy duplicates
    whatever ``<file>`` child the original clipitem carried — when that
    original happens to be the one holding the full listing (the common case:
    it's whichever clipitem for that source appears first in the sequence,
    almost always cut and split like everything else), every split piece gets
    its own full copy. Premiere tolerated the resulting duplicate listings
    well enough to still resolve *video*, but silently failed to resolve
    *audio* channel routing against them — confirmed on a real Premiere
    26.x import, 2026-08-29 (see TODO_LEDGER.md). This pass is what makes
    the "exactly one full listing" invariant hold again after cloning.
    """
    seen_full_ids: set[str] = set()
    for file_el in sequence.iter("file"):
        file_id = file_el.get("id")
        is_full = len(list(file_el)) > 0
        if not is_full:
            continue
        if file_id in seen_full_ids:
            for child in list(file_el):
                file_el.remove(child)
        else:
            seen_full_ids.add(file_id)


def _process_markers(sequence: ET.Element, cuts: list[tuple[int, int]]) -> int:
    """Shift every ``<marker>`` under the sequence; drop one inside a cut,
    counted and returned so the caller can report it."""
    dropped = 0
    for parent in sequence.iter():
        for marker in list(parent.findall("marker")):
            in_el = marker.find("in")
            if in_el is None or in_el.text is None:
                continue
            frame = int(in_el.text)
            overlap = _overlapping_cut(frame, frame + 1, cuts)
            if overlap is not None:
                parent.remove(marker)
                dropped += 1
                continue
            in_el.text = str(_shift_point(frame, cuts))
            out_el = marker.find("out")
            if out_el is not None and out_el.text not in (None, "-1"):
                out_el.text = str(_shift_point(int(out_el.text), cuts))
    return dropped


def _refuse_unsupported_media(sequence: ET.Element) -> None:
    """Global refusal for structure this transform has no model for at all,
    independent of whether a cut boundary happens to land inside it — a
    transition or nested sequence changes what "shift everything after" even
    means, so their mere presence is refused."""
    for transition in sequence.iter("transitionitem"):
        start = _text(transition, "start", "?")
        raise XmlRecutRefusal(
            f"sequence contains a <transitionitem> at frame {start} — transitions "
            f"are not supported by this transform, refusing rather than guessing"
        )
    for clipitem in sequence.iter("clipitem"):
        if clipitem.find("sequence") is not None:
            raise XmlRecutRefusal(
                f"clip {_clip_name(clipitem)!r} is a nested sequence — not supported, refusing"
            )


def recut(source_xml: str, plan: CutPlan) -> tuple[str, RecutReport]:
    """Apply a CutPlan's CUT spans to an exported FCP7 sequence.

    Pure: string in, string out, no side effects, no Premiere dependency.
    Returns ``(recut_xml, RecutReport)``. Raises ``XmlRecutRefusal`` on any
    structure this transform must not guess about, and ``ValueError`` on a
    VFR timebase (GAP-2, matching ``xml_export.to_xml``).
    """
    if plan.timebase.is_vfr:
        raise ValueError(
            "refusing to recut a VFR source: no single frame grid for frame-accurate "
            "cuts (GAP-2). Conform a CFR proxy first."
        )

    root = ET.fromstring(source_xml)
    sequence = root.find("sequence")
    if sequence is None:
        raise XmlRecutRefusal("no <sequence> element found in source XML")

    tb = _sequence_timebase(sequence)

    _refuse_unsupported_media(sequence)

    cuts = _cut_spans_frames(plan, tb)
    if not cuts:
        raise ValueError("plan has no cut spans — nothing to recut")

    report = RecutReport(cuts_applied=len(cuts), clips_removed=0, clips_trimmed=0,
                          clips_shifted=0, markers_dropped=0)

    for track in sequence.iter("track"):
        _process_track(track, cuts, tb, report)

    # Links are dropped wholesale rather than rewritten (module docstring):
    # a split clip's clone ids invalidate any <linkclipref> that pointed at
    # the original single id, and Premiere's own link groups are otherwise
    # nastier to reconstruct correctly than to omit. Geometry (and therefore
    # sync) is guaranteed by the per-track shift above regardless of links;
    # linking only matters if the editor drags a clip afterwards.
    for clipitem in sequence.iter("clipitem"):
        for link in list(clipitem.findall("link")):
            clipitem.remove(link)

    _dedupe_file_listings(sequence)

    report.markers_dropped = _process_markers(sequence, cuts)

    # Sequence-level duration shrinks by the total cut frames.
    total_cut = sum(c_end - c_start for c_start, c_end in cuts)
    dur_el = sequence.find("duration")
    if dur_el is not None and dur_el.text is not None:
        dur_el.text = str(int(dur_el.text) - total_cut)

    name_el = sequence.find("name")
    if name_el is not None:
        name_el.text = f"{name_el.text} — CutDeck"

    body = ET.tostring(root, encoding="unicode")
    xml_out = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n' + body + "\n"
    return xml_out, report


# ── CLI (Phase 3) ─────────────────────────────────────────────────────────────

class DurationMismatch(ValueError):
    """The mixdown's duration doesn't match the XML sequence's declared
    duration — see the module docstring's duration-guard note. The nastiest
    silent failure this transform can produce is cutting against the wrong
    time axis, so this check is a hard refusal, never a warning."""


_DURATION_GUARD_TOLERANCE_MS = 34  # ~1 frame at 30fps; exact check is per-frame below


def _check_duration_guard(sequence_duration_frames: int, mixdown_duration_ms: int,
                           tb: Timebase) -> None:
    seq_ms = frame_to_ms_int(sequence_duration_frames, tb)
    if abs(seq_ms - mixdown_duration_ms) > _DURATION_GUARD_TOLERANCE_MS:
        raise DurationMismatch(
            f"mixdown duration ({mixdown_duration_ms} ms) does not match the XML "
            f"sequence's declared duration ({seq_ms} ms, {sequence_duration_frames} "
            f"frames) within one frame. If the mixdown was exported over an in/out "
            f"range or the work area instead of the whole sequence, every cut would "
            f"land at the wrong time, uniformly — refusing rather than risk that."
        )


def frame_to_ms_int(frame: int, tb: Timebase) -> int:
    from transcribe.timebase import frame_to_ms
    return int(round(frame_to_ms(frame, tb)))


def main(argv: list[str] | None = None) -> int:
    import argparse
    import tempfile
    from pathlib import Path

    import yaml

    from cutdeck.contracts import CutConfig
    from cutdeck.sequence_mixdown import plan_from_mixdown

    ap = argparse.ArgumentParser(
        description="Recut an exported FCP7 XML sequence against a silence-removal "
                     "plan built from its own audio mixdown (recut_sequence mode)."
    )
    ap.add_argument("sequence_xml", help="the editor's own FCP7 XML export")
    ap.add_argument("mixdown_wav", nargs="?", default=None,
                     help="full-sequence audio mixdown (must span the whole sequence, "
                          "not an in/out range). Omit to auto-extract one straight from "
                          "the XML's own clipitems + source media instead (see "
                          "cutdeck/xml_audio_extract.py) — no Premiere export needed.")
    ap.add_argument("--audio-track", type=int, default=None,
                     help="0-based audio track index to use as the reference dialogue "
                          "track when auto-extracting (default: first track with clips). "
                          "Ignored when mixdown_wav is given explicitly.")
    ap.add_argument("--out", default=None,
                     help="output .xml path (default: <sequence_xml>_cut.xml beside the input)")
    ap.add_argument("--job-id", type=int, default=0)
    ap.add_argument("--config", default=str(Path(__file__).resolve().parent.parent
                                             / "transcribe" / "config.yaml"))
    ap.add_argument("--db", default=None, help="SQLite path (defaults to store default)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, write nothing")
    args = ap.parse_args(argv)

    src = Path(args.sequence_xml)
    source_xml = src.read_text(encoding="utf-8")
    root = ET.fromstring(source_xml)
    sequence = root.find("sequence")
    if sequence is None:
        raise SystemExit("no <sequence> element found in source XML")
    tb = _sequence_timebase(sequence)
    seq_frames = int(_text(sequence, "duration", "0"))

    cfg = CutConfig.from_yaml(yaml.safe_load(Path(args.config).read_text(encoding="utf-8")))

    extracted_tmp = None
    mixdown_wav = args.mixdown_wav
    if mixdown_wav is None:
        from cutdeck.xml_audio_extract import extract_mixdown
        extracted_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        extracted_tmp.close()
        print("no mixdown given — extracting one from the XML's own source media...")
        mixdown_wav = extract_mixdown(source_xml, extracted_tmp.name, args.audio_track)

    try:
        from transcribe.pipeline.ingest import ingest
        mixdown_result = ingest(mixdown_wav, materialize_chunks=False)
        _check_duration_guard(seq_frames, mixdown_result.duration_ms, tb)

        plan = plan_from_mixdown(mixdown_wav, args.job_id, cfg, timebase=tb)
    finally:
        if extracted_tmp is not None:
            Path(extracted_tmp.name).unlink(missing_ok=True)

    n_cut = sum(1 for s in plan.spans if s.action == CUT)
    cut_ms = sum(s.duration_ms for s in plan.spans if s.action == CUT)

    if args.dry_run:
        print(f"{n_cut} cut spans, {cut_ms} ms to remove of {plan.duration_ms} ms "
              f"({seq_frames} frames declared in sequence XML)")
        return 0

    out_xml, report = recut(source_xml, plan)
    out = Path(args.out) if args.out else src.with_name(src.stem + "_cut.xml")
    out.write_text(out_xml, encoding="utf-8")

    from transcribe.db import store
    conn = store.connect(Path(args.db)) if args.db else store.connect()
    try:
        from cutdeck import plan as planmod
        planmod.save_plan(conn, plan)
    finally:
        conn.close()

    print(f"wrote {out}")
    print(f"{report.cuts_applied} cuts applied: {report.clips_trimmed} clip pieces trimmed, "
          f"{report.clips_removed} clips removed, {report.clips_shifted} clips shifted, "
          f"{report.markers_dropped} markers dropped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
