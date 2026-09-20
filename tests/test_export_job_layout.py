import json
import sys
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('export_job', Path(__file__).resolve().parents[1] / 'scripts/export_job.py')
export_job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(export_job)
from transcribe.db import store
from transcribe.subtitles import read_subtitles


def test_export_layout_uses_saved_corrections_and_keeps_timing(tmp_path, monkeypatch):
    audio = tmp_path / 'source.wav'
    audio.write_bytes(b'fixture for hashing only')
    db = tmp_path / 'jobs.db'
    store.init_db(db)
    conn = store.connect(db)
    media = store.create_media(conn, str(audio))
    job = store.create_job(conn, media, 'mock', 'passthrough', 'test')
    store.create_token(conn, job, 0, 'ผิด', 1000, 3000, 'thai', .9, 'a')
    store.create_correction(conn, job, 0, 'ผิด', 'ลูกต้องการการดูแลจากเราอยู่', 'a')
    conn.commit()
    conn.close()
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'profile': {'target_line_chars': 12, 'wrap_threshold_chars': 15}}))
    monkeypatch.setattr(sys, 'argv', ['export_job', str(job), '--db', str(db),
                        '--out-dir', str(tmp_path / 'export'), '--layout-profile', str(profile), '--vtt'])
    export_job.main()
    for ext in ('srt', 'vtt'):
        parsed = read_subtitles((tmp_path / 'export' / f'source.{ext}').read_text(encoding='utf-8'),
                                ext, preserve_line_breaks=True)
        assert parsed[0]['text'].replace('\n', '') == 'ลูกต้องการการดูแลจากเราอยู่'
        assert '\n' in parsed[0]['text']
        assert (parsed[0]['start_ms'], parsed[0]['end_ms']) == (1000, 3000)
