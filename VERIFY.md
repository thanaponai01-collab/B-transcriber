include: .drive/preset-selection/VERIFY.md
# VERIFY

include: verification/rough-cut.md

Foundation scope (2026-10-11): selected SubtitleDesk backend checks run from the Git
root E:/Me/5.Claude/Transcriber_v2 using `python` (observed Python 3.13.4).
The TestClient recipe owns temporary directories; no live launch/readiness/cleanup
is required. Helper and extractor are fakes; real extraction/ASR remain blind spots.
Use installed verify-loop/scripts/verify.py with this repo argument and
`--only "SubtitleDesk quote workspace" --strict` for the selected recipe.
A filtered strict pass does not update whole-repository status. Selected proof is
retained in `.verify-evidence/subtitle_desk-foundation/.verify-state.json`; see
[foundation evidence](verification/foundation.md) for its isolation and limits. Historical baseline
and rejection descriptions below are retained, not current proof.

Each feature lists the commands that prove it. A check passes when its command exits 0.
Run them all with `python <verify-loop>/scripts/verify.py run`. Baseline (2026-09-28): 1036 pytest passed / 8 skipped, 558 node passed.

## Cue segmentation and subtitles
- test: `python -m pytest tests/test_align_srt.py tests/test_compare_subtitles.py tests/test_cue_conform.py tests/test_cues_grouping.py tests/test_cues_policy_config.py tests/test_cues_short_tail.py tests/test_cues_space_break.py tests/test_cues_split_dp.py tests/test_subtitle_layout.py tests/test_subtitles.py tests/test_srt_roundtrip.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: broke the silence-gap comparison in cues/split.py (gap_ms x1000), test_cues_* went red, reverted
- fail-proof (2026-10-22, frame-exact SRT): in subtitles.frame_cues, wrote the nearest ms instead of the floor, dropped the one-frame minimum, dropped the sub-frame gap close, and dropped the overlap guard; test_subtitles went red on each, reverted

## Audio ingest
- test: `python -m pytest tests/test_audio_decode.py tests/test_audio_windows.py tests/test_denoise_inmemory.py tests/test_phase3_ingest.py tests/test_stitch_fuzzy_seam_text.py tests/test_stitch_seam_window.py tests/test_stitch_subword_coincidence.py tests/test_audio_windows_speech_spans.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: disabled the zero-gap span merge in audio/windows.py, test_audio_windows/test_phase3_ingest went red, reverted

## Engines
- test: `python -m pytest tests/test_engine_base_unload.py tests/test_engine_config_validation.py tests/test_engine_contract_import_direction.py tests/test_engine_unload_order.py tests/test_faster_whisper.py tests/test_faster_whisper_path_scoping.py tests/test_faster_whisper_truncation_recovery.py tests/test_faster_whisper_short_span_recovery.py tests/test_hf_whisper_engines.py tests/test_phase4_typhoon.py tests/test_qwen3_asr.py tests/test_self_ensemble.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: no-op'd _release() in engines/base.py unload(), test_engine_base_unload went red; also removed gc.collect() and the empty_cache() call, and forced the CUDA check on, test_engine_unload_order went red on each (gc.collect() and empty_cache() removal had stayed green before), reverted

## Reconcile and pipeline
- test: `python -m pytest tests/test_console_safe_print.py tests/test_export_job_layout.py tests/test_improvements_202607.py tests/test_job_resumability.py tests/test_engine_safety_resume_identity.py tests/test_phase1_robustness.py tests/test_phase2_config.py tests/test_phase3_llm_reconcile.py tests/test_pipeline_plan.py tests/test_pipeline_refine.py tests/test_pipeline_run_config_fallbacks.py tests/test_smoke.py tests/test_thai_atoms.py tests/test_coverage_guard.py tests/test_review.py tests/test_service.py tests/test_system_spec_sync.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: narrowed the candidate set in reconcile.py to engine A only, test_smoke went red, reverted

## Word-start alignment (word_align)
- test: `python -m pytest tests/test_word_align.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: dropped the never-go-backwards clamp in word_align.retime_starts, test_starts_never_go_backwards_and_a_word_keeps_one_ms went red, reverted
- fail-proof: dropped the music-bed gate in word_align.snap_to_sound, test_no_snap_where_the_sound_never_drops_into_a_real_pause went red, reverted
- live (GPU, manual): `python -m transcribe.eval.timing <clean speech .wav ...>` reports word and cue starts against the audio's own onsets; on 5 three-minute clean clips (2026-11-24) word starts within one 25 fps frame went 42% → 72% (60 onsets), cue starts 44% → 71%
- replay (GPU, manual): `python -m transcribe.eval.timing --manifest transcribe/eval/timing_clips.json --cache output/timing` cuts the 14 clips of the manifest, runs Engine A once per clip into the cache, then re-aligns and scores per set (about 30 s once cached). 2026-11-24 with snap_to_sound, heldout (128 onsets): word starts within one frame 46% (Whisper) → 91%, p90 |err| 20 ms; cue starts 43% → 92%. The snap and the ruler read the same waveform, so this number is not independent: judge snap changes also by eye on moved starts the ruler cannot see, and by the gold gate (cue_BER 0.3214, unchanged). (Before the ends work, word_end lines meant nothing on gated OBS audio: the 'offset' was the noise gate closing. The offset ruler now ignores digital silence.)
- fail-proof: let snap_to_sound walk back past the previous word's start, test_the_second_word_of_a_phrase_keeps_its_start went red, reverted (unbounded, it added 134 one-ms words over the 14 clips)
- speed (2026-11-24, hks_studio clip, 2-3 runs each): alignment adds 3.2-3.5 s to a 3-minute clip (run_file_job 18.0-18.3 s vs 14.8 s without), down from 17.7 s (32.2 s vs 14.5 s); the model is the torchaudio checkpoint models/wav2vec2-th-ctc.pt (export: requirements.txt), loading in 1.4 s instead of 15.7 s, with no transformers import; its words are identical to the Hugging Face model's on all 14 clips
- long file: the 103-minute tiw source runs end to end in 293 s, 0 overlapping cues, no word starting before the previous one
- ends (2026-11-24): fail-proofs, each went red then reverted: no hysteresis in word_align.snap_end_to_sound → test_flickering_room_noise_still_makes_a_pause; a 400 ms limit on the walk back → test_an_anchor_deep_in_the_pause_walks_back_to_the_word_s_end; no tail mode → test_an_anchor_in_room_noise_walks_back_to_the_word_not_on_through_the_noise; the CTC anchor not kept before the next word, or an end past the next word kept → test_a_last_letter_inside_the_next_word_is_kept_before_it_and_an_end_past_it_is_dropped; its pause check → test_no_end_snap_without_a_real_pause; a touching cue's end moving → test_a_cue_followed_by_a_gap_ends_with_its_last_word_and_a_touching_cue_does_not_move; a cue end moving below its start → test_a_gapped_cue_whose_end_moves_far_back_does_not_reach_into_the_previous_cue
- ends live (replay, heldout): word ends before a pause within one 25 fps frame 11% (Whisper) → 72%, |err| median 140 → 20 ms, p90 180 ms (452 offsets); cue ends followed by a gap 24% → 70%. The ruler's offset is where 100 ms of quiet begins, one per pause; quiet is the room's noise + 6 dB or 30 dB under the speech's peak (taken before the fall, not sliding down the tail), whichever is higher; touching cues are not scored. Same caveat as starts: the ruler and the snap read the same waveform, and settings were chosen looking at both sets. Of the ruler's speech ends (tune + heldout, vlog left out), words with no end found went 209 → 67. By eye: tail mode moves ends 1-9 ms along the fall and clipped no soft syllable in 16 samples; the remaining misses with an end found are mostly speech Whisper never transcribed. Hand-cut gold shorts, 5 cue ends before a gap: |err| median 120 → 30 ms. Gold gate unchanged (CER_thai 0.0530, cue_BER 0.3214, 0 overlaps)

## Thai cue legality lint
- test: `python -m pytest tests/test_thai_lint.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: swapped first/last edge token in thai/lint.py, test_thai_lint went red, reverted

## Eval harness and gate
- test: `python -m pytest tests/test_eval_aggregation.py tests/test_eval_baseline_partitioning.py tests/test_eval_gate.py tests/test_eval_paired.py tests/test_eval_run_schema_migration.py tests/test_metrics_v2.py tests/test_metrics_v3.py tests/test_metrics_v4.py tests/test_passage_review.py tests/test_phase6_evalperf.py tests/test_phase7_makegold.py tests/test_phase_a_ci.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: made the gate skip the regression test in eval/gate.py, test_eval_gate went red, reverted

## Correction flywheel and finetune
- test: `python -m pytest tests/test_finetune_lora.py tests/test_flywheel_diff_span.py tests/test_learn_from_srt.py tests/test_make_finetune_set.py tests/test_phase5_flywheel.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: on flywheel/diff.py, swapped the short-text `and` for `or`, changed `_SPAN_THRESHOLD` to 1, replaced `hi = max(hi, lo + 1)` with `hi = lo`, made every token a correction, and changed the default engine name; test_flywheel_diff_span went red on each (the first three had stayed green under test_phase5_flywheel and test_learn_from_srt). Equivalent mutant left alive: `hi = j2` for `max(hi, j2)`

## CutDeck helper
- test: `python -m pytest tests/test_cutdeck_assistant.py tests/test_cutdeck_driver_commands.py tests/test_cutdeck_frame_bounds.py tests/test_cutdeck_helper_restart.py tests/test_cutdeck_helper_v2.py tests/test_cutdeck_live_check.py tests/test_cutdeck_live_premiere.py tests/test_cutdeck_mcp_backend.py tests/test_cutdeck_native_plan_golden.py tests/test_cutdeck_panel_wire.py tests/test_cutdeck_phase0.py tests/test_cutdeck_phase1.py tests/test_cutdeck_phase2.py tests/test_cutdeck_phase4.py tests/test_cutdeck_phase5.py tests/test_cutdeck_phase6.py tests/test_cutdeck_plan_sync_bridge.py tests/test_cutdeck_premiere.py tests/test_cutdeck_preview.py tests/test_cutdeck_sequence_json.py tests/test_cutdeck_sequence_mixdown.py tests/test_cutdeck_stacked_track_e2e.py tests/test_cutdeck_sync_audio.py tests/test_cutdeck_sync_plan.py tests/test_cutdeck_words.py tests/test_cutdeck_audio_extract.py tests/test_cutdeck_helper.py tests/test_cutdeck_rough_cut_cli.py tests/test_cutdeck_rough_cut_retirement.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: the driver-command tests (test_cutdeck_live_premiere.py, offline mode) went red when the panel stopped offering distribute_clips, when the empty-selection refusal was removed, and when read_sequence returned nothing; cutdeck/live_check.py's tests went red when it stopped at the wrong step, dropped the missing-command stop, lost the panel hint, or always exited 0, or counted the panel's all-clips fallback as a selection (that last one was a real bug found in the live run); reverted

- test (2026-11-21, menu and keyboard routes): `python -m pytest tests/test_cutdeck_keys.py -q -p no:cacheprovider`
- fail-proof: each went red on its own and was restored: dropped the Ctrl+Alt-last sort in keys.pick (Ctrl+Alt+Z picked); removed the active-sequence check in run_focused (pressed after a switch); took "close" out of menu.BLOCKED (File > Close Project runnable).

- test (2026-11-23, Premiere command log, #129): `python -m pytest tests/test_cutdeck_command_log.py -q -p no:cacheprovider` (every command through `Jobs.premiere` appends a start and an end record to `<jobs dir>/premiere_commands.jsonl`: args, hint, time with offset, the result of a write or the size of a read, the error of a failure; a helper command's own panel calls are logged too; `_call_driver` has no caller but `Jobs.premiere`; each start names its `caller`, the program and Claude Code session from `helper_protocol.caller`, nested panel calls included)
- test (2026-11-24, command log report): `python -m pytest tests/test_helper_log.py -q` and `python tools/helper_log.py` (per-command calls, time and failures; repeated failures grouped into incidents; calls by caller)
- fail-proof: the 4 log tests red on 26ca379 (no log file); skipping the start record turned the same 4 red; a second `_call_driver` caller turned the door test red with "route the call through Jobs.premiere so it is logged"; restored.

- test (2026-11-23, save diff minus the command log, #129): `python -m pytest tests/test_save_diff.py -q -p no:cacheprovider` (`cutdeck/save_diff.py`: clips matched by their full reader record, a same-name remove+add on one track paired as one `changed`; tracks and sequences added/removed, plus sequence markers and frame-size changes; only successful non-read calls fully within a save interval can explain changes on explicitly named sequences; `--corrections` passes at half the spoken corrections found)
- real data (2026-11-23): `python -m cutdeck.save_diff "<project folder>/Adobe Premiere Pro Auto-Save/<project>--*.prproj" --log output/premiere/premiere_commands.jsonl` on the 11-22 LV GP auto-saves 21:29–22:37: the max interview subtitle pass shows as trims (end/source_out, source_in/start), splits, disables and 17 added Graphics, ~1 s per save pair; the live helper's own log (a probe read at 15:41) parses and explains nothing
- fail-proof: made a command that names no sequence explain nothing; the whole-interval test went red; restored.
- blind spot: no stable clip ID survives a save (7,014 of 7,068 track items carry none; ObjectIDs renumber), so a moved clip with a same-name neighbour can pair with the wrong one; the 11-22 user edits at 21:09–21:17 predate the oldest kept auto-save

- test (2026-11-23, cdv call startup): `python -m pytest tests/test_cutdeck_cdv_startup.py -q -p no:cacheprovider` (a cdv round trip leaves asyncio, websockets, ai_backend, the helper, driver_commands, premiere_ui, numpy and PIL unloaded; the standard-library client in cutdeck/helper_protocol.py gives the same replies and errors as Backend against a real serve(), answers pings during a slow reply, and round-trips every frame length and a fragmented reply)
- fail-proof: the first 3 tests red on 26ca379 (before PORT/VERSION moved to cutdeck/helper_protocol.py), green after; removing the pong, the continuation join, or the refusal check in `ask` each turned tests red, restored.
- live (2026-11-23, bench `output/perf/2026-11-23-cutdeck-profile/cdv_bench.py`, helper on :7891 not restarted): fresh-process `cdv.py call read_sequence` timed from outside, 4 alternating block pairs of 6 per side, one warm-up dropped per side; old 26ca379 median 507 ms (477-618, n=24), new median 302 ms (278-359, n=24), 0 failures; the recorded result and the unknown-command error are identical on both sides. `import cdv` 354 ms to 155 ms.
- live (2026-11-23, same bench, standard-library client and lazy subprocess/ctypes): c4b47d3 median 281 ms (275-325, n=24), new median 102 ms (97-109, n=24), 0 failures; recorded result, unknown-command record, stdout and exit code identical to c4b47d3; 0 bytes added to the helper log; `doctor` and plain `launch` run live on the new client (`scratch`, `cleanup`, `launch --restart-helper` not run live). Left: python start ~32 ms, argparse + re ~19, socket + client ~9, pathlib/json ~11, first Winsock connect ~4, the command ~4.

## Premiere project readers
- test: `python -m pytest tests/test_prproj_anchor_check.py tests/test_prproj_pixels.py tests/test_prproj_reader.py tests/test_scrub_fcpxml.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: read u32 big-endian in cutdeck/prproj_reader.py, test_prproj_reader went red, reverted

## Donor project + import_sequences (issue 130)
- test: `python -m pytest tests/test_prproj_donor.py tests/test_cutdeck_driver_commands.py -q -p no:cacheprovider` and `node --test tests/cutdeck_control.test.cjs`
- fail-signal: AssertionError
- fail-proof: left the Motion value unpatched in cutdeck/prproj_donor.py, test_donor_changes_one_scale... went red, reverted; dropped the appended effect objects in `_graft`, both test_donor_grafts_an_effect... cases went red, reverted
- live (2026-11-23, scratch project `output/issue130/scratch_130.prproj`, runs `20261123-221826-issue130-import-sequences` and `20261123-222215-issue130-full-readback`): `cdv.py call import_sequences` of a plain and a Scale-137.25 donor of `a5_start.prproj` `Gate4`; both imported, all 6 clips' Motion read back equal to the donor, V1 Scale 137.25 only on the patched arm
- live graft + cross-sequence (2026-11-23, run `20261123-223331-issue130-cross-seq-paste`): a donor of `Plattern_FB SIZE` and a donor with its masked Gaussian Blur and Lumetri grafted (`--effect`) onto two testsrc clips, imported, Edit > Copy / Edit > Paste onto another sequence; blur changed only the mask's 208x170 box, Lumetri's 130 params equal the template's

## Shorts rule check (issue 128)
- test: `python -m pytest tests/test_shorts_check.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof (2026-11-23): safe-zone bottom back to 1440 (1 red); moving-video limit raised to 99 s (4 red); each restored.
- offline (2026-11-23, `python -m cutdeck.shorts_check` on the saved 11-21 and 11-22 projects): moving race video 3.53 s on `TT russell wall v3`, 5.10 s on v4, under 3 s on v5, equal to the hand measurements in projects/1raceclub/workflow-log.md; 0 flags on the user's `TT editing` (11-21) and `max interview`. Not a fresh trial: every timeline was seen in the first trial and the definitions were set against them. On the 11-21 project the race feed is date-named, so `--feed 10-55-45` is needed (it then measures 1.73 s and 2.3 s).
- fresh trial (2026-11-23, `python tools/shorts_check_trial.py`, protocol posted on issue 128 before the run): the user's own `tt` timelines in 18 episodes from 2026-09-03 to 11-19 (the other 17 held out, not run). 56 gap-separated runs, 51 flags against a pass line of 1: **not met**. 10 runs are 5-min-plus working stretches, not Shorts. The check measured anything (feed, box or title) on only 22 runs; `FEED` matched no clip on 50 (feeds named `Qualifyin.ts`, `race.mp4`, `fp2.mp4`…), so a missed feed name passes silently. Each flag looked at: safe zone 44, all picture-in-picture boxes of moving feed in older Shorts; the box geometry matches the user's own export (`20260925 - q ant.mp4`, 5 s), so this is the user's practice before the 11-22 safe-zone rule, not a check bug. Moving video 5: the 68-min working stretch; 24.7 s (`TT max radio`) and 3.83 s (`NOR CHAMPENGE BROKE`) in exported Shorts, older practice before the 11-21 rule; two unexported runs. Title 2: both word-by-word subtitles that start on the first frame, so "text on the first frame" also catches subtitles (definition gap). Catching an agent's Short not tested here.

## place_text (text into Premiere via a baked .mogrt)
- test: `python -m pytest tests/test_cutdeck_mogrt_text.py -q`
- fail-signal: failed
- live: `cdv.py call place_text` on the scratch (2026-11-21, runs `20261121-230511-mogrttext`, `20261121-232401-place-text-busy`): Thai rendered from Basic Title and an AE template, AE text read back, occupied track refused, Undo removes it.

## Premiere UI route (set_speed, nest_clips, edit_text, paste_attributes)
- test: `python -m pytest tests/test_cutdeck_premiere_ui.py -q`
- fail-signal: failed
- fail-proof (2026-11-21): TICKED_MEAN raised to 200 in cutdeck/premiere_ui.py, test_ticked_box_is_told_from_an_empty_one went red, restored
- live: `cdv.py call set_speed | nest_clips | edit_text` on the scratch (run `20261121-233204-close-gaps`): speed 200 / 50+reverse read back, Thai nest name, Thai text rendered, each undone with one Edit > Undo.
- live edit_text waits (2026-11-23, runs `20261123-001015-edit-text-sleeps` and `20261123-001809-edit-text-real-footage`, bench `output/perf/2026-11-23-cutdeck-profile/edit_bench.py`): fixed pauses replaced by window waits; median 7.66 s to 4.27 s over bars, 7.73 s to 4.34 s over real footage with Thai text, 0 failures, 0 px changed elsewhere, `left_editing` true 10/10 over real footage (the old check said false 9/9 there).
- live export_frame wait (2026-11-23, bench `output/perf/2026-11-23-cutdeck-profile/ef_bench.py`, alternated old/new blocks with panel reloads): returns once the PNG ends with IEND; last write to return median 110 ms to 30.5 ms on new frames (n=12 each), 111.5 to 31 ms on a repeated frame, 48/48 frames complete and decoded. edit_text regression over bars 4/4, 0 px elsewhere, median 4.07 s.
- live paste_attributes (2026-11-22, `cutdeck.premiere_ui.paste_attributes` on Paste attr test sequences): 58/58 then 744/744 plain V4 pieces read back equal to the source; one Undo reverted the 58; the 10 pre-styled pieces were listed in `differ` (Posterize twice). Through MCP (stdio client → `python -m cutdeck.mcp_server` → helper restarted on this code): `premiere_paste_attributes` listed (53 tools), 58/58 matching, `differ` empty, 2.7 s.

## SRT subtitles (srt_subtitles)
- test: `python -m pytest tests/test_cutdeck_srt_subtitles.py -q`; `node --test tests/cutdeck_build_sequence.test.cjs` (clone with a negative v_offset)
- fail-signal: failed
- fail-proof (2026-11-22): SELECTED_ROW set to 29 in cutdeck/srt_subtitles.py, 2 tests went red, restored
- live: `cdv.py call srt_subtitles` on the scratch (run `20261122-222610-srt-captions`, 57): 4 cues to V2 in the "1RC Subtitle" Style, position [0.5, -0.0423], scale 112.5; every Graphic frame-exact; the rendered text matched the user's subtitle within 1 px; `edit_text` edited one.

## Decode language (th / en / auto)
- test: `python -m pytest tests/test_language_choice.py -q -p no:cacheprovider`
- fail-signal: failed
- live (2026-11-22): an English F1 broadcast transcribed with `en` and `auto` (identical, English) vs the default (invented Thai); a Thai source with `auto` identical to `th`; through the helper, `auto` and `en` return their own cached jobs; `auto` held out on 10 unseen files, 10 right (docs/ENGINES.md).

## Several pieces at fixed cost: paste_pieces, the paste_from guard, the razor re-read
- test: `python -m pytest tests/test_cutdeck_driver_commands.py -k "derive or paste or arrange" -q -p no:cacheprovider`, `node --test tests/cutdeck_build_sequence.test.cjs tests/cutdeck_native_cut.test.cjs`
- fail-proof (2026-11-26): the two `razor:` tests fail on master with the live message "razor filler on audio track 0 is not one frame long"; the `ranges` clone test fails on the old `buildSequence.js`.
- live (2026-11-26, scratch `output/short-bench/short-bench.prproj`, `python tools/short_route_bench.py --route A|D --n 5|20|40 ...`, log `output/short-bench/bench.jsonl`): route A (derive) 19.6 / 24.0 / 35.0 s and 6-8 top-level calls at N 5 / 20 / 40, route D (paste per piece) 43 / 172 / 411 s and 1+N calls; both exact against the plan; A and D render pixel-identical at all 80 piece edges (`output/short-bench/frames/edges.json`); `paste_pieces` (then `derive_short`) 40 pieces in 47.5 s, 0 missing, temporaries removed; a third `paste_from` into one target refused live.
- stale handles (2026-11-26, `output/short-bench/stale_exp.py tiny|control40 N [--no-reload]`, log `stale_exp.jsonl`): `node --test tests/cutdeck_control.test.cjs tests/cutdeck_driver.test.cjs tests/cutdeck_build_sequence.test.cjs` cover the fresh-fetch retry and the null-entry re-read; live, 6 of 6 two-piece reordered builds exact with one logged recovery in a settled session; in a storm (PREMIERE_FACTS "Panel writes right after another command's commits") builds still fail loudly and name every temporary left.

## Derive from a sequence: Make Subsequence, paste_from, arrange
- test: `python -m pytest tests/test_cutdeck_driver_commands.py -k "paste or subsequence or arrange" -q -p no:cacheprovider` and `node --test tests/cutdeck_control.test.cjs`
- fail-signal: failed
- fail-proof (2026-11-24): dropping the landing correction in `_paste_from` (`v_up = v_offset` without `- shift`) turned `test_paste_from_corrects_where_the_paste_landed_and_honours_v_offset` red; restored, green.
- arrange fail-proof (2026-11-24): dropping the lift of the old stretch from `arrange_steps` turned `test_arrange_plays_the_blocks_in_the_new_order_on_a_copy` red; restored, green.
- arrange live (2026-11-24, run `20261124-131438-arrange`): three pieces played 3, 1, 2 on a copy, read back exact with the cover's Scale 50, frames pixel-identical to the source.
- live (2026-11-24, runs `20261124-125650-subseq-probe`, `20261124-130315-paste-from`): Make Subsequence of 1-4 s kept every track, edges, Scale and Gaussian Blur, frame pixel-identical to its parent, one Undo removes it; `paste_from` put that range into another sequence at 3 s with `v_offset` 1, read back frame-exact with the blur and Scale, park cleaned, piece deleted. Design: docs/DERIVE_FROM_SEQUENCE.md.

## Question pieces from the user's split (label colours)
- test: `python -m pytest tests/test_split_pieces.py tests/test_prproj_reader.py -q -p no:cacheprovider`
- fail-signal: failed
- fail-proof (2026-11-24): a wrong label pattern in `cutdeck/prproj_reader.py` (`LabelColorX`) turned `test_a_clip_label_colour_is_read_as_its_slot` red; restored, green.
- real (2026-11-24, offline): `python -m cutdeck.split_pieces` on 20261123 `Editing` gave the 22 V2 pieces with their colours and opening words in 1.4 s; 20261120 `Edit` gave 15.

- test: `python -m pytest tests/test_cutdeck_timeline_transcript.py tests/test_cutdeck_word_cut.py -q -p no:cacheprovider`
- fail-signal: failed
- fail-proof (2026-11-22): dropped `- clip.in_` from the mapping in cutdeck/timeline_transcript.py (3 red); widened the sound threshold in `tighten` (1 red); cut at the word edges instead of in the pauses in cutdeck/word_cut.py (1 red); each restored.
- fail-proof (2026-11-22, PR 117 gaps): before the fix, 6 tests went red: a cache hit did not make its transcript the one read (test_service), `mark_transcript_chosen` / `transcript_scripts` missing, no other-language note, a store made before `job.chosen_at` crashed `source_words`, and the word tools dropped the transcript's warnings. Green after; full pytest 1,357 passed (the 8 `test_text_box` failures also fail with the change stashed).
- real store (a copy of `transcriber.db`, offline from the saved `listen 50fps (scratch)` A5): job 89 (English) read with a note naming Thai job 86; `transcribe(language="th")` hit the cache and the next read was job 86 with a note naming `language="en"`; `transcribe(language="en")` hit the cache and the read was job 87. No ASR ran. Then on the real store through the helper's `transcribe` (a second helper on port 7899, Premiere closed) and the real offline CLI: `th` -> job 86 with the warning, `auto` -> job 89 again; 90 jobs before and after.
- live (2026-11-22, runs `20261122-004515-timeline-listen`, `20261122-013033-timeline-listen-final`, `20261122-015758-short-placed`, `20261122-020524-real-sequences`): `timeline_transcript` on a 96-min sequence, 119- and 1,653-clip rough cuts (~2 s), speed 200%/50%, two sources on two tracks; fresh transcripts of the cut audio sit a median 3 ms / -13 ms from the mapped words; Rough Cut from mapped transcripts gave identical cut lists, and on a never-transcribed source it transcribed the source once; `plan_pieces` + `build_sequence` made a reordered Short with 0 cuts in sound; `keep_words` kept 2 phrases on a 7-track copy (every track kept, 0 cuts in sound); the planner's 60 ms pad beats 120 ms on the owner's two independent cuts (16 vs 7 of 46 and 31 vs 18 of 104 edges within a frame; scripts/timeline_listen/calibrate_edges.py); `keep_words` across rough-cut joins kept every track; `cut_words` removed 3 fillers (said 3 -> 0, no new cut in sound). Phrases in continuous speech (no pause) are cut at the word boundary and reported as cuts in sound. Report: docs/TIMELINE_LISTEN.md.
- perf (2026-11-23, ffprobe stream count cached per process by path+size+mtime): `test_audio_streams_are_probed_once_per_file_version` red on the old code (ffprobe ran on every build), green after; a replaced file is probed again and its new count returned. Offline A/B (`output/perf/2026-11-23-cutdeck-profile/tt_ab.py 26ca379`) on the saved `20261122-004515-timeline-listen/31-read_timeline-full-clips.json` (8,878 tightened words, 9,045 untightened; 1 source; real store; Python 3.13.4), 6 alternating blocks of 5 warm builds each, two runs: old median 309 / 299 ms (296-477 / 294-339), new 212 / 208 ms (206-233 / 203-228), identical output. First build in a process still pays one ffprobe (4,816 ms with a cold level decode, 482 ms with levels cached). `build()` runs in the helper process (`driver_commands`), so the cache lasts the helper's life. Not checked live through the helper.

## Clean speech (fillers, repeats, restarts) on a copy
- test: `python -m pytest tests/test_cutdeck_speech_clean.py -q -p no:cacheprovider`
- fail-signal: failed
- fail-proof (2026-11-25): the no-pause guard in `cutdeck/speech_clean.py` `plan` switched off (1 red); the restart rule without its same-start check (2 red); adjacent findings not merged (1 red); each restored, green.
- vs the owner (2026-11-25, offline): on the LV GP 2026 rough cut, of the findings whose neighbouring lines the owner kept in their final `yt`, they had cut 2 of 14 fillers and 2 of 13 restarts by hand. So restarts are marked by default (`cut_restarts` cuts them). Whether the kept ones were wanted or just too slow to cut by hand is not known.
- offline (2026-11-25) on the saved `yt` with its audio levels: found 14 fillers, 10 restarts, 7 repeats, 2 near restarts; with every cut kind on, the audio guard left 14 cuts (8 fillers skipped and 9 findings turned into markers for having no pause), and no kept piece under 10 frames between cuts.
- live (2026-11-25, `apply: false` only) on the open HKS `2 FACEBOOK D1 (agent v2)`: 1 restart found ("พ่อ / พ่อผมก็เสียไปแล้ว"), no pause to cut in, so marked..
- live (2026-11-26, `apply: true`, defaults) on the LV `yt`: 7 cuts (6 fillers, 1 repeat), 4.1 s removed on every track (V1-3, A1-6 all end at 1719.83 s, was 1723.93), 18 markers, 8 fillers skipped, `new_cuts_in_sound` empty. Each of the 18 markers read back on the copy's transcript lands on its own words. Copy: `yt clean speech (Claude)` in Rough Cuts. The copy's `end_ticks`/`out_ticks` keep the parent's value.

- markers (2026-11-26): `cut_copy` (and every native cut) moves the copy's markers back with the cuts and removes one inside a cut. Test `markers on the copy move back with the cuts` in `tests/cutdeck_native_cut.test.cjs`; fail-proof: red before the fix (markers stayed put). Live: a scratch cut of `yt clean speech v2 (Claude)`, 8 of 8 markers at the expected times, the one in a cut removed; scratch copy deleted.

## CutDeck panel (UXP)
- test: `node --test tests/*.cjs`
- test: `node tools/adobe/check-api.mjs`
- fail-signal: # fail 1
- fail-proof (2026-11-21, general control; tests/cutdeck_control.test.cjs): each went red on its own and was restored, 8/8 green: findClip matched any clip on the track instead of the one starting at the id's ticks (2 red); remove used VIDEO for audio clips (1 red); select_clips skipped setSelection (1 red). Validators: tests/test_cutdeck_driver_commands.py `test_control_commands_check_ids_ticks_and_ops`. Not yet run in Premiere (docs/PREMIERE_CONTROL_MAP.md).
- fail-proof: changed the track-index guard in uxp/cutdeck/transform/frameBounds.js, cutdeck_frame_bounds.test.cjs went red; also made clip-underneath start exclusive and end inclusive, the frame-finished check accept a first non-zero size or a repeated null, and the playhead start check exclusive, cutdeck_frame_bounds_edges.test.cjs went red on each (the underneath start boundary and the size-stability check had stayed green before), reverted
- fail-proof (2026-10-19, per-text-layer bounds): removed the hide-other-text write in `measureTextLayer` (uxp/cutdeck/transform/frameBounds.js); 5 tests in cutdeck_transform_edit.test.cjs went red; restored, 696/696 green. Live 2026-10-19: both text layers of a 2-text Graphic aligned left alone, each measured with the other hidden (PREMIERE_FACTS row "Measuring ONE text layer").
- fail-proof: stashed the alignPanel.js/panel.js fixes, cutdeck_input_commit.test.cjs went red on both tests (bad frame count stayed in the box; Enter committed twice), restored
- fail-proof: inverted the routesDiffer comparison in uxp/cutdeck/layoutProbe.js, cutdeck_layout_probe.test.cjs went red on the text-probe differ case, reverted
- fail-proof (2026-10-26, one panel, four tabs; tests/cutdeck_one_panel.test.cjs): each went red on its own and was restored, 726/726 green: dropped the `isMounted` tab gate in features/align.js (the poll read Premiere on the Cut tab); raised the frame drawing's height cap to 300 (9:16 drawn too tall); let the fx block reset include disabled rows; never cleared the busy-tab dot; gave `#tab-align` a `data-act` (busy would disable it); laid the frame out while its width is 0. Not yet run in Premiere (plan step 8).
- fail-proof (2026-10-26, poll cost; tests/cutdeck_align_poll_rate.test.cjs): made the idle read keep 1 s instead of doubling to 4 s while unchanged in uxp/cutdeck/features/align.js; both poll-rate tests went red; restored, 729/729 green. The poll and its Premiere listeners now start and stop with the Transform/Align tab (cutdeck_align_panel.test.cjs pins it). Not yet run in Premiere.
- fail-proof (2026-11-22, PR 115 gaps): before the fix, cutdeck_transform_edit.test.cjs "an edit plans from Premiere's values" went red (Position x 0.1920 vs 0.1667, the stale rotation 7 that moved the picture live in run `20261122-000256-maintain-timeline`) and cutdeck_driver.test.cjs "cut_copy refuses a result_name already in the project" went red; both green with edits reading fresh (`forceRefresh` in uxp/cutdeck/transform/edit.js) and the name check in features/driver.js, 797/797. Live after a Premiere restart (run `20261122-073257-pr115-gaps`): rotate + Edit > Undo + anchor top-left wrote [0, 0] with the frame unchanged, cut_copy refused an existing name, crop/opacity/align group took effect and undid.
- fail-proof (2026-10-26, playback; tests/cutdeck_align_poll_rate.test.cjs): disabled the playhead-moved skip in `pollAlignTransform` (uxp/cutdeck/features/align.js); the no-reads-during-playback test went red; restored, 730/730 green. Not yet run in Premiere.

## Topic Cut
- test: `python -m pytest tests/test_cutdeck_topic_layout.py tests/test_cutdeck_topic_speakers.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: set BLUE_FRAME_MIN to 0.99 and to 0.05 in cutdeck/topic_layout.py, test_top_edge_mostly_blue_is_clip / test_top_edge_mostly_not_blue_is_studio went red (the first version of the tests stayed green under 0.99 because its edges were 100% blue; fixed before use); in cutdeck/topic_speakers.py, made turns merge across a pause and set the smoothing reach to 0, test_a_pause_starts_a_new_turn_even_for_the_same_speaker and test_smoothing_removes_a_single_outlier went red; reverted, files identical to backup

## HKS episode pipeline (projects/hks/build-plan.md)
- path: cutdeck/hks_*.py
- oracle: projects/hks/build-plan.md
- test: `python -m pytest tests/test_hks_assemble.py tests/test_hks_bleep.py tests/test_hks_breaks.py tests/test_hks_covers.py tests/test_hks_day.py tests/test_hks_draft.py tests/test_hks_episode.py tests/test_hks_finish.py tests/test_hks_judge.py tests/test_hks_tighten.py tests/test_hks_turns.py tests/test_hks_versions.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: in cutdeck/hks_judge.py kept_runs, made a run join across hidden content (`if False:`), test_kept_lines_join_unless_hidden_content_lies_between went red; in cutdeck/hks_bleep.py dropped the `(?!ว)` guards, test_compounds_are_not_swears went red; reverted, `git diff` empty

## SubtitleDesk quote workspace
- path: subtitle_desk/
- oracle: subtitle_desk/README.md, tests/conftest.py
- test: `python -m pytest tests/test_subtitle_desk.py -q -p no:cacheprovider`
- fail-signal: AssertionError
- fail-proof: dropped the range offset from cue times in subtitle_desk/server.py, test_session_reaches_ready_with_cues_shifted_by_range_offset went red, reverted

## Blind spots
- SubtitleDesk: the browser page (subtitle_desk/static/app.js) has no automated check, and nothing here transcribes a real range or imports the SRT into live Premiere; the backend runs against a fake helper and extractor.
- SRT placement in live Premiere is manual: `python -m tools.srt_roundtrip make DIR --fps N`, drag the file onto a test sequence (Subtitle, Source timecode), then `python -m tools.srt_roundtrip check FILE.srt` reads the captions back through the panel's Caption Timing probe.
- No real run of the pipeline: nothing here transcribes real audio on GPU. `transcribe.pipeline.run` on a real file and `transcribe.eval.harness` on the gold set are manual.
- CutDeck panel checks run against `tests/fakes/premiere.cjs`, not live Premiere; real-host behaviour is only in docs/PREMIERE_FACTS.md.
- Panel fail-proof includes the historical cases above and the Rough Cut source guard
  (verification/rough-cut-retirement-evidence.md); coverage is not exhaustive.
- Live Premiere is opt-in, not part of `verify.py run`. Before releasing CutDeck: start the helper (`python -m cutdeck.helper`), open a sequence with In/Out marks and the CutDeck panel, check with `python -m cutdeck.live_check`, then run `python -m pytest tests/test_cutdeck_live_premiere.py --live -m live -v` (add `--live-edit` only if you accept the selected clips being edited). It fails, never skips, if any piece is missing.
- Live run 2026-09-28 (`2 FACEBOOK D1`, nothing selected): 8/8 passed. With nothing selected the four transform/anchor/align/distribute tests only proved the "Select a clip" refusal, so their success path on real clips is still unproven.
- The offline mode of those tests runs the real panel driver against the fake Premiere with nothing selected, so the success path of transform/anchor/align/distribute on a real selection is only proven by the live run.
- HKS episode pipeline: the unit tests use synthetic data; the real-data checks need G:\Me\Works and the caches: `python -m cutdeck.<module> --all G:\Me\Works --check` for hks_episode, hks_breaks, hks_layout, hks_rough, hks_tighten, hks_covers, hks_draft, hks_finish, hks_bleep, hks_versions (`--holdout` once per change, never tuned on). The judge answers they read are under `test_projects/hks_judge/<day>/` (gitignored). No draft has been built in live Premiere. The day command (`python -m cutdeck.hks_day "<day folder>"`) runs the judges through headless `claude -p` and puts markers in live Premiere; its tests fake both.
- One equivalent mutant is left alive in flywheel/diff.py (`hi = j2` for `max(hi, j2)`).
- Topic Cut: the two real-episode tests are opt-in (about 2 minutes together, over the runner's 120 s limit): `TOPIC_CUT_REAL=1 python -m pytest tests/test_cutdeck_topic_layout.py tests/test_cutdeck_topic_speakers.py -q -p no:cacheprovider`. They need the 4.5 GB `HKS Facebook 290969 Full.mp4`; the speaker one also needs speechbrain and a GPU. Run them before changing the layout or speaker modules. Their accuracy floors (layout 93%, speaker host/guest 85% / 15%) come from labels made by eye and a threshold tuned on the same frames, so they are optimistic. The topic-start judgement itself (which host run opens a new topic) is not code and has no check; its answer key is `tests/data/topic_cut_starts_hks290969.json`.
