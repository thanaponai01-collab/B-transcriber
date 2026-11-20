"""Scorer for HKS proposals against the gold (cutdeck/hks_score.py). Answers computed by hand."""

import pytest

from cutdeck.hks_gold import Cut, DayGold, OutputCut, SourceRange
from cutdeck.hks_score import Gold, Proposal, gold_of, gold_proposal, keep_all, parse_proposal, score


def ms(*ranges):
    return [(round(a * 1000), round(b * 1000)) for a, b in ranges]


def gold(span, **keeps):
    return Gold({m: (round(span[0] * 1000), round(span[1] * 1000)) for m in keeps},
                {m: ms(*rs) for m, rs in keeps.items()})


def proposal(covered=None, **keeps):
    return Proposal({m: ms(*rs) for m, rs in keeps.items()},
                    {m: ms(*rs) for m, rs in (covered or {}).items()})


def by_class(s):
    return {c.name: (c.proposed, c.hits, c.precision, c.gold, c.found, c.recall) for c in s.classes}


# Gold A: keeps 0-10, 12-20, 30-40 over the span 0-40; drops 10-12 (2 s) and 20-30 (10 s).
G = gold((0, 40), A=[(0, 10), (12, 20), (30, 40)])
# Proposal: keeps 0-10.4 and 12-25; drops 10.4-12 (1.6 s, between keeps) and 25-40 (15 s, tail).
P = proposal(A=[(0, 10.4), (12, 25)])


def test_seconds_agreement_precision_recall():
    s = score(G, P)
    assert s.span_s == 40 and s.kept_s == 23.4 and s.gold_kept_s == 28
    # keep/keep 10 + 8 = 18 s; drop/drop 1.6 + 5 = 6.6 s
    assert s.agreement == pytest.approx(24.6 / 40)
    assert s.keep_precision == pytest.approx(18 / 23.4)
    assert s.keep_recall == pytest.approx(18 / 28)


def test_boundaries_match_start_to_start_and_end_to_end():
    s = score(G, P)
    # proposed starts 10.4, 25; ends 12 (40 is the span end, not an edit). gold starts 10, 20; ends 12, 30.
    assert (s.proposed_edges, s.gold_edges, s.edge_hits) == (3, 4, 2)
    assert s.boundary_precision == pytest.approx(2 / 3) and s.boundary_recall == 0.5


def test_edge_exactly_half_a_second_away_hits_and_just_over_misses():
    g = gold((0, 30), A=[(0, 10), (20, 30)])
    assert score(g, proposal(A=[(0, 10.5), (19.5, 30)])).edge_hits == 2
    assert score(g, proposal(A=[(0, 10.52), (19.48, 30)])).edge_hits == 0


def test_an_edge_matches_at_most_once():
    g = gold((0, 30), A=[(0, 10), (20, 30)])  # one gold start at 10, one gold end at 20
    s = score(g, proposal(A=[(0, 9.8), (9.9, 10.1), (10.2, 30)]))  # starts 9.8, 10.1; ends 9.9, 10.2
    assert (s.proposed_edges, s.gold_edges, s.edge_hits) == (4, 2, 1)  # both starts near 10; one counts


def test_classes_precision_by_proposed_length_recall_over_gold():
    c = by_class(score(G, P))
    assert c["0.6-3s"] == (1, 1, 1.0, 1, 1, 1.0)  # 10.4-12 lies in 10-12; 10-12 is 80 % dropped
    assert c[">=15s"] == (1, 0, 0.0, 0, 0, None)  # 25-40: only 5 of 15 s in gold drops
    assert c["3-15s"] == (0, 0, None, 1, 1, 1.0)  # 20-30 is exactly 50 % dropped: found
    assert c["<0.6s"] == (0, 0, None, 0, 0, None)


def test_a_drop_of_exactly_0_6_s_is_in_the_0_6_to_3_class():
    g = gold((0, 20), A=[(0, 10), (10.6, 20)])
    c = by_class(score(g, proposal(A=[(0, 10), (10.6, 20)])))
    assert c["0.6-3s"] == (1, 1, 1.0, 1, 1, 1.0) and c["<0.6s"][0] == 0


def test_touching_ranges_merge_and_a_sub_frame_gap_is_no_drop():
    for keeps in ([(0, 5), (5, 10)], [(0, 5), (5.02, 10)]):
        s = score(gold((0, 10), A=[(0, 10)]), proposal(A=keeps))
        assert s.proposed_edges == 0 and s.agreement == 1.0
    assert score(gold((0, 10), A=[(0, 10)]), proposal(A=[(0, 5), (5.04, 10)])).proposed_edges == 2


def test_jump_cuts_skip_covered_drops_and_camera_changes():
    assert score(G, P).jump_cuts == 1  # 10.4-12 only; the tail 25-40 has no keep after it
    assert score(G, proposal(covered={"A": [(10.4, 12)]}, A=[(0, 10.4), (12, 25)])).jump_cuts == 0
    assert score(G, P, camera_changes={"A": [12.12]}).jump_cuts == 0
    assert score(G, P, camera_changes={"A": [12.13]}).jump_cuts == 1


def test_two_media_sum_and_keeps_outside_the_span_are_ignored():
    g = Gold({"A": (0, 30000), "B": (100000, 120000)},
             {"A": ms((0, 10), (20, 30)), "B": ms((100, 110), (115, 120))})
    s = score(g, proposal(A=[(0, 30)], B=[(50, 110)]))  # B 50-100 lies before B's span
    assert s.span_s == 50 and s.kept_s == 40 and s.gold_kept_s == 35
    # keep/keep: A 20 + B 10; drop/drop: B 110-120 vs 110-115 = 5
    assert s.agreement == pytest.approx(35 / 50)
    assert s.keep_precision == pytest.approx(30 / 40) and s.keep_recall == pytest.approx(30 / 35)


def test_unknown_media_is_an_error():
    with pytest.raises(ValueError, match="not in the scored span"):
        score(G, proposal(Z=[(0, 1)]))


def test_gold_against_itself_is_perfect():
    s = score(G, Proposal(G.keeps))
    assert (s.agreement, s.keep_precision, s.keep_recall) == (1.0, 1.0, 1.0)
    assert (s.boundary_precision, s.boundary_recall) == (1.0, 1.0)
    assert all(c.precision in (1.0, None) and c.recall in (1.0, None) for c in s.classes)


def test_keep_all_has_no_drops_so_precisions_are_none_not_zero():
    s = score(G, keep_all(G))
    assert s.agreement == s.keep_precision == pytest.approx(28 / 40) and s.keep_recall == 1.0
    assert (s.boundary_precision, s.boundary_recall, s.jump_cuts) == (None, 0.0, 0)
    assert all(c.precision is None for c in s.classes)
    assert s.kept_s == 40 and not s.length_in_range


def test_length_in_range():
    assert score(G, P, length_range=(20, 25)).length_in_range
    assert not score(G, P, length_range=(900, 1200)).length_in_range


def day_gold():
    """Hook 0-10 (a keep re-used from 500 s); body keeps 100-110, 115-120, 120.24-125 (same sync,
    a muted censor gap, so no Cut), 140-145. Cuts: 110->115 uncovered, 125->140 covered."""
    k = [SourceRange("A", 500, 505, 0, 5), SourceRange("A", 100, 110, 10, 20),
         SourceRange("A", 115, 120, 20, 25), SourceRange("A", 120.24, 125, 25.24, 30),
         SourceRange("A", 140, 145, 30, 35)]
    yt = OutputCut("1 YOUTUBE", 40, 40, 10, k, [], [Cut(20, 5, False), Cut(30, 15, True)])
    return DayGold("d", "p", ["A", "B"], {"A": 200.0, "B": 50.0}, None, None, yt, None, None, [])


def test_gold_from_a_day_scores_body_keeps_only():
    g = gold_of(day_gold())
    assert g.span == {"A": (100000, 145000)}
    assert g.keeps == {"A": ms((100, 110), (115, 120), (120.24, 125), (140, 145))}


def test_gold_proposal_flags_only_the_uncovered_cut_as_a_jump():
    day = day_gold()
    g = gold_of(day)
    p = gold_proposal(day, g)
    assert p.covered == {"A": ms((120, 120.24), (125, 140))}
    s = score(g, p)
    assert s.jump_cuts == 1 and s.agreement == 1.0 and s.boundary_recall == 1.0


def test_file_span_covers_every_footage_file():
    g = gold_of(day_gold(), "file")
    assert g.span == {"A": (0, 200000), "B": (0, 50000)}
    s = score(g, keep_all(g))
    assert s.span_s == 250 and s.keep_recall == 1.0
    assert s.gold_edges == 8  # A drops 0-100, 110-115, 120-120.24, 125-140, 145-200: 4 starts, 4 ends


def test_parse_proposal_validates_ranges():
    p = parse_proposal({"keeps": {"A": [[5, 10], [0, 5]]}, "covered": {"A": [[10, 12]]}})
    assert p.keeps == {"A": [(0, 10000)]} and p.covered == {"A": [(10000, 12000)]}
    with pytest.raises(ValueError, match="in < out"):
        parse_proposal({"keeps": {"A": [[5, 5]]}})
    with pytest.raises(ValueError, match="'keeps'"):
        parse_proposal({})
