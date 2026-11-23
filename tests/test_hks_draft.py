"""Phase 4 draft (cutdeck/hks_draft.py): the cut judge's spans become keeps."""

import json

from cutdeck import hks_draft, hks_judge


def test_spans_with_no_cut_line_between_them_are_one_keep(tmp_path):
    folder = tmp_path / "20990101 - x"
    lines = [["L0001", 0.0, 1.0, "a"], ["L0002", 1.2, 2.0, "b"], ["L0003", 2.5, 3.0, "c"],
             ["L0004", 3.1, 4.0, "d"]]
    hks_judge.lines_path(folder, "cut", tmp_path).parent.mkdir(parents=True)
    hks_judge.lines_path(folder, "cut", tmp_path).write_text(json.dumps({"a.mp4": lines}))
    hks_judge.paths(folder, "cut", tmp_path)[1].write_text(json.dumps({"spans": [
        {"from": "L0001", "to": "L0001"}, {"from": "L0002", "to": "L0002"}, {"from": "L0004", "to": "L0004"}]}))
    assert hks_draft.judge_keeps(folder, tmp_path) == {"a.mp4": [(0.0, 2.0), (3.1, 4.0)]}
