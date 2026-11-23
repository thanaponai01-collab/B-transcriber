"""6.1 / 6.2 versions (cutdeck/hks_versions.py): the cut lands under the ceiling, never past it."""

import pytest

from cutdeck import hks_versions as v


def test_the_last_piece_is_trimmed_to_the_target():
    got = v.fit([(0, 100), (200, 260)], hook=25.0, target=179.96, floor=168.0)
    assert got[0] == (0, 100) and got[1] == pytest.approx((200, 254.96))
    assert 25.0 + sum(b - a for a, b in got) == pytest.approx(179.96)


def test_a_body_too_short_for_the_floor_is_refused():
    with pytest.raises(ValueError):
        v.fit([(0, 20)], hook=25.0, target=59.96, floor=56.0)


def test_overlap_counts_each_second_once():
    assert v.overlap([(0, 10), (5, 15)], [(8, 20)]) == 7
