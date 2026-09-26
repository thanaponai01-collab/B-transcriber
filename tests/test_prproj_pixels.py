"""prproj_pixels turns saved normalized Position/Anchor back into the pixels Effect Controls shows."""

import pytest

from cutdeck.prproj_pixels import clip_rows
from cutdeck.prproj_reader import read_project
from tests.test_prproj_reader import REAL


@pytest.mark.skipif(not REAL.exists(), reason="probe.prproj not present")
def test_pixels_match_what_was_typed_into_effect_controls():
    seq = next(s for s in read_project(REAL)["sequences"] if s["name"] == "Sequence 04")
    assert seq["frame"] == [1920, 1080]
    rows = clip_rows(seq)
    # Motion on a 1280x720 source in a 1920x1080 sequence: typed 100,200 into both fields.
    assert rows[0][4:] == ("100, 200", "100, 200")
    assert rows[1][4:] == ("100, 200 (keyframed)", "100, 200")
    # Untouched default Text layer sits at the sequence centre.
    assert rows[3][4:] == ("960, 540", "0, 0")
