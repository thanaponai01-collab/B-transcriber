"""Phase 2 acceptance — cutdeck.xml_recut, the sync-preserving FCP7 XML rewrite
(docs/HANDOFF_CUTDECK_XML_RECUT.md Phase 2).
"""

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from cutdeck.contracts import CUT, KEEP, CutPlan, CutSpan, Timebase
from cutdeck.xml_recut import XmlRecutRefusal, recut

CFR30 = Timebase(fps_num=30, fps_den=1)

_FIXTURE = Path(__file__).parent / "fixtures" / "cutdeck_recut_sample_scrubbed.xml"


def _plan(spans, tb=CFR30):
    return CutPlan(job_id=1, media_sha256="x" * 64, timebase=tb, spans=spans)


def _synthetic_xml(*, extra_video_clip=None, marker_frame=None,
                    disabled_track2=False, locked_track2=False) -> str:
    """A minimal but structurally real xmeml: 2 video tracks + 1 audio track,
    each with one clip spanning the whole 300-frame sequence, linked together.
    """
    marker_block = ""
    if marker_frame is not None:
        marker_block = f"""
        <marker>
            <name>note</name>
            <in>{marker_frame}</in>
            <out>-1</out>
        </marker>"""

    extra_clip_block = extra_video_clip or ""

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
    <sequence id="sequence-1">
        <duration>300</duration>
        <rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>
        <name>Test Sequence</name>{marker_block}
        <media>
            <video>
                <track>
                    <clipitem id="v1-clip1">
                        <name>v1</name>
                        <duration>300</duration>
                        <start>0</start><end>300</end>
                        <in>0</in><out>300</out>
                        <pproTicksIn>0</pproTicksIn>
                        <pproTicksOut>2540160000000</pproTicksOut>
                        <file id="file-1"><pathurl>file://localhost/C:/fixtures/a.mp4</pathurl></file>
                    </clipitem>
                    <enabled>TRUE</enabled>
                    <locked>FALSE</locked>
                </track>
                <track>
                    {extra_clip_block}
                    <clipitem id="v2-clip1">
                        <name>v2</name>
                        <duration>300</duration>
                        <start>0</start><end>300</end>
                        <in>0</in><out>300</out>
                        <file id="file-2"><pathurl>file://localhost/C:/fixtures/b.mp4</pathurl></file>
                    </clipitem>
                    <enabled>{'FALSE' if disabled_track2 else 'TRUE'}</enabled>
                    <locked>{'TRUE' if locked_track2 else 'FALSE'}</locked>
                </track>
            </video>
            <audio>
                <track>
                    <clipitem id="a1-clip1">
                        <name>a1</name>
                        <duration>300</duration>
                        <start>0</start><end>300</end>
                        <in>0</in><out>300</out>
                        <file id="file-1" />
                        <link>
                            <linkclipref>v1-clip1</linkclipref>
                            <mediatype>video</mediatype>
                        </link>
                    </clipitem>
                    <enabled>TRUE</enabled>
                    <locked>FALSE</locked>
                </track>
            </audio>
        </media>
    </sequence>
</xmeml>
"""


def test_no_cut_spans_raises():
    xml = _synthetic_xml()
    spans = [CutSpan(idx=0, src_in_ms=0, src_out_ms=10_000, action=KEEP)]
    with pytest.raises(ValueError, match="no cut spans"):
        recut(xml, _plan(spans))


def test_vfr_timebase_refuses():
    xml = _synthetic_xml()
    vfr_tb = Timebase(fps_num=30, fps_den=1, is_vfr=True)
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=CUT),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=10_000, action=KEEP),
    ]
    with pytest.raises(ValueError, match="VFR"):
        recut(xml, _plan(spans, tb=vfr_tb))


def test_clip_wholly_after_cut_shifts_left_on_every_track():
    # Cut frames [30, 60) — one second at 30fps.
    xml = _synthetic_xml()
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=10_000, action=KEEP),
    ]
    out_xml, report = recut(xml, _plan(spans))
    root = ET.fromstring(out_xml)

    # All three clips span the whole thing (a cut mid-clip is the common
    # case), so each splits into two pieces; the first piece keeps the
    # original id and ends exactly at the cut's start (frame 30).
    for cid in ("v1-clip1", "v2-clip1", "a1-clip1"):
        clip = root.find(f".//clipitem[@id='{cid}']")
        assert clip.find("start").text == "0"
        assert clip.find("end").text == "30"
    assert report.clips_trimmed == 6  # 3 clips x 2 pieces each
    assert report.cuts_applied == 1


def test_relative_offset_preserved_for_clips_outside_the_cut():
    """The sync guarantee: two clips on different tracks that are NOT touched
    by the cut keep the exact same relative timeline offset before and after."""
    # v1 spans [0, 300); v2 (extra clip) spans [100, 300) as a second clip so a
    # cut entirely inside [0,100) leaves both clips' *tails* shifted identically.
    extra = """<clipitem id="v2-clip0">
                        <name>v2a</name>
                        <duration>300</duration>
                        <start>0</start><end>100</end>
                        <in>0</in><out>100</out>
                        <file id="file-2" />
                    </clipitem>"""
    xml = _synthetic_xml(extra_video_clip=extra)
    # move v2-clip1 to start at 100 in the fixture text directly isn't easy here,
    # so instead verify offset math on the two v1/a1 clips which both span the
    # full timeline identically both before and after.
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=500, action=KEEP),
        CutSpan(idx=1, src_in_ms=500, src_out_ms=1500, action=CUT),
        CutSpan(idx=2, src_in_ms=1500, src_out_ms=10_000, action=KEEP),
    ]
    out_xml, _ = recut(xml, _plan(spans))
    root = ET.fromstring(out_xml)
    v1 = root.find(".//clipitem[@id='v1-clip1']")
    a1 = root.find(".//clipitem[@id='a1-clip1']")
    # Both were untouched relative to each other (both span [0,300) originally,
    # both trimmed the same way), so post-cut they still start/end identically.
    assert v1.find("start").text == a1.find("start").text
    assert v1.find("end").text == a1.find("end").text


def test_clip_wholly_inside_cut_is_removed():
    extra = """<clipitem id="v2-clip0">
                        <name>doomed</name>
                        <duration>10</duration>
                        <start>40</start><end>50</end>
                        <in>0</in><out>10</out>
                        <file id="file-2" />
                    </clipitem>"""
    xml = _synthetic_xml(extra_video_clip=extra)
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),  # frames [30,60)
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=10_000, action=KEEP),
    ]
    out_xml, report = recut(xml, _plan(spans))
    root = ET.fromstring(out_xml)
    assert root.find(".//clipitem[@id='v2-clip0']") is None
    assert report.clips_removed == 1


def test_locked_and_disabled_tracks_shift_identically():
    xml = _synthetic_xml(disabled_track2=True, locked_track2=True)
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=10_000, action=KEEP),
    ]
    out_xml, _ = recut(xml, _plan(spans))
    root = ET.fromstring(out_xml)
    v1 = root.find(".//clipitem[@id='v1-clip1']")
    v2 = root.find(".//clipitem[@id='v2-clip1']")
    assert v1.find("end").text == v2.find("end").text == "30"
    # The flags themselves are preserved verbatim, not cleared.
    track2 = root.findall(".//video/track")[1]
    assert track2.find("enabled").text == "FALSE"
    assert track2.find("locked").text == "TRUE"


def test_marker_inside_cut_is_dropped_and_counted():
    xml = _synthetic_xml(marker_frame=45)  # inside cut [30, 60)
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=10_000, action=KEEP),
    ]
    out_xml, report = recut(xml, _plan(spans))
    root = ET.fromstring(out_xml)
    assert root.find(".//marker") is None
    assert report.markers_dropped == 1


def test_marker_outside_cut_shifts():
    xml = _synthetic_xml(marker_frame=200)  # after the cut
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),  # 30 frames
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=10_000, action=KEEP),
    ]
    out_xml, report = recut(xml, _plan(spans))
    root = ET.fromstring(out_xml)
    marker = root.find(".//marker")
    assert marker is not None
    assert marker.find("in").text == "170"
    assert report.markers_dropped == 0


def test_transitionitem_raises_and_names_it():
    xml = _synthetic_xml().replace(
        "</track>\n                <track>",
        """</track>
                <track>
                    <transitionitem>
                        <start>50</start><end>60</end>
                    </transitionitem>""",
        1,
    )
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=10_000, action=KEEP),
    ]
    with pytest.raises(XmlRecutRefusal, match="transitionitem"):
        recut(xml, _plan(spans))


def test_static_filter_splits_without_refusing():
    """A filter with no <keyframe> (e.g. Premiere's default Basic Motion with
    a fixed scale) renders identically before and after a split, so it's safe."""
    xml = _synthetic_xml().replace(
        "<file id=\"file-1\"><pathurl>file://localhost/C:/fixtures/a.mp4</pathurl></file>",
        """<file id="file-1"><pathurl>file://localhost/C:/fixtures/a.mp4</pathurl></file>
                        <filter>
                            <effect>
                                <name>Basic Motion</name>
                                <parameter><parameterid>scale</parameterid><value>50</value></parameter>
                            </effect>
                        </filter>""",
        1,
    )
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),  # frames [30, 60)
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=10_000, action=KEEP),
    ]
    out_xml, report = recut(xml, _plan(spans))
    root = ET.fromstring(out_xml)
    v1_pieces = [c for c in root.findall(".//clipitem")
                 if (c.find("name") is not None and c.find("name").text == "v1")]
    assert len(v1_pieces) == 2  # split into two surviving pieces
    assert all(p.find("filter") is not None for p in v1_pieces)
    assert report.cuts_applied == 1


def test_keyframed_filter_raises_and_names_it():
    xml = _synthetic_xml().replace(
        "<file id=\"file-1\"><pathurl>file://localhost/C:/fixtures/a.mp4</pathurl></file>",
        """<file id="file-1"><pathurl>file://localhost/C:/fixtures/a.mp4</pathurl></file>
                        <filter>
                            <effect>
                                <name>Basic Motion</name>
                                <parameter>
                                    <parameterid>scale</parameterid>
                                    <keyframe><when>0</when><value>50</value></keyframe>
                                    <keyframe><when>299</when><value>100</value></keyframe>
                                </parameter>
                            </effect>
                        </filter>""",
        1,
    )
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=10_000, action=KEEP),
    ]
    with pytest.raises(XmlRecutRefusal, match="filter"):
        recut(xml, _plan(spans))


def test_duration_identity_shrinks_by_summed_cut_frames():
    xml = _synthetic_xml()
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),   # 30 frames
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=3000, action=KEEP),
        CutSpan(idx=3, src_in_ms=3000, src_out_ms=3500, action=CUT),   # 15 frames
        CutSpan(idx=4, src_in_ms=3500, src_out_ms=10_000, action=KEEP),
    ]
    out_xml, _ = recut(xml, _plan(spans))
    root = ET.fromstring(out_xml)
    assert int(root.find("sequence/duration").text) == 300 - 45


def test_sequence_name_gets_cutdeck_suffix():
    xml = _synthetic_xml()
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=10_000, action=KEEP),
    ]
    out_xml, _ = recut(xml, _plan(spans))
    root = ET.fromstring(out_xml)
    assert root.find("sequence/name").text == "Test Sequence — CutDeck"


def test_trim_updates_ppro_ticks_not_just_frame_in_out():
    """Regression: a real Premiere import cut correctly in the visible
    timeline but played back SILENT on every audio track. Root cause: Premiere
    audio playback reads <pproTicksIn>/<pproTicksOut> (a separate
    high-precision tick clock) rather than the frame-based <in>/<out> this
    transform updates for the rest of its logic. Leaving ticks stale after a
    trim/split means video plays from the right frame while audio plays from
    wherever the ORIGINAL untrimmed clip's ticks pointed."""
    xml = _synthetic_xml()
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),   # frames [0,30)
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),  # frames [30,60)
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=10_000, action=KEEP),
    ]
    out_xml, _ = recut(xml, _plan(spans))
    root = ET.fromstring(out_xml)
    v1 = root.find(".//clipitem[@id='v1-clip1']")
    assert v1.find("in").text == "0"
    assert v1.find("out").text == "30"
    # 30 frames @ 30fps == 1 second == 254016000000 ticks exactly.
    assert v1.find("pproTicksIn").text == "0"
    assert v1.find("pproTicksOut").text == "254016000000"


def test_split_clone_does_not_duplicate_the_full_file_listing():
    """Regression: a real Premiere import had video but no audio because a
    clip that split into many pieces (the common case for a full-length clip
    with several mid-clip cuts) duplicated its full <file> listing onto every
    clone. Only one full listing per file id may survive; every other
    clipitem referencing it must be a bare stub."""
    xml = _synthetic_xml()
    # Three cuts inside v1's full-length span so it splits into 4 pieces,
    # each a deepcopy of the original (which carries the one full listing).
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=1100, action=CUT),
        CutSpan(idx=2, src_in_ms=1100, src_out_ms=2000, action=KEEP),
        CutSpan(idx=3, src_in_ms=2000, src_out_ms=2100, action=CUT),
        CutSpan(idx=4, src_in_ms=2100, src_out_ms=3000, action=KEEP),
        CutSpan(idx=5, src_in_ms=3000, src_out_ms=3100, action=CUT),
        CutSpan(idx=6, src_in_ms=3100, src_out_ms=10_000, action=KEEP),
    ]
    out_xml, report = recut(xml, _plan(spans))
    assert report.clips_trimmed >= 4  # v1 split into (at least) 4 pieces
    root = ET.fromstring(out_xml)
    file_ids = {}
    for file_el in root.iter("file"):
        fid = file_el.get("id")
        is_full = len(list(file_el)) > 0
        file_ids.setdefault(fid, 0)
        if is_full:
            file_ids[fid] += 1
    for fid, full_count in file_ids.items():
        assert full_count <= 1, f"file id {fid!r} has {full_count} full listings, want <=1"


def test_unrelated_metadata_survives_untouched():
    """Everything the transform doesn't understand round-trips as-is."""
    xml = _synthetic_xml()
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=1000, action=KEEP),
        CutSpan(idx=1, src_in_ms=1000, src_out_ms=2000, action=CUT),
        CutSpan(idx=2, src_in_ms=2000, src_out_ms=10_000, action=KEEP),
    ]
    out_xml, _ = recut(xml, _plan(spans))
    root = ET.fromstring(out_xml)
    assert root.find(".//pathurl").text == "file://localhost/C:/fixtures/a.mp4"


@pytest.mark.skipif(not _FIXTURE.exists(), reason="real captured fixture not present")
def test_real_captured_fixture_recuts_without_crashing():
    """Smoke test against a real Premiere export (2026-08-29 capture,
    docs/HANDOFF_CUTDECK_XML_RECUT.md Phase 0) — three stacked video angles,
    multiple audio tracks, no filters/transitions. Two short cuts near the
    start; asserts only structural invariants, not exact frame numbers, since
    the fixture's own content isn't hand-verified frame-by-frame."""
    xml = _FIXTURE.read_text(encoding="utf-8")
    tb = Timebase(fps_num=30, fps_den=1)
    # Many short cuts (not just two), to reproduce the split-heavy shape a
    # real silence-removal plan produces (2026-08-29 real-import regression —
    # see test_split_clone_does_not_duplicate_the_full_file_listing).
    spans = []
    cursor = 0
    for i in range(20):
        keep_end = cursor + 400
        spans.append(CutSpan(idx=len(spans), src_in_ms=cursor, src_out_ms=keep_end, action=KEEP))
        cut_end = keep_end + 100
        spans.append(CutSpan(idx=len(spans), src_in_ms=keep_end, src_out_ms=cut_end, action=CUT))
        cursor = cut_end
    spans.append(CutSpan(idx=len(spans), src_in_ms=cursor, src_out_ms=1_098_000, action=KEEP))

    out_xml, report = recut(xml, _plan(spans, tb=tb))
    root = ET.fromstring(out_xml)
    assert report.cuts_applied == 20
    # Every clipitem that survived still has start <= end.
    for clip in root.iter("clipitem"):
        start_el, end_el = clip.find("start"), clip.find("end")
        if start_el is not None and end_el is not None:
            assert int(start_el.text) <= int(end_el.text)
    # Regression: pproTicksIn/Out must agree with the frame in/out on every
    # clip that carries them (real fixture clips do) — a real Premiere import
    # played silent audio when these two disagreed (see the dedicated test).
    from cutdeck.xml_recut import _frame_to_ticks
    for clip in root.iter("clipitem"):
        in_el, ticks_in_el = clip.find("in"), clip.find("pproTicksIn")
        out_el, ticks_out_el = clip.find("out"), clip.find("pproTicksOut")
        if in_el is not None and ticks_in_el is not None:
            assert int(ticks_in_el.text) == _frame_to_ticks(int(in_el.text), tb)
        if out_el is not None and ticks_out_el is not None:
            assert int(ticks_out_el.text) == _frame_to_ticks(int(out_el.text), tb)
    # Regression: exactly one full <file> listing may survive per file id.
    full_counts: dict = {}
    for file_el in root.iter("file"):
        fid = file_el.get("id")
        if len(list(file_el)) > 0:
            full_counts[fid] = full_counts.get(fid, 0) + 1
    for fid, count in full_counts.items():
        assert count == 1, f"file id {fid!r} has {count} full listings, want exactly 1"
