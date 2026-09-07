"""scripts/xml_import_ladder.py — the ladder must not lie about what it tests.

This tool exists to make one human Premiere session diagnostic: each rung adds
exactly one assumption to the rung below, so the first rung that fails names its
own cause. Two properties carry that promise, and both are easy to break
silently:

1. **Every rung stays inside the media.** Fixed-offset spans (the first draft
   used a literal 5 s / 12 s / 2 s layout) overrun a short source. The rung then
   fails in Premiere because it points past the end of the file — a failure
   about the ladder, not about the exporter, which is precisely the ambiguity
   the ladder exists to remove.

2. **Every rung is structurally what it claims.** A rung that quietly degenerates
   — rung 4 collapsing to a single clip on short media, because to_xml drops a
   span that rounds to zero frames — still gets imported, still passes, and
   still teaches nothing. That is worse than a missing rung.

Both were real defects in the first draft, caught by generating the ladder
against a real 2-second clip rather than by reading it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from xml_import_ladder import (  # noqa: E402
    LADDER, _many_keeps, _plan, _strip_audio_and_links,
)

from cutdeck.contracts import KEEP  # noqa: E402
from cutdeck.xml_export import to_xml  # noqa: E402
from transcribe.timebase import Timebase  # noqa: E402

# 2 s is the degenerate case that caught both defects; 38.6 min is job 28, the
# longest real clip this repo has measured; 60 min is the ledger's stated target.
LENGTHS = [2_000, 20_000, 60_000, 2_316_000, 3_600_000]


def _tb(total_ms: int) -> Timebase:
    return Timebase(30000, 1001, duration_ms=total_ms)


@pytest.mark.parametrize("total_ms", LENGTHS)
@pytest.mark.parametrize("rung", LADDER, ids=lambda r: r.slug)
def test_every_rung_tiles_the_media_without_overrunning_it(rung, total_ms):
    plan = rung.build(total_ms, _tb(total_ms))

    assert plan.spans, "rung produced no spans"
    assert plan.spans[0].src_in_ms == 0
    assert plan.duration_ms <= total_ms, (
        f"rung {rung.seq} runs {plan.duration_ms}ms past a {total_ms}ms source")
    for a, b in zip(plan.spans, plan.spans[1:]):
        assert a.src_out_ms == b.src_in_ms, "spans must tile with no gap/overlap"


@pytest.mark.parametrize("total_ms", LENGTHS)
@pytest.mark.parametrize("rung", LADDER, ids=lambda r: r.slug)
def test_no_rung_has_a_span_that_rounds_away(rung, total_ms):
    """to_xml silently drops a keep span shorter than one frame. A rung that
    loses a clip that way still imports and still proves nothing."""
    tb = _tb(total_ms)
    plan = rung.build(total_ms, tb)
    xml = to_xml(plan, "x.mp4", plan_id=rung.seq, frame_size=(1920, 1080))
    emitted = len(ET.fromstring(xml).find("sequence/media/video/track")
                  .findall("clipitem"))
    assert emitted == len(plan.keep_spans), (
        f"rung {rung.seq} planned {len(plan.keep_spans)} keeps but emitted "
        f"{emitted} clips at {total_ms}ms")


@pytest.mark.parametrize("total_ms", LENGTHS)
def test_the_ladder_is_cumulative_in_clip_count(total_ms):
    """Rung 3 onward must place more than one clip, or the contiguity, far-offset
    and crossfade rungs are all testing a single-clip timeline."""
    tb = _tb(total_ms)
    for rung in LADDER:
        keeps = len(rung.build(total_ms, tb).keep_spans)
        expected_min = 1 if rung.seq <= 2 else 2
        assert keeps >= expected_min, (
            f"rung {rung.seq} has {keeps} keep(s) at {total_ms}ms")


def test_rung_one_is_video_only_but_keeps_the_file_media_description():
    """The reducer must remove the sequence's audio *tracks* without stripping
    the <file>'s own <audio> channel-count description — that belongs to the
    media, not the timeline, and Premiere needs it to link audio in rung 2."""
    total = 60_000
    tb = _tb(total)
    rung = LADDER[0]
    root = ET.fromstring(to_xml(rung.build(total, tb), "x.mp4", plan_id=1,
                                frame_size=(1920, 1080)))
    _strip_audio_and_links(root)

    assert root.find("sequence/media/audio") is None, "sequence audio tracks remain"
    assert not root.findall(".//link"), "dangling links remain"
    assert root.find(".//file/media/audio/channelcount") is not None, \
        "the file's own audio description was stripped too"


def test_top_rung_is_unmodified_exporter_output():
    """The ladder's evidentiary claim: the last rung is exactly what ships."""
    total = 60_000
    tb = _tb(total)
    rung = LADDER[-1]
    xml = to_xml(rung.build(total, tb), "x.mp4", plan_id=rung.seq,
                 frame_size=(1920, 1080),
                 word_blade_crossfade_ms=rung.crossfade_ms or 20)
    root = ET.fromstring(xml)
    rung.reduce(root)
    assert ET.tostring(root) == ET.tostring(ET.fromstring(xml)), \
        "the top rung must not be reduced at all"


def test_stub_rung_places_many_clips_against_one_file_listing():
    """The de-dupe question only becomes visible at scale, so this rung must
    actually reach scale on real-length footage."""
    total = 2_316_000                       # job 28's real length
    tb = _tb(total)
    rung = next(r for r in LADDER if r.slug == "file_stub_dedupe")
    root = ET.fromstring(to_xml(rung.build(total, tb), "x.mp4", plan_id=5,
                                frame_size=(1920, 1080)))

    clips = root.find("sequence/media/video/track").findall("clipitem")
    with_path = [f for f in root.findall(".//file") if f.find("pathurl") is not None]
    assert len(clips) >= 20, "too few clips to expose a bin-duplication failure"
    assert len(with_path) == 1, "exactly one <file> may carry the full listing"


def test_many_keeps_scales_its_count_not_just_its_slot():
    """The 200ms slot floor means 40 clips need 16s of source; a shorter file
    must get fewer clips rather than clips running off the end."""
    assert len(_many_keeps(2_000)) < len(_many_keeps(2_316_000))
    assert all(end <= 2_000 for _, end in _many_keeps(2_000))
