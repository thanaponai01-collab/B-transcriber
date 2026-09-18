import pytest

from tools.compare_subtitles import compare


def test_wrapping_is_not_a_recognition_error():
    reference = '1\n00:00:00,000 --> 00:00:01,000\nลูกต้องการ\nการดูแล\n'
    candidate = '1\n00:00:00,000 --> 00:00:01,000\nลูกต้องการการดูแล\n'
    report = compare(reference, candidate)
    assert report['metrics']['cer_thai'] == 0
    assert report['reference']['multiline_cues'] == 1
    assert report['candidate']['multiline_cues'] == 0


def test_missing_speech_and_flash_caption_are_separate_signals():
    reference = '1\n00:00:00,000 --> 00:00:01,000\nลูกต้องการการดูแล\n'
    candidate = '1\n00:00:00,000 --> 00:00:00,240\nลูก\n'
    report = compare(reference, candidate)
    assert report['metrics']['cer_thai'] > 0
    assert report['candidate']['under_500ms'][0]['duration_ms'] == 240


def test_empty_reference_is_rejected():
    with pytest.raises(ValueError):
        compare('', '1\n00:00:00,000 --> 00:00:01,000\nลูก\n')
