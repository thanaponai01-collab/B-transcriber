"""Timing judge scorer on synthetic edges (transcribe/eval/judge)."""
import json

import pytest

from transcribe.eval.judge import praat, score


def _ref(onsets, offsets, span=(0, 10000)):
    return {"clip": "c", "span_ms": list(span), "onset": onsets, "offset": offsets}


def test_match_is_nearest_one_to_one():
    assert score.match([1000, 1040], [1030]) == [None, 1030]
    assert score.match([1000], [1600]) == [None]  # beyond MATCH_MS: a miss, not dropped


def test_misses_stay_in_the_denominator():
    words = [{"start_ms": 1010, "end_ms": 1500}]
    rows = score.edge_rows(_ref([1000, 5000], [1500]), words, [], fps=30)
    s = score.summarize(rows)
    assert s["start"]["n"] == 2 and s["start"]["missed"] == 1 and s["start"]["w1"] == 0.5
    assert s["end"]["w1"] == 1.0


def test_frames_at_the_clip_fps():
    words = [{"start_ms": 1050, "end_ms": 2000}]  # 1.5 frames late at 30 fps, 2.5 frames at 50 fps
    s30 = score.summarize(score.edge_rows(_ref([1000], []), words, [], fps=30))
    s50 = score.summarize(score.edge_rows(_ref([1000], []), words, [], fps=50))
    assert (s30["start"]["w1"], s30["start"]["w2"]) == (0.0, 1.0)
    assert (s50["start"]["w1"], s50["start"]["w2"]) == (0.0, 0.0)


def test_one_frame_means_one_frame_duration():
    words = [{"start_ms": 1055, "end_ms": 2000}]  # 55 ms late; snapped to frame 32 (1066 ms) still late
    s = score.summarize(score.edge_rows(_ref([1000], []), words, [], fps=30))
    assert s["start"]["w1"] == 0.0 and s["start"]["placed_w1"] == 0.0


def test_premiere_floor_to_30fps():
    assert score.premiere_ms(1066) == pytest.approx(1033.333, abs=0.01)
    words = [{"start_ms": 1030, "end_ms": 2000}]  # ref 1033: floored to 1000 ms, still within a frame
    s = score.summarize(score.edge_rows(_ref([1033], []), words, [], fps=30))
    assert s["start"]["w1"] == 1.0 and s["start"]["premiere_w1"] == 1.0
    words = [{"start_ms": 1060, "end_ms": 2000}]  # ref 1066: floored to 1033 ms, 33 ms early: a hit
    s = score.summarize(score.edge_rows(_ref([1090], []), words, [], fps=30))
    assert s["start"]["w1"] == 1.0 and s["start"]["premiere_w1"] == 0.0


def test_paired_delta_counts_moved_edges():
    a = score.edge_rows(_ref([1000, 3000], []), [{"start_ms": 1200, "end_ms": 1300}, {"start_ms": 3000, "end_ms": 3100}], [], 30)
    b = score.edge_rows(_ref([1000, 3000], []), [{"start_ms": 1000, "end_ms": 1300}, {"start_ms": 3000, "end_ms": 3100}], [], 30)
    d = score.paired_delta(a, b, k=1, iters=200)
    assert d["delta"] == 0.5 and d["edges_better_1f"] == 1 and d["edges_worse_1f"] == 0
    assert d["clips"] == 1 and d["ci95"] == [0.5, 0.5]  # one clip: the clip bootstrap cannot vary


def test_read_points_from_praat_text_grid():
    tg = praat.textgrid(5.0, 1.0, 4.0).replace(
        'name = "onset"\n        xmin = 0\n        xmax = 5.000\n        points: size = 0\n',
        'name = "onset"\n        xmin = 0\n        xmax = 5.000\n        points: size = 2\n'
        '        points [1]:\n            number = 2.5\n            mark = ""\n'
        '        points [2]:\n            number = 1.25\n            mark = ""\n')
    assert praat.read_points(tg) == {"onset": [1.25, 2.5], "offset": []}


def test_lock_refuses_a_changed_file(tmp_path, monkeypatch):
    f = tmp_path / "x.json"
    f.write_text("{}")
    monkeypatch.setattr(score, "locked_files", lambda m: {"x": score._sha(f)})
    monkeypatch.setattr(score, "LOCK", tmp_path / "judge.lock")
    (tmp_path / "judge.lock").write_text(json.dumps({"x": score._sha(f)}))
    score.check_lock({})
    f.write_text('{"moved": 1}')
    with pytest.raises(SystemExit, match="mismatch"):
        score.check_lock({})
