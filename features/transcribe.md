# transcribe features

## Transcribe a file
- what: Turn one audio/video file into timestamped phrase-cue tokens saved in the job database.
- cli: `python -m transcribe.pipeline.run <audio> --config transcribe/config.yaml` @ transcribe/pipeline/run.py
- trace: `run_file` @ transcribe/pipeline/run.py > `refine` > `reconcile`
- needs: GPU + `models/whisper-th-medium-ct2`; writes `transcriber.db` (job, engine_result, token)
- verify: Reconcile and pipeline; traced end to end

## Transcribe service orchestrator
- what: Shared programmatic entry point with DB resolution, sha256 cache, coverage gaps and review flags.
- python: `transcribe(media_path, config=..., ...)` @ transcribe/service.py :: transcribe
- trace: `transcribe` @ transcribe/service.py > `run_file_job` @ transcribe/pipeline/run.py
- verify: Reconcile and pipeline; proven by tests/test_service.py

## Transcribe and review
- what: Transcribe a file and open the web editor on the result.
- cli: `python transcribe_file.py <audio> [--no-editor] [--review-passages] [--layout-profile]`
- trace: `transcribe.pipeline.run` @ transcribe_file.py; starts editor on 127.0.0.1:8000
- verify: Audio ingest; proven by --help

## Web editor
- what: Load finished job in browser, play audio, edit token text, save corrections, export SRT/VTT.
- routes: `/`, `/jobs`, `/jobs/{job_id}`, `/audio`, `/save`, `/export/srt`, `/export/vtt` @ transcribe/editor/server.py
- ui: `#btn-load`, `#btn-save`, `#btn-srt`, `#btn-vtt` @ transcribe/editor/static/index.html
- trace: `saveCorrections` > `/save` > `create_correction` @ transcribe/db/store.py
- verify: Correction flywheel and finetune; TestClient GET / and /jobs return 200

## Export a job to SRT/VTT
- what: Write a job's tokens (with corrections applied) to SRT or VTT next to the media.
- cli: `python scripts/export_job.py <job_id> --fps N [--vtt]` @ scripts/export_job.py (`--fps` required: cues snap to that sequence's frames; the editor's SRT button needs its fps field too)
- trace: `main` > `write_subtitles` @ transcribe/subtitles/__init__.py
- verify: Reconcile and pipeline; covered by tests/test_export_job_layout.py

## Eval harness and gate
- what: Run pipeline over gold set, score cer_thai/wer_latin/boundary rates, reject regressions.
- cli: `python -m transcribe.eval.harness --config transcribe/config.yaml [--experiment]`
- trace: `run_harness` @ transcribe/eval/harness.py > `gate` @ transcribe/eval/gate.py
- verify: Eval harness and gate; writes eval_run rows

## Review report
- what: Render self-contained HTML review of a pipeline report with export button.
- click: `#export` @ transcribe/review_report.py
- trace: `render_review` @ transcribe/review_report.py; verify: Eval harness and gate

## Compare and recheck subtitles
- what: Score exported SRT vs hand-corrected reference, or re-transcribe chosen windows.
- cli: `python -m tools.compare_subtitles <ref> <cand>`, `python -m tools.recheck_subtitles`
- verify: Cue segmentation and subtitles; proven by --help

## Engine benchmarks and probes
- what: Time engine A, probe engine B candidates, survey dependencies.
- cli: `tools.bench_transcribe`, `tools.probe_engine_b`, `tools.engine_sharpener`
- verify: Engines; proven by --help

## Build gold & fine-tune sets
- what: Freeze hand-corrected evaluation data or collect audio slices for fine-tuning.
- cli: `tools.make_gold` (draft, from-srt, freeze); `tools.make_finetune_set` (from-srt, from-corrections, stats)
- verify: Eval harness and gate / Correction flywheel; proven by --help

## SRT round trip in Premiere
- what: Write frame-rate stress SRTs, then read the placed captions back from Premiere and compare frame by frame.
- cli: `python -m tools.srt_roundtrip` (make, check) @ tools/srt_roundtrip.py
- verify: tests/test_srt_roundtrip.py (comparison logic); the live run is manual

## Subtitle layout profile
- what: Learn personal line-break layout profile from corrected SRTs and apply to new SRTs.
- cli: `python -m tools.subtitle_layout` (learn, apply --fps N) @ tools/subtitle_layout.py
- verify: Thai cue legality lint; proven by --help
