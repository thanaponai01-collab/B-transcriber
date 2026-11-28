import json

from tools.purity_review import draw, score

CONFIG = {}


def _items(texts):
    return [{"id": i, "file": f"f{i % 2}.mp4", "start_ms": 0, "end_ms": 3000, "hyp": t, "clip": ""}
            for i, t in enumerate(texts)]


def test_reviewer_agreeing_everywhere_scores_zero_and_passes():
    items = _items(["สวัสดีครับ"] * 20)
    out = score(items, {str(i): {"text": "สวัสดีครับ"} for i in range(20)}, CONFIG)
    assert out["cer"] == 0.0 and out["verdict"] == "pass" and out["reviewed"] == 20


def test_no_speech_cue_counts_every_written_character_as_an_error():
    items = _items(["สวัสดีครับ", "ขอบคุณ"])
    out = score(items, {"0": {"text": "สวัสดีครับ"}, "1": {"text": "", "no_speech": True}}, CONFIG)
    assert out["cer"] == round(len("ขอบคุณ") / len("สวัสดีครับ"), 4)


def test_unreviewed_cues_are_left_out():
    items = _items(["สวัสดีครับ", "ผิดหมดเลย"])
    out = score(items, {"0": {"text": "สวัสดีครับ"}}, CONFIG)
    assert out["reviewed"] == 1 and out["of"] == 2 and out["cer"] == 0.0


def test_mostly_wrong_sample_fails_and_loanword_ticks_are_counted():
    items = _items(["กกกกกกกกกก"] * 20)
    corr = {str(i): {"text": "ขขขขขขขขขข", "thai_loanword": i < 5} for i in range(20)}
    out = score(items, corr, CONFIG)
    assert out["verdict"] == "fail" and out["thai_loanword_share"] == 0.25


def test_sample_draws_only_kept_cues_and_is_reproducible(tmp_path):
    rows = [{"file": "a.mp4", "start_ms": i, "end_ms": i + 1, "text": str(i), "confidence": c}
            for i, c in enumerate([0.99, 0.5, 0.96, 0.95, 0.2])] + [{"file": "b.mp4", "skipped": "gold_overlap"}]
    labels = tmp_path / "l.jsonl"
    labels.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    first = draw(labels, n=10)
    assert sorted(it["hyp"] for it in first) == ["0", "2", "3"]
    assert first == draw(labels, n=10)
