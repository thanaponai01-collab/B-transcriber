import re

from transcribe.subtitles import read_subtitles, write_subtitles
from transcribe.subtitles.layout import LayoutProfile, fit_profile, layout_cues


def test_learning_keeps_manual_lines_separate_from_transcription():
    raw = '1\n00:00:00,000 --> 00:00:02,000\nลูกต้องการ\nการดูแลจากเรา\n'
    assert '\n' not in read_subtitles(raw)[0]['text']
    assert '\n' in read_subtitles(raw, preserve_line_breaks=True)[0]['text']
    profile = fit_profile([raw])
    assert profile.training_cues == 1
    assert profile.multiline_cues == 1


def test_layout_preserves_speech_timing_and_bound_thai_units():
    text = 'ผู้หญิงคนนั้นบอกว่าเราควรดูแลลูกให้ดีที่สุด'
    cues = [{'text': text, 'start_ms': 2000, 'end_ms': 4400}]
    result = layout_cues(cues, LayoutProfile(target_line_chars=17, wrap_threshold_chars=20))
    assert '\n' in result[0]['text']
    assert re.sub(r'\s', '', result[0]['text']) == text
    assert 'ผู้หญิงคนนั้น' in result[0]['text']
    assert result[0]['start_ms'] == 2000 and result[0]['end_ms'] == 4400
    assert cues[0]['text'] == text
    assert read_subtitles(write_subtitles(result, 'srt'))[0]['end_ms'] == 4400


def test_existing_manual_layout_is_preserved():
    cue = {'text': 'ลูกต้องการ\nการดูแล', 'start_ms': 0, 'end_ms': 2000}
    assert layout_cues([cue], LayoutProfile())[0] == cue


def test_latin_words_are_not_split():
    cue = {'text': 'OpenAI makes useful tools for transcription', 'start_ms': 0, 'end_ms': 2000}
    result = layout_cues([cue], LayoutProfile(target_line_chars=15, wrap_threshold_chars=20))[0]['text']
    assert '\n' in result
    assert result.replace('\n', ' ') == cue['text']
