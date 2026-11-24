import json
import zipfile

import pytest

from cutdeck import mogrt_text


def _template(path):
    definition = {
        "capsuleID": "old-id",
        "clientControls": [
            {"type": 6, "uiName": {"strDB": [{"localeString": "en_US", "str": "Title"}]},
             "value": {"strDB": [{"localeString": "en_US", "str": "Old"}, {"localeString": "th_TH", "str": "เก่า"}]}},
            {"type": 2, "uiName": {"strDB": [{"localeString": "en_US", "str": "Color"}]}},
            {"type": 6, "uiName": {"strDB": [{"localeString": "en_US", "str": "Sub"}]},
             "value": {"strDB": [{"localeString": "en_US", "str": "Keep"}]}},
        ],
        "sourceInfoLocalized": {"en_US": {"capsuleparams": {"capParams": [
            {"capPropUIName": "Title", "capPropDefault": "Old"}, {"capPropUIName": "Sub", "capPropDefault": "Keep"}]}}},
    }
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("definition.json", json.dumps(definition))
        z.writestr("project.aegraphic", b"\x00binary")
    return path


def test_bake_sets_text_everywhere_and_a_new_capsule_id(tmp_path):
    src = _template(tmp_path / "t.mogrt")
    out = mogrt_text.bake(src, {"Title": "สวัสดี"})
    with zipfile.ZipFile(out) as z:
        d = json.loads(z.read("definition.json"))
        assert z.read("project.aegraphic") == b"\x00binary"
    assert [s["str"] for s in d["clientControls"][0]["value"]["strDB"]] == ["สวัสดี", "สวัสดี"]
    assert d["clientControls"][2]["value"]["strDB"][0]["str"] == "Keep"
    params = d["sourceInfoLocalized"]["en_US"]["capsuleparams"]["capParams"]
    assert [p["capPropDefault"] for p in params] == ["สวัสดี", "Keep"]
    assert d["capsuleID"] != "old-id"  # Premiere re-places its cached original otherwise


def test_bake_by_index_counts_text_controls_only(tmp_path):
    out = mogrt_text.bake(_template(tmp_path / "t.mogrt"), {"1": "New sub"})
    assert [c["text"] for c in mogrt_text.text_controls(out)] == ["Old", "New sub"]


def test_unknown_text_lists_the_templates_texts(tmp_path):
    with pytest.raises(ValueError, match='0 "Title", 1 "Sub"'):
        mogrt_text.bake(_template(tmp_path / "t.mogrt"), {"Nope": "x"})


def test_bake_deletes_copies_older_than_a_week_and_keeps_recent_ones(tmp_path, monkeypatch):
    import os, time
    monkeypatch.setattr(mogrt_text.tempfile, "gettempdir", lambda: str(tmp_path))
    bake_dir = tmp_path / "cutdeck-mogrt"
    bake_dir.mkdir()
    old, recent = bake_dir / "old.mogrt", bake_dir / "recent.mogrt"
    for f, age_days in ((old, 8), (recent, 6)):
        f.write_bytes(b"x")
        t = time.time() - age_days * 86400
        os.utime(f, (t, t))
    out = mogrt_text.bake(_template(tmp_path / "t.mogrt"), {"Title": "x"})
    assert not old.exists() and recent.exists() and out.exists()
