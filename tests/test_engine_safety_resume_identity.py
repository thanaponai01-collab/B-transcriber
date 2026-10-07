"""Failure cleanup and conservative resume identity; no ASR models required."""
import copy
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from transcribe.db import store
from transcribe.pipeline import engine_run, plan


class EngineFailureCleanupTests(unittest.TestCase):
    def test_all_engine_failure_paths_unload_and_preserve_error(self):
        # Cover initial A, real B, and resumed/fresh self-ensemble passes.
        cases = [('a', 'load'), ('a', 'decode'), ('b', 'load'), ('b', 'decode'),
                 ('ensemble', 'load'), ('ensemble', 'decode'),
                 ('resume', 'load'), ('resume', 'decode')]
        for route, failure_at in cases:
            with self.subTest(route=route, failure_at=failure_at):
                error = RuntimeError('inference failed')
                cfg = {'engine_a': 'mock', 'engine_b': 'passthrough'}
                job_plan = plan.make_plan(cfg, None)
                job_plan = SimpleNamespace(**vars(job_plan))
                job_plan.self_ensemble_enabled = route in ('ensemble', 'resume')
                job_plan.skip_engine_a = route == 'resume'
                engine = Mock()
                original_path = os.environ.get('PATH', '')

                def load():
                    os.environ['PATH'] = 'test CUDA path'
                    if failure_at == 'load':
                        raise error

                def unload():
                    os.environ['PATH'] = original_path

                engine.load.side_effect = load
                engine.unload.side_effect = unload
                inputs = engine_run.DecodeInputs([], None, [], {})
                cached = SimpleNamespace(tokens_json='[]', timestamps_final=True)
                with patch.object(engine_run, 'build_engine', return_value=engine), \
                     patch.object(engine_run, '_log_vram'), \
                     patch.object(engine_run, '_free_vram'), \
                     patch.object(engine_run, '_transcribe_with',
                                  side_effect=error if route in ('a', 'b') else None,
                                  return_value=([], True, None)), \
                     patch.object(engine_run, '_decode_self_ensemble_b', side_effect=error), \
                     patch.object(store, 'get_engine_result', return_value=cached), \
                     patch.object(store, 'save_engine_result') as save, \
                     patch.object(store, 'update_job_phase') as advance:
                    with self.assertRaises(RuntimeError) as raised:
                        if route == 'b':
                            engine_run._run_engine_b(None, 1, job_plan, inputs,
                                                     'cpu', cfg, True, None, None)
                        else:
                            engine_run._run_engine_a(None, 1, job_plan, inputs, 'cpu', cfg)
                    self.assertIs(raised.exception, error)
                    engine.unload.assert_called_once()
                    self.assertEqual(os.environ['PATH'], original_path)
                    save.assert_not_called()
                    advance.assert_not_called()

    def test_success_unloads_before_persisting(self):
        events = []
        engine = Mock()
        engine.load.side_effect = lambda: events.append('load')
        engine.unload.side_effect = lambda: events.append('unload')
        cfg = {'engine_a': 'mock', 'engine_b': 'passthrough'}
        with patch.object(engine_run, 'build_engine', return_value=engine), \
             patch.object(engine_run, '_log_vram'), \
             patch.object(engine_run, '_free_vram'), \
             patch.object(engine_run, '_transcribe_with', return_value=([], True, None)), \
             patch.object(store, 'save_engine_result', side_effect=lambda *a: events.append('save')), \
             patch.object(store, 'update_job_phase', side_effect=lambda *a: events.append('advance')):
            engine_run._run_engine_a(None, 1, plan.make_plan(cfg, None),
                                     engine_run.DecodeInputs([], None, [], {}), 'cpu', cfg)
        self.assertEqual(events, ['load', 'unload', 'save', 'advance'])


class ResumeFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {'engine_a': 'mock', 'engine_b': 'passthrough',
                    'engines': {'mock': {'model_id': 'checkpoint-a', 'beam_size': 5}},
                    'vad_threshold': 0.35}

    def test_mapping_order_does_not_change_identity(self):
        reordered = dict(reversed(list(self.cfg.items())))
        self.assertEqual(plan.resume_fingerprint(self.cfg, ['AI'], {'AI': 1.0}),
                         plan.resume_fingerprint(reordered, ['AI'], {'AI': 1.0}))

    def test_decode_and_bias_changes_invalidate_identity(self):
        baseline = plan.resume_fingerprint(self.cfg, ['AI'], {'AI': 1.0})
        variants = []
        for key, value in [('model_id', 'checkpoint-b'), ('beam_size', 1)]:
            cfg = copy.deepcopy(self.cfg)
            cfg['engines']['mock'][key] = value
            variants.append((cfg, ['AI'], {'AI': 1.0}))
        cfg = copy.deepcopy(self.cfg)
        cfg['vad_threshold'] = 0.5
        variants.extend([(cfg, ['AI'], {'AI': 1.0}),
                         (self.cfg, ['API'], {'API': 1.0}),
                         (self.cfg, ['AI'], {'AI': 2.0})])
        for args in variants:
            with self.subTest(args=args):
                self.assertNotEqual(baseline, plan.resume_fingerprint(*args))

    def test_prompt_term_order_is_part_of_identity(self):
        self.assertNotEqual(plan.resume_fingerprint(self.cfg, ['AI', 'API'], {}),
                            plan.resume_fingerprint(self.cfg, ['API', 'AI'], {}))

    def test_database_matches_only_same_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'test.db'
            media = Path(tmp) / 'audio.wav'
            media.write_bytes(b'test')
            store.init_db(db)
            conn = store.connect(db)
            try:
                media_id = store.create_media(conn, str(media))
                legacy = store.create_job(conn, media_id, 'mock', 'passthrough', 'v')
                store.update_job_status(conn, legacy, 'failed')
                lookup = lambda fingerprint: store.find_resumable_job(
                    conn, media_id, 'mock', 'passthrough', 'v', fingerprint)
                self.assertIsNone(lookup('current'))
                self.assertEqual(lookup(None).id, legacy)
                job = store.create_job(conn, media_id, 'mock', 'passthrough', 'v', 'current')
                for status in ('failed', 'running'):
                    store.update_job_status(conn, job, status)
                    self.assertEqual(lookup('current').id, job)
                    self.assertIsNone(lookup('changed'))
                store.update_job_status(conn, job, 'done')
                self.assertIsNone(lookup('current'))
            finally:
                conn.close()

    def test_pipeline_resumes_same_inputs_and_restarts_changed_inputs(self):
        from transcribe.pipeline import run
        for change in ('config', 'term', 'weight'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                db = Path(tmp) / 'pipeline.db'
                media = Path(tmp) / 'audio.wav'
                media.write_bytes(b'test media')
                cfg = {'engine_a': 'mock', 'engine_b': 'passthrough', 'vad_threshold': 0.35}
                ingested = SimpleNamespace(chunks=[], spans=[], audio=None, sample_rate=16000)
                with patch.object(run, '_ingest_for_plan', return_value=ingested), \
                     patch.object(run.refine, 'refine', return_value=[]):
                    run.run_file(str(media), cfg, db)
                    conn = store.connect(db)
                    try:
                        first = store.list_jobs(conn)[0]
                        store.update_job_status(conn, first.id, 'failed')
                        # The cached A/B outputs and written phase can be reused.
                        run.run_file(str(media), dict(reversed(list(cfg.items()))), db)
                        self.assertEqual(len(store.list_jobs(conn)), 1)
                        store.update_job_status(conn, first.id, 'failed')
                        if change == 'config':
                            cfg['vad_threshold'] = 0.5
                        else:
                            store.upsert_bias_term(conn, 'AI', 'technical', 'latin', 'manual', 1.0)
                            if change == 'weight':
                                run.run_file(str(media), cfg, db)
                                latest = max(store.list_jobs(conn), key=lambda job: job.id)
                                store.update_job_status(conn, latest.id, 'failed')
                                store.upsert_bias_term(conn, 'AI', 'technical', 'latin', 'manual', 2.0)
                        before = len(store.list_jobs(conn))
                        run.run_file(str(media), cfg, db)
                        jobs = store.list_jobs(conn)
                        self.assertEqual(len(jobs), before + 1)
                        latest = max(jobs, key=lambda job: job.id)
                        self.assertEqual(latest.status, 'done')
                        self.assertNotEqual(latest.resume_fingerprint, first.resume_fingerprint)
                    finally:
                        conn.close()

    def test_legacy_database_migrates_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'legacy.db'
            conn = sqlite3.connect(db)
            schema = store._SCHEMA.read_text(encoding='utf-8')
            schema = schema.replace('job_phase        TEXT,', 'job_phase        TEXT')
            schema = schema.replace('    resume_fingerprint TEXT\n', '')
            conn.executescript(schema)
            conn.close()
            store.init_db(db)
            store.init_db(db)
            conn = store.connect(db)
            try:
                columns = [r['name'] for r in conn.execute('PRAGMA table_info(job)')]
                self.assertEqual(columns.count('resume_fingerprint'), 1)
            finally:
                conn.close()


if __name__ == '__main__':
    unittest.main()
