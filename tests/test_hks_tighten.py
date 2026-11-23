"""4.1 tightening (cutdeck/hks_tighten.py): a pause is cut only where the cut can be hidden."""

from cutdeck import hks_tighten as t

KEEP = [(0.0, 60.0)]
PAUSES = [(10.0, 11.0), (20.0, 21.0), (30.0, 31.0), (40.0, 40.4), (50.0, 51.0)]
LAYOUT = [[0, 15, "clip"], [15, 60, "studio"]]
POINTS = [[30.9, "camera"], [48.0, 53.0, "still"]]


def test_pauses_are_cut_only_under_a_cover_a_camera_change_or_a_still():
    keeps, covers, n = t.tighten(KEEP, PAUSES, LAYOUT, POINTS)
    assert n == {"cover": 1, "camera": 1, "still": 1, "left": 1}  # the 0.4 s pause is pace, not counted
    assert covers == [(10.15, 10.9)]                                 # clip picture: covered later
    cut = lambda a, b: not any(ka <= a and b <= kb for ka, kb in keeps)
    assert cut(10.2, 10.8) and cut(30.2, 30.85) and cut(50.2, 50.8)
    assert not cut(20.2, 20.8)                                       # studio, no camera change: a jump cut, left
    assert not cut(40.1, 40.3)


def test_the_camera_cut_lands_on_the_change():
    keeps, _, _ = t.tighten([(0.0, 60.0)], [(30.0, 31.0)], [[0, 60, "studio"]], [[30.9, "camera"]])
    assert any(abs(a - 30.9) < 1e-9 for a, _ in keeps)  # the next piece starts on the new shot


def test_untightened_closes_only_short_gaps():
    assert t.untightened([(0, 10), (10.5, 20), (25, 30)]) == [(0, 20), (25, 30)]
