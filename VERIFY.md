# VERIFY

Each feature lists the commands that prove it. A check passes when its command exits 0.
Run them all with `python <verify-loop>/scripts/verify.py run`. Baseline (2026-09-28): 1036 pytest passed / 8 skipped, 558 node passed.

## Cue segmentation and subtitles
- test: `python -m pytest tests/test_align_srt.py tests/test_compare_subtitles.py tests/test_cue_conform.py tests/test_cues_grouping.py tests/test_cues_policy_config.py tests/test_cues_short_tail.py tests/test_cues_space_break.py tests/test_cues_split_dp.py tests/test_subtitle_layout.py tests/test_subtitles.py -q -p no:cacheprovider`
- fail-proof: broke the silence-gap comparison in cues/split.py (gap_ms x1000), test_cues_* went red, reverted

## Audio ingest
- test: `python -m pytest tests/test_audio_decode.py tests/test_audio_windows.py tests/test_denoise_inmemory.py tests/test_phase3_ingest.py tests/test_stitch_fuzzy_seam_text.py tests/test_stitch_seam_window.py tests/test_stitch_subword_coincidence.py tests/test_vfr_conform.py -q -p no:cacheprovider`
- fail-proof: disabled the zero-gap span merge in audio/windows.py, test_audio_windows/test_phase3_ingest went red, reverted

## Engines
- test: `python -m pytest tests/test_engine_base_unload.py tests/test_engine_config_validation.py tests/test_engine_contract_import_direction.py tests/test_engine_unload_order.py tests/test_faster_whisper_path_scoping.py tests/test_faster_whisper_truncation_recovery.py tests/test_faster_whisper_short_span_recovery.py tests/test_hf_whisper_engines.py tests/test_phase4_typhoon.py tests/test_qwen3_asr.py tests/test_self_ensemble.py -q -p no:cacheprovider`
- fail-proof: no-op'd _release() in engines/base.py unload(), test_engine_base_unload went red; also removed gc.collect() and the empty_cache() call, and forced the CUDA check on, test_engine_unload_order went red on each (gc.collect() and empty_cache() removal had stayed green before), reverted

## Reconcile and pipeline
- test: `python -m pytest tests/test_console_safe_print.py tests/test_export_job_layout.py tests/test_improvements_202607.py tests/test_job_resumability.py tests/test_engine_safety_resume_identity.py tests/test_phase1_robustness.py tests/test_phase2_config.py tests/test_phase3_llm_reconcile.py tests/test_pipeline_plan.py tests/test_pipeline_refine.py tests/test_pipeline_run_config_fallbacks.py tests/test_smoke.py tests/test_thai_atoms.py -q -p no:cacheprovider`
- fail-proof: narrowed the candidate set in reconcile.py to engine A only, test_smoke went red, reverted

## Thai cue legality lint
- test: `python -m pytest tests/test_thai_lint.py -q -p no:cacheprovider`
- fail-proof: swapped first/last edge token in thai/lint.py, test_thai_lint went red, reverted

## Eval harness and gate
- test: `python -m pytest tests/test_eval_aggregation.py tests/test_eval_baseline_partitioning.py tests/test_eval_gate.py tests/test_eval_paired.py tests/test_eval_run_schema_migration.py tests/test_metrics_v2.py tests/test_metrics_v3.py tests/test_passage_review.py tests/test_phase6_evalperf.py tests/test_phase7_makegold.py tests/test_phase_a_ci.py -q -p no:cacheprovider`
- fail-proof: made the gate skip the regression test in eval/gate.py, test_eval_gate went red, reverted

## Correction flywheel and finetune
- test: `python -m pytest tests/test_finetune_lora.py tests/test_flywheel_diff_span.py tests/test_learn_from_srt.py tests/test_make_finetune_set.py tests/test_phase5_flywheel.py -q -p no:cacheprovider`
- fail-proof: on flywheel/diff.py, swapped the short-text `and` for `or`, changed `_SPAN_THRESHOLD` to 1, replaced `hi = max(hi, lo + 1)` with `hi = lo`, made every token a correction, and changed the default engine name; test_flywheel_diff_span went red on each (the first three had stayed green under test_phase5_flywheel and test_learn_from_srt). Equivalent mutant left alive: `hi = j2` for `max(hi, j2)`

## CutDeck helper
- test: `python -m pytest tests/test_cutdeck_driver_commands.py tests/test_cutdeck_frame_bounds.py tests/test_cutdeck_helper_restart.py tests/test_cutdeck_helper_v2.py tests/test_cutdeck_live_check.py tests/test_cutdeck_live_premiere.py tests/test_cutdeck_mcp_backend.py tests/test_cutdeck_mode_selection.py tests/test_cutdeck_native_plan_golden.py tests/test_cutdeck_panel_wire.py tests/test_cutdeck_phase0.py tests/test_cutdeck_phase1.py tests/test_cutdeck_phase2.py tests/test_cutdeck_phase4.py tests/test_cutdeck_phase5.py tests/test_cutdeck_phase6.py tests/test_cutdeck_plan_sync_bridge.py tests/test_cutdeck_premiere.py tests/test_cutdeck_preview.py tests/test_cutdeck_sequence_json.py tests/test_cutdeck_sequence_mixdown.py tests/test_cutdeck_stacked_track_e2e.py tests/test_cutdeck_sync_audio.py tests/test_cutdeck_sync_plan.py tests/test_cutdeck_words.py tests/test_cutdeck_xml_audio_extract.py tests/test_cutdeck_xml_bridge.py tests/test_cutdeck_xml_export.py tests/test_cutdeck_xml_recut.py tests/test_cutdeck_xml_recut_cli.py -q -p no:cacheprovider`
- fail-proof: stopped percent-encoding the file URL in cutdeck/xml_export.py, xml_export/bridge tests went red, reverted
- fail-proof: the driver-command tests (test_cutdeck_live_premiere.py, offline mode) went red when the panel stopped offering distribute_clips, when the empty-selection refusal was removed, and when read_sequence returned nothing; cutdeck/live_check.py's tests went red when it stopped at the wrong step, dropped the missing-command stop, lost the panel hint, or always exited 0, or counted the panel's all-clips fallback as a selection (that last one was a real bug found in the live run); reverted

## Premiere project readers
- test: `python -m pytest tests/test_prproj_anchor_check.py tests/test_prproj_pixels.py tests/test_prproj_reader.py tests/test_scrub_fcpxml.py tests/test_xml_import_ladder.py -q -p no:cacheprovider`
- fail-proof: read u32 big-endian in cutdeck/prproj_reader.py, test_prproj_reader went red, reverted

## CutDeck panel (UXP)
- test: `node --test tests/*.cjs`
- test: `node tools/adobe/check-api.mjs`
- fail-proof: changed the track-index guard in uxp/cutdeck/transform/frameBounds.js, cutdeck_frame_bounds.test.cjs went red; also made clip-underneath start exclusive and end inclusive, the frame-finished check accept a first non-zero size or a repeated null, and the playhead start check exclusive, cutdeck_frame_bounds_edges.test.cjs went red on each (the underneath start boundary and the size-stability check had stayed green before), reverted
- fail-proof: stashed the alignPanel.js/panel.js fixes, cutdeck_input_commit.test.cjs went red on both tests (bad frame count stayed in the box; Enter committed twice), restored
- fail-proof: inverted the routesDiffer comparison in uxp/cutdeck/layoutProbe.js, cutdeck_layout_probe.test.cjs went red on the text-probe differ case, reverted

## Topic Cut
- test: `python -m pytest tests/test_cutdeck_topic_layout.py tests/test_cutdeck_topic_speakers.py -q -p no:cacheprovider`
- fail-proof: set BLUE_FRAME_MIN to 0.99 and to 0.05 in cutdeck/topic_layout.py, test_top_edge_mostly_blue_is_clip / test_top_edge_mostly_not_blue_is_studio went red (the first version of the tests stayed green under 0.99 because its edges were 100% blue; fixed before use); in cutdeck/topic_speakers.py, made turns merge across a pause and set the smoothing reach to 0, test_a_pause_starts_a_new_turn_even_for_the_same_speaker and test_smoothing_removes_a_single_outlier went red; reverted, files identical to backup

## Blind spots
- No real run of the pipeline: nothing here transcribes real audio on GPU. `transcribe.pipeline.run` on a real file and `transcribe.eval.harness` on the gold set are manual.
- CutDeck panel checks run against `tests/fakes/premiere.cjs`, not live Premiere; real-host behaviour is only in docs/PREMIERE_FACTS.md.
- Panel fail-proof covers frameBounds only; other panel modules are not mutation-checked.
- Live Premiere is opt-in, not part of `verify.py run`. Before releasing CutDeck: start the helper (`python -m cutdeck.xml_bridge`), open a sequence with In/Out marks and the CutDeck panel, check with `python -m cutdeck.live_check`, then run `python -m pytest tests/test_cutdeck_live_premiere.py --live -m live -v` (add `--live-edit` only if you accept the selected clips being edited). It fails, never skips, if any piece is missing.
- Live run 2026-09-28 (`2 FACEBOOK D1`, nothing selected): 8/8 passed. With nothing selected the four transform/anchor/align/distribute tests only proved the "Select a clip" refusal, so their success path on real clips is still unproven.
- The offline mode of those tests runs the real panel driver against the fake Premiere with nothing selected, so the success path of transform/anchor/align/distribute on a real selection is only proven by the live run.
- One equivalent mutant is left alive in flywheel/diff.py (`hi = j2` for `max(hi, j2)`).
- Topic Cut: the two real-episode tests are opt-in (about 2 minutes together, over the runner's 120 s limit): `TOPIC_CUT_REAL=1 python -m pytest tests/test_cutdeck_topic_layout.py tests/test_cutdeck_topic_speakers.py -q -p no:cacheprovider`. They need the 4.5 GB `HKS Facebook 290969 Full.mp4`; the speaker one also needs speechbrain and a GPU. Run them before changing the layout or speaker modules. Their accuracy floors (layout 93%, speaker host/guest 85% / 15%) come from labels made by eye and a threshold tuned on the same frames, so they are optimistic. The topic-start judgement itself (which host run opens a new topic) is not code and has no check; its answer key is `tests/data/topic_cut_starts_hks290969.json`.
