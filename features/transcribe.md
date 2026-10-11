# transcribe features

## Transcribe a file
- what: Turn one audio/video file into timestamped phrase-cue tokens saved in the job database.
- cli: `python -m transcribe.pipeline.run <audio> --config transcribe/config.yaml` @ transcribe/pipeline/run.py :: __main__
- trace: `run_file` @ transcribe/pipeline/run.py > `refine` @ transcribe/pipeline/refine.py > `reconcile` @ transcribe/pipeline/reconcile.py
- needs: GPU + `models/whisper-th-medium-ct2`; writes `transcriber.db`
- effect: rows in `job`, `engine_result`, `token`
- verify: Reconcile and pipeline
- status: traced: read run_file end to end (ingest, run_engines, refine, bulk_create_tokens, phase updates); not run on real audio (VERIFY.md blind spot)

## Transcribe and review
- what: One command: transcribe a file, then open the web editor on the result (optionally review passages, apply a layout profile).
- cli: `python transcribe_file.py <audio>` @ transcribe_file.py :: --no-editor
- trace: `transcribe.pipeline.run` @ transcribe_file.py
- effect: runs the pipeline (as a subprocess of transcribe.pipeline.run), exports SRT, starts the editor on 127.0.0.1:8000
- verify: Audio ingest
- status: proven @ 2ad7576: `--help` lists --no-editor, --review-passages, --layout-profile; not run on audio (ingest is the pipeline's first phase, so its tests are the nearest check)

## Compare and recheck subtitles
- what: Score an exported SRT against a hand-corrected one without running ASR, or re-transcribe chosen windows of a job to recheck them.
- cli: `python -m tools.compare_subtitles <reference> <candidate>` @ tools/compare_subtitles.py :: --output
- cli: `python -m tools.recheck_subtitles --output <file>` @ tools/recheck_subtitles.py :: --plan-only
- trace: `main` @ tools/compare_subtitles.py
- verify: Cue segmentation and subtitles
- status: proven @ 2ad7576: `--help` ran for both; neither run on files

## Engine benchmarks and probes
- what: Time engine A on a file, probe engine B candidates against a reference, and survey the tools/models the project depends on.
- cli: `python -m tools.bench_transcribe <audio>` @ tools/bench_transcribe.py :: --compare-sequential
- cli: `python -m tools.probe_engine_b --audio A --reference R ...` @ tools/probe_engine_b.py :: --engine-a-json
- cli: `python -m tools.engine_sharpener` @ tools/engine_sharpener.py :: --section
- trace: `main` @ tools/bench_transcribe.py
- needs: GPU for bench/probe
- verify: Engines
- status: proven @ 2ad7576: `--help` ran for all three; none run

## Web editor
- what: Load a finished job in the browser, hear the audio, correct token text, save corrections, download SRT/VTT.
- route: `/` @ transcribe/editor/server.py :: root
- route: `/jobs` @ transcribe/editor/server.py :: list_jobs
- route: `/jobs/{job_id}` @ transcribe/editor/server.py :: get_job
- route: `/jobs/{job_id}/audio` @ transcribe/editor/server.py :: get_audio
- route: `/jobs/{job_id}/save` @ transcribe/editor/server.py :: save_corrections
- route: `/jobs/{job_id}/export/srt` @ transcribe/editor/server.py :: export_srt_endpoint
- route: `/jobs/{job_id}/export/vtt` @ transcribe/editor/server.py :: export_vtt_endpoint
- click: `#btn-load` @ transcribe/editor/static/index.html
- click: `#btn-save` @ transcribe/editor/static/index.html
- click: `#btn-srt` @ transcribe/editor/static/index.html
- click: `#btn-vtt` @ transcribe/editor/static/index.html
- trace: `saveCorrections` @ transcribe/editor/static/index.html > `/save` @ transcribe/editor/server.py > `create_correction` @ transcribe/db/store.py
- needs: `uvicorn transcribe.editor.server:app --host 127.0.0.1 --port 8000`, or `transcribe_file.py` starts it
- effect: `correction` rows (repeat saves replace, reverts delete)
- verify: Correction flywheel and finetune
- status: suspected: current behavior not re-proven after source drift; historical proof at commit 2ad7576: TestClient GET `/` returned 200 text/html and GET `/jobs` returned 200 with real job rows; save, export and the four buttons only traced (no browser drive, and save writes the live DB)

## Export a job to SRT/VTT
- what: Write a job's tokens (with corrections applied) to SRT, optionally VTT, next to the source media.
- cli: `python scripts/export_job.py <job_id> [--vtt] [--fps N]` @ scripts/export_job.py :: --vtt
- trace: `main` @ scripts/export_job.py > `write_subtitles` @ transcribe/subtitles/__init__.py
- effect: `.srt` (and `.vtt`) file written
- verify: Reconcile and pipeline
- status: suspected: only the argparse header and imports read; export layout is covered by tests/test_export_job_layout.py

## Eval harness and gate
- what: Run the pipeline over the gold set and score `cer_thai`, `wer_latin` and boundary rates; reject a change that regresses a gated signal.
- cli: `python -m transcribe.eval.harness --config transcribe/config.yaml` @ transcribe/eval/harness.py :: --experiment
- trace: `run_harness` @ transcribe/eval/harness.py > `gate` @ transcribe/eval/gate.py
- needs: gold files from "Build a gold set"; GPU
- effect: `eval_run` rows
- verify: Eval harness and gate
- status: traced: read the CLI block; `--help` ran and printed its options; harness not run on the gold set (manual, VERIFY.md blind spot)

## Review report
- what: Render a self-contained HTML review of a pipeline report, with an export button.
- click: `#export` @ transcribe/review_report.py
- trace: `render_review` @ transcribe/review_report.py
- verify: Eval harness and gate
- status: suspected: found by the scan only; `render_review` not read

## Build a gold set
- what: Draft a hand-correctable transcript for an audio file, then freeze it as gold data the eval harness consumes.
- cli: `draft` @ tools/make_gold.py
- cli: `from-srt` @ tools/make_gold.py
- cli: `freeze` @ tools/make_gold.py
- trace: `main` @ tools/make_gold.py > `freeze` @ tools/make_gold.py > `validate` @ tools/make_gold.py
- effect: `<stem>.draft.json`, then a frozen gold file in the goldenset folder
- verify: Eval harness and gate
- status: traced: read main's subcommands and the function list; `--help` crashes on the system Python 3.13 console (cp1252 cannot print the arrow in a help string), so it was not run

## Build a fine-tune set
- what: Collect audio slices plus corrected text from hand-recut SRTs or DB corrections, and report progress toward the fine-tune threshold.
- cli: `from-srt` @ tools/make_finetune_set.py
- cli: `from-corrections` @ tools/make_finetune_set.py
- cli: `stats` @ tools/make_finetune_set.py
- trace: `main` @ tools/make_finetune_set.py > `ingest_srt` @ tools/make_finetune_set.py > `require_clean` @ tools/make_finetune_set.py
- effect: audio slices and manifest entries; `stats` is read-only
- verify: Correction flywheel and finetune
- status: proven @ 2ad7576: `python -m tools.make_finetune_set --help` listed all three subcommands; none run on data

## Subtitle layout profile
- what: Learn a personal line-break/layout profile from corrected SRTs, then apply it to another SRT without changing cue timing.
- cli: `learn` @ tools/subtitle_layout.py
- cli: `apply` @ tools/subtitle_layout.py
- trace: `main` @ tools/subtitle_layout.py > `fit_profile` @ transcribe/subtitles/layout.py
- effect: a profile JSON (`learn`) or a laid-out SRT (`apply`)
- verify: Thai cue legality lint
- status: proven @ 2ad7576: `--help` listed learn and apply; neither run on files
