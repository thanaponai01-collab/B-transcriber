"""CutDeck Phase 2 acceptance tests (HANDOFF_CUTDECK_WORDLEVEL.md Phase 2).

Covers:
  2.1 filler_cuts revived on the Word timeline (not phrase-cue tokens).
  2.2 repeat_cuts — stutter / duplicated-word removal.
  2.3 the blade contract — CutSpan.blade, plan round-trip, XML crossfade.

All GPU-free. Run: python -m pytest tests/test_cutdeck_phase2.py -v
"""

from xml.etree import ElementTree as ET

from cutdeck.contracts import (
    BLADE_VAD,
    BLADE_WORD,
    CUT,
    KEEP,
    CutConfig,
    CutPlan,
    CutSpan,
    Segment,
    Timebase,
)
from cutdeck.rules import build_cut_spans, filler_cuts, repeat_cuts
from cutdeck import plan as planmod
from cutdeck.words import Word
from cutdeck.xml_export import to_xml

NTSC2997 = Timebase(fps_num=30000, fps_den=1001, duration_ms=3_600_000)


def _seg(id_, start, end, ids=None, text=""):
    return Segment(id=id_, start_ms=start, end_ms=end, token_ids=ids or [], text=text)


# ── 2.1 filler_cuts on the word timeline ──────────────────────────────────────

def test_filler_cut_on_word_timeline_isolates_exactly_the_filler_word():
    cfg = CutConfig(fillers_enabled=True, filler_lexicon=("เอ่อ",), min_clip_ms=0)
    words = [
        Word("หนึ่ง", 0, 500, 0.9),
        Word("เอ่อ", 600, 800, 0.9),
        Word("สอง", 900, 1400, 0.9),
    ]
    out = build_cut_spans([], None, 2000, cfg, words=words)
    cuts = [(s.src_in_ms, s.src_out_ms, s.reason, s.blade) for s in out if s.action == CUT]
    assert cuts == [(600, 800, "filler", BLADE_WORD)]


def test_filler_cuts_direct_empty_words_warns_and_returns_nothing(caplog):
    cfg = CutConfig(fillers_enabled=True, filler_lexicon=("เอ่อ",))
    with caplog.at_level("WARNING"):
        out = filler_cuts([], [], cfg, job_id=29)
    assert out == []
    assert any("job 29" in r.message for r in caplog.records)


def test_filler_disabled_returns_nothing_without_touching_words():
    cfg = CutConfig(fillers_enabled=False)
    # A word list that would obviously match if fillers were on.
    words = [Word("เอ่อ", 0, 200, 0.9)]
    assert filler_cuts(words, [], cfg) == []


def test_contextual_filler_only_cut_when_isolated_word_level():
    cfg = CutConfig(fillers_enabled=True, filler_lexicon=(),
                    filler_lexicon_contextual=("แบบ",), contextual_isolation_ms=200,
                    min_clip_ms=0)
    word = Word("แบบ", 1000, 1200, 0.9)

    # Not isolated (no surrounding silence) → kept.
    assert filler_cuts([word], [], cfg) == []

    # Isolated by >=200ms silence on both sides → cut.
    silences = [(800, 1000), (1200, 1400)]
    cuts = filler_cuts([word], silences, cfg)
    assert cuts and cuts[0][2] == "filler" and cuts[0][4] == BLADE_WORD


# ── 2.2 repeat_cuts — stutter / duplicated words ──────────────────────────────

def test_repeat_cuts_keeps_last_of_triple_repeat():
    cfg = CutConfig(repeats_enabled=True, repeat_max_ngram=4, repeat_max_gap_ms=600)
    words = [
        Word("ไป", 0, 200, 0.9),
        Word("ไป", 250, 450, 0.9),
        Word("ไป", 500, 700, 0.9),
    ]
    seg = _seg(0, 0, 700)
    cuts = repeat_cuts(words, [seg], cfg)
    assert len(cuts) == 2
    assert (cuts[0][0], cuts[0][1]) == (0, 200)
    assert (cuts[1][0], cuts[1][1]) == (250, 450)
    assert all(c[2] == "repeat" and c[4] == BLADE_WORD for c in cuts)


def test_repeat_cuts_multi_word_ngram_keeps_last():
    cfg = CutConfig(repeats_enabled=True)
    words = [
        Word("เดือน", 0, 200, 0.9), Word("นึง", 200, 400, 0.9),
        Word("เดือน", 450, 650, 0.9), Word("นึง", 650, 850, 0.9),
    ]
    seg = _seg(0, 0, 850)
    cuts = repeat_cuts(words, [seg], cfg)
    assert len(cuts) == 1
    assert (cuts[0][0], cuts[0][1]) == (0, 400)  # first "เดือน นึง" cut, second kept


def test_repeat_cuts_mai_yamok_is_not_a_repeat():
    cfg = CutConfig(repeats_enabled=True)
    words = [Word("เด็ก", 0, 200, 0.9), Word("ๆ", 200, 300, 0.9)]
    seg = _seg(0, 0, 300)
    assert repeat_cuts(words, [seg], cfg) == []


def test_repeat_cuts_never_crosses_segment_boundary():
    cfg = CutConfig(repeats_enabled=True)
    words = [
        Word("ไป", 0, 200, 0.9),
        Word("ไป", 5000, 5200, 0.9),  # same text, but a different utterance entirely
    ]
    segs = [_seg(0, 0, 200), _seg(1, 5000, 5200)]
    assert repeat_cuts(words, segs, cfg) == []


def test_repeat_cuts_gap_too_large_is_not_a_repeat():
    cfg = CutConfig(repeats_enabled=True, repeat_max_gap_ms=600)
    words = [Word("ไป", 0, 200, 0.9), Word("ไป", 1100, 1300, 0.9)]  # 900ms gap
    seg = _seg(0, 0, 1300)
    assert repeat_cuts(words, [seg], cfg) == []


def test_repeat_cuts_disabled_by_default():
    cfg = CutConfig()
    words = [Word("ไป", 0, 200, 0.9), Word("ไป", 250, 450, 0.9)]
    seg = _seg(0, 0, 450)
    assert repeat_cuts(words, [seg], cfg) == []


def test_repeat_cuts_determinism():
    cfg = CutConfig(repeats_enabled=True)
    words = [
        Word("ไป", 0, 200, 0.9), Word("ไป", 250, 450, 0.9), Word("ไป", 500, 700, 0.9),
    ]
    seg = _seg(0, 0, 700)
    assert repeat_cuts(words, [seg], cfg) == repeat_cuts(words, [seg], cfg)


def test_repeat_cuts_wired_through_build_cut_spans():
    cfg = CutConfig(repeats_enabled=True, min_clip_ms=0)
    words = [Word("ไป", 0, 200, 0.9), Word("ไป", 250, 450, 0.9), Word("ไป", 500, 700, 0.9)]
    seg = _seg(0, 0, 700)
    out = build_cut_spans([], None, 700, cfg, words=words, segments=[seg])
    cuts = [(s.src_in_ms, s.src_out_ms, s.reason, s.blade) for s in out if s.action == CUT]
    assert cuts == [(0, 200, "repeat", BLADE_WORD), (250, 450, "repeat", BLADE_WORD)]


# ── 2.3 the blade contract ────────────────────────────────────────────────────

def test_plan_roundtrips_both_blade_kinds():
    spans = [
        CutSpan(0, 0, 1000, KEEP),
        CutSpan(1, 1000, 1200, CUT, reason="filler", blade=BLADE_WORD),
        CutSpan(2, 1200, 2000, KEEP),
        CutSpan(3, 2000, 3000, CUT, reason="silence", blade=BLADE_VAD),
        CutSpan(4, 3000, 4000, KEEP),
    ]
    plan = planmod.build_plan(1, "abc", Timebase(30, 1), 4000, spans)
    again = planmod.loads(planmod.dumps(plan))
    assert [s.blade for s in again.spans] == [s.blade for s in plan.spans]
    assert again.spans[1].blade == BLADE_WORD
    assert again.spans[3].blade == BLADE_VAD


def test_old_plan_json_without_blade_key_defaults_to_vad():
    data = {
        "plan_version": "1.0", "job_id": 1, "media_sha256": "abc",
        "timebase": {"fps_num": 30, "fps_den": 1},
        "spans": [
            {"idx": 0, "src_in_ms": 0, "src_out_ms": 1000, "action": "keep",
             "reason": None, "source": None, "segment_ids": []},
        ],
    }
    plan = planmod.from_dict(data)
    assert plan.spans[0].blade == BLADE_VAD


def test_assert_contiguous_exhaustive_unaffected_by_blade():
    spans = [
        CutSpan(0, 0, 1000, KEEP),
        CutSpan(1, 1000, 1200, CUT, reason="filler", blade=BLADE_WORD),
        CutSpan(2, 1200, 2000, KEEP),
    ]
    planmod.assert_contiguous_exhaustive(spans, 2000)  # must not raise


def _plan(spans, duration_ms=3_600_000):
    return CutPlan(job_id=42, media_sha256="x" * 64, timebase=NTSC2997, spans=spans)


def test_xml_export_emits_crossfade_only_on_word_blade_edges():
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=10_000, action=KEEP),
        CutSpan(idx=1, src_in_ms=10_000, src_out_ms=10_500, action=CUT,
                reason="filler", blade=BLADE_WORD),
        CutSpan(idx=2, src_in_ms=10_500, src_out_ms=20_000, action=KEEP),
        CutSpan(idx=3, src_in_ms=20_000, src_out_ms=22_000, action=CUT,
                reason="silence", blade=BLADE_VAD),
        CutSpan(idx=4, src_in_ms=22_000, src_out_ms=3_600_000, action=KEEP),
    ]
    root = ET.fromstring(to_xml(_plan(spans), r"C:\Me\footage.mp4", plan_id=7))

    audio_tracks = root.findall("sequence/media/audio/track")
    assert audio_tracks, "expected audio tracks in export"
    for track in audio_tracks:
        transitions = track.findall("transitionitem")
        # Exactly one crossfade (the word-blade junction), none for the VAD junction.
        assert len(transitions) == 1
        effect = transitions[0].find("effect")
        assert effect.find("mediatype").text == "audio"

    video_transitions = root.find("sequence/media/video/track").findall("transitionitem")
    assert video_transitions == []  # video track never gets a crossfade


def test_xml_export_no_crossfade_when_all_vad_blade():
    spans = [
        CutSpan(idx=0, src_in_ms=0, src_out_ms=10_000, action=KEEP),
        CutSpan(idx=1, src_in_ms=10_000, src_out_ms=12_000, action=CUT,
                reason="silence", blade=BLADE_VAD),
        CutSpan(idx=2, src_in_ms=12_000, src_out_ms=3_600_000, action=KEEP),
    ]
    root = ET.fromstring(to_xml(_plan(spans), r"C:\Me\footage.mp4", plan_id=7))
    for track in root.findall("sequence/media/audio/track"):
        assert track.findall("transitionitem") == []
