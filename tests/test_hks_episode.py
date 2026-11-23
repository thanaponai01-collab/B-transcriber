"""episode.json (cutdeck/hks_episode.py): sections replace only themselves; step 2.3's check on
the real day folders when the G: drive is mounted."""

from pathlib import Path

import pytest

import cutdeck.hks_audit as audit
from cutdeck import hks_episode as ep

DAY = Path(r"G:\Me\Works\20261120 - โหนกระแส")


def test_a_section_write_replaces_only_that_section(tmp_path):
    ep.update("20261120", "a.mp4", "clock", [[0, 5]], tmp_path)
    ep.update("20261120", "b.mp4", "clock", [[1, 2]], tmp_path)
    ep.update("20261120", "a.mp4", "tv_part", [0, 5], tmp_path)
    ep.update("20261120", "a.mp4", "clock", [[0, 7]], tmp_path)
    files = ep.load("20261120", tmp_path)["files"]
    assert files == {"a.mp4": {"clock": [[0, 7]], "tv_part": [0, 5]}, "b.mp4": {"clock": [[1, 2]]}}
    assert ep.load("20261121", tmp_path) == {"day": "20261121", "files": {}}


def test_clock_spans_are_half_open_runs():
    assert ep.spans([0, 1, 1, 0, 1]) == [[1, 3], [4, 5]]
    assert ep.inside([[1, 3]], 2.9) and not ep.inside([[1, 3]], 3)


@pytest.mark.skipif(not DAY.exists(), reason="needs the G: day folders")
def test_20261120_clock_check_passes_and_fails_without_the_blur(tmp_path, monkeypatch):
    ep.clock_day(DAY, out=tmp_path)
    assert ep.check_day(DAY, tmp_path) == []
    real = audit.layers
    monkeypatch.setattr(audit, "layers", lambda seq, footage: [
        audit.Layer(l.track, l.start, l.end, l.kind, l.media, l.path, l.source_in, l.framing, False, l.hold_at)
        for l in real(seq, footage)])
    assert len(ep.unblurred_clock(DAY, ep.load("20261120", tmp_path))) > 600
