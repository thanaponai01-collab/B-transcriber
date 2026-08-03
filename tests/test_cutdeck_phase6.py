"""Phase 6 acceptance — cutdeck/takes.py, the retake/false-start LLM classifier
(HANDOFF_CUTDECK_WORDLEVEL.md Phase 6, IMPLEMENT_CUTDECK.md §B.3 ``takes.py``).

Select-only discipline mirrors ``transcribe.pipeline.reconcile``: a mock LLM
returning a hallucinated or missing id must raise, never be silently
accepted. The deterministic marker pre-pass (``rules.retake_marker_segments``)
is tested separately from the LLM step it feeds.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck.contracts import (  # noqa: E402
    BLADE_WORD,
    CUT,
    KEEP,
    LABEL_FALSE_START,
    LABEL_KEEP_WORTHY,
    LABEL_MISTAKE,
    LABEL_RETAKE,
    SOURCE_LLM,
    SOURCE_RULE,
    CutConfig,
    Label,
    Segment,
)
from cutdeck.rules import build_cut_spans, label_cuts, retake_marker_segments  # noqa: E402
from cutdeck.takes import (  # noqa: E402
    HallucinatedIdError,
    classify_cluster,
    find_false_start_pairs,
    find_repeat_take_clusters,
    label_takes,
)


def _seg(id_, start_ms, end_ms, text):
    return Segment(id=id_, start_ms=start_ms, end_ms=end_ms, token_ids=[id_], text=text)


# ── deterministic marker pre-pass ───────────────────────────────────────────

def test_retake_marker_segments_detects_marker_phrase():
    cfg = CutConfig(retake_markers=("เดี๋ยวเอาใหม่",))
    segments = [
        _seg(0, 0, 1000, "วันนี้อากาศดี"),
        _seg(1, 1000, 2000, "เดี๋ยวเอาใหม่นะครับ"),
    ]
    assert retake_marker_segments(segments, cfg) == [1]


def test_retake_marker_segments_empty_when_no_markers_configured():
    cfg = CutConfig(retake_markers=())
    segments = [_seg(0, 0, 1000, "เดี๋ยวเอาใหม่")]
    assert retake_marker_segments(segments, cfg) == []


def test_retake_marker_segments_no_false_positive():
    cfg = CutConfig(retake_markers=("เดี๋ยวเอาใหม่",))
    segments = [_seg(0, 0, 1000, "วันนี้อากาศดีมาก")]
    assert retake_marker_segments(segments, cfg) == []


# ── deterministic pre-filters ────────────────────────────────────────────────

def test_find_repeat_take_clusters_groups_near_duplicates():
    cfg = CutConfig(repeat_take_jaccard_threshold=0.55, retake_window_segments=5)
    segments = [
        _seg(0, 0, 1000, "ผมชื่อจอห์น"),
        _seg(1, 1500, 2500, "ผมชื่อจอห์น"),
        _seg(2, 3000, 4000, "ผมชื่อจอห์น"),
        _seg(3, 5000, 6000, "วันนี้อากาศดีมาก"),
    ]
    clusters = find_repeat_take_clusters(segments, cfg)
    assert len(clusters) == 1
    assert [s.id for s in clusters[0]] == [0, 1, 2]


def test_find_repeat_take_clusters_ignores_dissimilar_segments():
    cfg = CutConfig(repeat_take_jaccard_threshold=0.55, retake_window_segments=5)
    segments = [
        _seg(0, 0, 1000, "ผมชื่อจอห์น"),
        _seg(1, 1500, 2500, "วันนี้อากาศดีมาก"),
    ]
    assert find_repeat_take_clusters(segments, cfg) == []


def test_find_false_start_pairs_matches_short_then_longer_echo():
    cfg = CutConfig(false_start_max_ms=2500)
    segments = [
        _seg(0, 0, 1000, "ผม"),                     # 1000ms, short
        _seg(1, 1200, 4200, "ผมคิดว่ามันดีมาก"),      # longer, shares prefix "ผม"
    ]
    pairs = find_false_start_pairs(segments, cfg)
    assert len(pairs) == 1
    assert (pairs[0][0].id, pairs[0][1].id) == (0, 1)


def test_find_false_start_pairs_skips_when_first_not_short():
    cfg = CutConfig(false_start_max_ms=500)
    segments = [
        _seg(0, 0, 1000, "ผม"),  # 1000ms >= 500ms threshold — not a false-start candidate
        _seg(1, 1200, 4200, "ผมคิดว่ามันดีมาก"),
    ]
    assert find_false_start_pairs(segments, cfg) == []


# ── select-only discipline ───────────────────────────────────────────────────

def test_classify_cluster_raises_on_hallucinated_id():
    segments = [_seg(0, 0, 1000, "a"), _seg(1, 1000, 2000, "a")]

    def bad_llm_fn(candidates, bias_terms):
        return [{"id": 999, "action": "cut", "reason": "bad"}]

    try:
        classify_cluster(segments, LABEL_RETAKE, bad_llm_fn, gap_before_ms={})
        assert False, "expected HallucinatedIdError"
    except HallucinatedIdError:
        pass


def test_classify_cluster_raises_on_missing_id_coverage():
    segments = [_seg(0, 0, 1000, "a"), _seg(1, 1000, 2000, "a")]

    def partial_llm_fn(candidates, bias_terms):
        return [{"id": 0, "action": "cut", "reason": "partial"}]

    try:
        classify_cluster(segments, LABEL_RETAKE, partial_llm_fn, gap_before_ms={})
        assert False, "expected HallucinatedIdError"
    except HallucinatedIdError:
        pass


def test_classify_cluster_never_receives_timestamps_in_payload():
    segments = [_seg(0, 0, 1000, "a")]
    seen = {}

    def capturing_llm_fn(candidates, bias_terms):
        seen["payload"] = candidates
        return [{"id": 0, "action": "keep", "reason": "ok"}]

    classify_cluster(segments, LABEL_RETAKE, capturing_llm_fn, gap_before_ms={0: 0})
    keys = set(seen["payload"][0].keys())
    assert keys == {"id", "text", "duration_ms", "gap_before_ms"}


# ── label_takes orchestration ────────────────────────────────────────────────

def test_label_takes_off_by_default_is_all_keep():
    cfg = CutConfig()  # takes_llm_enabled defaults False
    segments = [_seg(0, 0, 1000, "เดี๋ยวเอาใหม่"), _seg(1, 1000, 2000, "วันนี้อากาศดี")]
    labels = label_takes(segments, cfg, llm_fn=None)
    assert [(l.segment_id, l.action, l.kind, l.source) for l in labels] == [
        (0, KEEP, LABEL_KEEP_WORTHY, SOURCE_RULE),
        (1, KEEP, LABEL_KEEP_WORTHY, SOURCE_RULE),
    ]


def test_label_takes_marker_hit_stays_keep_when_llm_off_even_with_llm_fn_supplied():
    cfg = CutConfig(retake_markers=("เดี๋ยวเอาใหม่",), takes_llm_enabled=False)
    segments = [_seg(0, 0, 1000, "เดี๋ยวเอาใหม่นะ")]

    def would_cut_everything(candidates, bias_terms):
        return [{"id": c["id"], "action": "cut", "reason": "x"} for c in candidates]

    labels = label_takes(segments, cfg, llm_fn=would_cut_everything)
    assert labels[0].action == KEEP


def test_label_takes_duplicate_take_fixture_keeps_exactly_the_last_take():
    cfg = CutConfig(takes_llm_enabled=True, repeat_take_jaccard_threshold=0.55,
                     retake_window_segments=5)
    segments = [
        _seg(0, 0, 1000, "ผมชื่อจอห์น"),
        _seg(1, 1500, 2500, "ผมชื่อจอห์น"),
        _seg(2, 3000, 4000, "ผมชื่อจอห์น"),
    ]

    def keep_last_llm_fn(candidates, bias_terms):
        last_id = max(c["id"] for c in candidates)
        return [
            {"id": c["id"], "action": ("keep" if c["id"] == last_id else "cut"), "reason": "dup"}
            for c in candidates
        ]

    labels = {l.segment_id: l for l in label_takes(segments, cfg, llm_fn=keep_last_llm_fn)}
    assert labels[0].action == CUT
    assert labels[1].action == CUT
    assert labels[2].action == KEEP
    assert all(l.kind == LABEL_RETAKE for l in labels.values())


def test_label_takes_marker_resolves_lookback_window_via_llm():
    cfg = CutConfig(retake_markers=("เดี๋ยวเอาใหม่",), takes_llm_enabled=True,
                     retake_window_segments=5)
    segments = [
        _seg(0, 0, 1000, "ผมชื่อจอห์นครับ"),
        _seg(1, 1200, 2200, "เอ่อ ผิด"),
        _seg(2, 2400, 3400, "เดี๋ยวเอาใหม่"),
    ]

    def reach_back_one(candidates, bias_terms):
        marker_id = max(c["id"] for c in candidates)
        return [
            {"id": c["id"], "action": ("cut" if c["id"] >= marker_id - 1 else "keep"), "reason": "retake"}
            for c in candidates
        ]

    labels = {l.segment_id: l for l in label_takes(segments, cfg, llm_fn=reach_back_one)}
    assert labels[0].action == KEEP
    assert labels[1].action == CUT
    assert labels[2].action == CUT
    assert labels[1].kind == LABEL_MISTAKE
    assert labels[2].kind == LABEL_MISTAKE


def test_label_takes_false_start_pattern():
    cfg = CutConfig(takes_llm_enabled=True, false_start_max_ms=2500)
    segments = [
        _seg(0, 0, 1000, "ผม"),
        _seg(1, 1200, 4200, "ผมคิดว่ามันดีมาก"),
    ]

    def keep_second(candidates, bias_terms):
        keep_id = max(c["id"] for c in candidates)
        return [
            {"id": c["id"], "action": ("keep" if c["id"] == keep_id else "cut"), "reason": "false_start"}
            for c in candidates
        ]

    labels = {l.segment_id: l for l in label_takes(segments, cfg, llm_fn=keep_second)}
    assert labels[0].action == CUT
    assert labels[1].action == KEEP
    assert labels[0].kind == LABEL_FALSE_START


# ── wired into rules.build_cut_spans ────────────────────────────────────────

def test_label_cuts_converts_cut_labels_to_raw_cuts_over_segment_span():
    segments = [_seg(0, 1000, 2000, "เดี๋ยวเอาใหม่"), _seg(1, 3000, 4000, "keep me")]
    labels = [
        Label(segment_id=0, action=CUT, kind=LABEL_MISTAKE, source=SOURCE_LLM),
        Label(segment_id=1, action=KEEP, kind=LABEL_KEEP_WORTHY, source=SOURCE_RULE),
    ]
    cuts = label_cuts(labels, segments)
    assert cuts == [(1000, 2000, LABEL_MISTAKE, SOURCE_LLM, BLADE_WORD)]


def test_build_cut_spans_folds_in_label_cuts():
    segments = [_seg(0, 1000, 2000, "เดี๋ยวเอาใหม่")]
    labels = [Label(segment_id=0, action=CUT, kind=LABEL_MISTAKE, source=SOURCE_LLM)]
    cfg = CutConfig(min_clip_ms=500)  # leading 1000ms keep island must not trip min-clip merge
    out = build_cut_spans([], None, 5000, cfg, segments=segments, labels=labels)
    take_cuts = [s for s in out if s.action == CUT and s.reason == LABEL_MISTAKE]
    assert len(take_cuts) == 1
    assert (take_cuts[0].src_in_ms, take_cuts[0].src_out_ms) == (1000, 2000)
    assert take_cuts[0].blade == BLADE_WORD


def test_build_cut_spans_labels_none_is_byte_identical_to_omitted():
    segments = [_seg(0, 1000, 2000, "keep")]
    cfg = CutConfig()
    a = build_cut_spans([], None, 5000, cfg, segments=segments)
    b = build_cut_spans([], None, 5000, cfg, segments=segments, labels=None)
    assert [(s.action, s.src_in_ms, s.src_out_ms) for s in a] == \
           [(s.action, s.src_in_ms, s.src_out_ms) for s in b]
