# FEATURES

What the system has and how each feature is reached. `features.py check` tests every entry
point against the code. Read this before driving or changing the app; run
`python <feature-map>/scripts/features.py check --strict` after any change to a route, control,
shortcut or command. Two processes matter: the Thai transcription pipeline + web editor
(`transcribe/`), and CutDeck (`cutdeck/` helper + `uxp/cutdeck/` Premiere panel).

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
- status: proven @ 2ad7576: TestClient GET `/` returned 200 text/html and GET `/jobs` returned 200 with real job rows; save, export and the four buttons only traced (no browser drive, and save writes the live DB)

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

## CutDeck helper
- what: Local websocket service (ws://127.0.0.1:7891) that runs CutDeck jobs (rough cut, transcribe, sync plan) and relays live-Premiere commands between agents and the panel.
- cli: `python -m cutdeck.xml_bridge` @ cutdeck/xml_bridge.py :: --jobs-dir
- trace: `main` @ cutdeck/xml_bridge.py > `serve` @ cutdeck/xml_bridge.py > `dispatch` @ cutdeck/xml_bridge.py > `_run` @ cutdeck/xml_bridge.py
- effect: job folders under `output/premiere/`, `helper.log`
- verify: CutDeck helper
- status: proven @ 2ad7576 (earlier live run 2026-09-28, per VERIFY.md): helper live-proven in Premiere; not restarted in this session

## Rough cut
- what: Find silence and filler in the active Premiere sequence and cut them out of a copy of the sequence, natively in Premiere.
- click: `#cut` @ uxp/cutdeck/index.html
- click: `#resume` @ uxp/cutdeck/index.html
- click: `#pill-speech` @ uxp/cutdeck/index.html
- click: `#pill-silence` @ uxp/cutdeck/index.html
- cli: `python -m cutdeck.xml_recut <sequence.xml>` @ cutdeck/xml_recut.py :: --dry-run
- trace: `bindPrimaryActions` @ uxp/cutdeck/core/panel.js > `onCut` @ uxp/cutdeck/main.js > `onCut` @ uxp/cutdeck/features/roughCut.js > `doCut` @ uxp/cutdeck/features/roughCut.js > `nativeCut` @ uxp/cutdeck/features/roughCut.js
- needs: helper running; the active sequence open in Premiere
- effect: a new sequence `<name> — CutDeck <id>`; the original is untouched
- verify: CutDeck panel (UXP)
- status: traced: read doCut/nativeCut and the helper's prepare/submit_rough_cut/_run; live Premiere run of the cut itself not repeated this session

## Sync sequence
- what: Match every clip by its own audio and lay them on their own tracks in a copy named `<sequence>_Synced`.
- click: `#sync` @ uxp/cutdeck/index.html
- trace: `bindPrimaryActions` @ uxp/cutdeck/core/panel.js > `onSync` @ uxp/cutdeck/main.js > `onSync` @ uxp/cutdeck/features/sync.js > `doSync` @ uxp/cutdeck/features/sync.js > `syncSequence` @ uxp/cutdeck/timeline/nativeSync.js
- effect: `<sequence>_Synced` copy; helper `plan_sync` job
- verify: CutDeck panel (UXP)
- status: traced: read doSync; not run live this session

## Topic Cut (partly built)
- what: Split a finished host-and-guests recording (live news) into one clip per topic, each starting where the host asks a new question. Today: markers at the topic starts on a duplicate sequence; no razor cuts and no panel button yet.
- cli: `python -m cutdeck.premiere_cli add_markers <markers.json>` @ cutdeck/premiere_cli.py :: add_markers
- trace: `main` @ cutdeck/premiere_cli.py > `premiere` @ cutdeck/ai_backend.py > `_ask` @ cutdeck/ai_backend.py
- needs: helper running and the CutDeck panel open on the duplicate sequence; a markers.json of `{start_s, name, comment}` built from the transcript (the topic judgement is done by reading it, not by code)
- effect: Comment markers on the active sequence, one undo step
- note: building blocks with no entry point of their own yet: `classify_frame` @ cutdeck/topic_layout.py (clip or studio layout), `host_turns` @ cutdeck/topic_speakers.py (host or guest voice). Design and findings: docs/DESIGN_TOPIC_CUT.md; answer key: tests/data/topic_cut_starts_hks290969.json
- verify: Topic Cut
- status: proven @ c279d6b: ran add_markers live on "Footages Copy 01" (31 markers, 1 undo step) and the Topic Cut tests, both with the real episode; the panel button, razor cuts and the topic judge do not exist

## Adjustment layer, matte and freeze frame
- what: Add an adjustment layer, colour matte or frame hold to the timeline (click spans all, Ctrl per clip, Shift every cut; hold: Alt/Shift clones instead of exporting).
- click: `#btn-adj` @ uxp/cutdeck/index.html
- click: `#btn-matte` @ uxp/cutdeck/index.html
- click: `#btn-hold` @ uxp/cutdeck/index.html
- trace: `bindAdjustmentButtons` @ uxp/cutdeck/core/panel.js > `onAdjust` @ uxp/cutdeck/main.js > `createAdjustFeature` @ uxp/cutdeck/features/adjust.js
- verify: CutDeck panel (UXP)
- status: traced: read the three bindings and main.js wiring; not run

## Panel navigation and tools
- what: Switch tabs, open Settings, reload the panel, and run read-only diagnostic probes from the overflow menu.
- click: `#tab-edit` @ uxp/cutdeck/index.html
- click: `#tab-adj` @ uxp/cutdeck/index.html
- click: `#tools-toggle` @ uxp/cutdeck/index.html
- click: `#menu-item-settings` @ uxp/cutdeck/index.html
- click: `#menu-item-reload` @ uxp/cutdeck/index.html
- click: `#copystatus` @ uxp/cutdeck/index.html
- click: `#timingprobe` @ uxp/cutdeck/index.html
- click: `#motionprobe` @ uxp/cutdeck/index.html
- click: `#effectprobe` @ uxp/cutdeck/index.html
- click: `#transformprobe` @ uxp/cutdeck/index.html
- click: `#keyframeprobe` @ uxp/cutdeck/index.html
- click: `#alcreateprobe` @ uxp/cutdeck/index.html
- click: `#syncmovesprobe` @ uxp/cutdeck/index.html
- click: `#nativecutprobe` @ uxp/cutdeck/index.html
- trace: `bindTabs` @ uxp/cutdeck/core/panel.js > `onTab` @ uxp/cutdeck/main.js
- note: `alcreate`, `syncmoves` and `nativecut` probes edit the project (they say so in their tooltips); the others are read-only
- verify: CutDeck panel (UXP)
- status: suspected: entry points found in the markup; only the tab binding read

## Transform panel
- what: Edit selected clips' position, scale, rotation and anchor, set a 9-point anchor, align and distribute clips.
- click: `#align-refresh` @ uxp/cutdeck/index.html
- click: `#align-probe` @ uxp/cutdeck/index.html
- click: `#align-scale-reset` @ uxp/cutdeck/index.html
- click: `#align-rotation-reset` @ uxp/cutdeck/index.html
- click: `#align-copy` @ uxp/cutdeck/index.html
- trace: `alignPanel` @ uxp/cutdeck/main.js > `bind` @ uxp/cutdeck/core/alignPanel.js
- needs: clips selected in Premiere; with none selected these only refuse ("Select a clip")
- verify: CutDeck panel (UXP)
- status: proven @ 2ad7576 for the refusal path only (VERIFY.md live run 2026-09-28); success path on a real selection unproven

## Agent tools (MCP)
- what: Expose CutDeck to agents over MCP stdio: transcribe, rough_cut (from an XML file), `premiere_rough_cut` (the live sequence, no XML: panel read -> `prepare` -> `start`, then `premiere_apply_cuts`), job polling, and the `premiere_*` live commands.
- cli: `python scripts/start_cutdeck_mcp.py` @ scripts/start_cutdeck_mcp.py :: cutdeck.mcp_server
- cli: `python -m cutdeck.mcp_server` @ cutdeck/mcp_server.py :: --port
- trace: `main` @ cutdeck/mcp_server.py > `create_server` @ cutdeck/mcp_server.py > `premiere` @ cutdeck/ai_backend.py > `_ask` @ cutdeck/ai_backend.py
- needs: helper running; the panel open for `premiere_*` tools
- verify: CutDeck helper
- status: traced: read all tool definitions in mcp_server.py and the helper's dispatch; server not started. `premiere_rough_cut` proven against a real helper with a stubbed panel read (tests/test_cutdeck_mcp_backend.py, 2026-10-07); not run against live Premiere

## Live Premiere CLI
- what: Send one live command (status, read_sequence, apply_cuts, add_markers, run_probe, inspect_selection, transform/anchor/align/distribute) to the panel through the helper.
- cli: `python -m cutdeck.premiere_cli <command>` @ cutdeck/premiere_cli.py :: --port
- cli: `python -m cutdeck.live_check` @ cutdeck/live_check.py :: main
- trace: `main` @ cutdeck/premiere_cli.py > `premiere` @ cutdeck/ai_backend.py > `_ask` @ cutdeck/ai_backend.py
- verify: CutDeck helper
- status: proven @ 2ad7576 for `--help` (lists the ten commands); live commands need Premiere + panel and were not run this session

## Read a Premiere project
- what: Print a read-only JSON summary of a `.prproj` (tracks, mute state, clip disable), check anchors, and read pixels.
- cli: `python -m cutdeck.prproj_reader <project>` @ cutdeck/prproj_reader.py :: --sequence
- cli: `python -m cutdeck.prproj_anchor_check` @ cutdeck/prproj_anchor_check.py :: main
- cli: `python -m cutdeck.prproj_pixels` @ cutdeck/prproj_pixels.py :: main
- trace: `main` @ cutdeck/prproj_reader.py
- verify: Premiere project readers
- status: proven @ 2ad7576 for `prproj_reader --help`; not run on a project

## Vendored Adobe samples (not this system)
- what: Adobe's sample OAuth panel and a local UXP split probe. They sit in the repo for reference and are not part of the transcriber or CutDeck runtime.
- route: `/login` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- route: `/callback` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- route: `/getCredentials` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- route: `/getRequestId` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- click: `#runVideo` @ uxp/spike18_split_probe/index.html
- click: `#runAudio` @ uxp/spike18_split_probe/index.html
- click: `#copyLog` @ uxp/spike18_split_probe/index.html
- trace: `login` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- verify: CutDeck panel (UXP)
- status: suspected: found by the scan; not opened and not part of any check

**Not built** (roadmap or reserved, not features):

- No second ASR engine (`passthrough` stands in for engine B), so no agreement signal.
- LLM reconciler tiebreak exists but is off (`reconciler.llm_enabled: false`).
- Speaker diarization: `token.speaker_id` is reserved, always null.
