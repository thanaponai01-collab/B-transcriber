# cutdeck features

## CutDeck helper
- what: Local websocket service (ws://127.0.0.1:7891) that runs CutDeck jobs (rough cut, transcribe, sync plan) and relays live-Premiere commands between agents and the panel.
- cli: `python -m cutdeck.helper` @ cutdeck/helper.py :: --jobs-dir
- trace: `main` @ cutdeck/helper.py > `serve` @ cutdeck/helper.py > `dispatch` @ cutdeck/helper.py > `_run` @ cutdeck/helper.py
- effect: job folders under `output/premiere/`, `helper.log`
- verify: CutDeck helper
- status: offline-proven at afa8dc7 (verification/rough-cut-retirement-evidence.md); current helper not restarted/live-confirmed. Live proof at 2ad7576 is historical.

## Rough cut
- current-design: docs/rough-cut.md (JSON audio input, source-snapshot validation, bounded stale-handle recovery and verification limits)
- what: Find silence and filler in the active Premiere sequence and cut them out of a copy of the sequence, natively in Premiere.
- click: `#cut` @ uxp/cutdeck/index.html
- click: `#resume` @ uxp/cutdeck/index.html
- click: `#pill-speech` @ uxp/cutdeck/index.html
- click: `#pill-silence` @ uxp/cutdeck/index.html
- cli: `python -m cutdeck.rough_cut <sequence.json> --cuts-json <cuts.json>` @ cutdeck/rough_cut.py :: --dry-run
- trace: `bindPrimaryActions` @ uxp/cutdeck/core/panel.js > `onCut` @ uxp/cutdeck/main.js > `onCut` @ uxp/cutdeck/features/roughCut.js > `doCut` @ uxp/cutdeck/features/roughCut.js > `nativeCut` @ uxp/cutdeck/features/roughCut.js
- needs: helper running; the active sequence open in Premiere
- effect: a new sequence `<name> — CutDeck <id>`; the original is untouched; the project is saved before the copy is made (Premiere can quit mid-cut, PREMIERE_FACTS.md)
- verify: CutDeck panel (UXP)
- status: proven offline 2026-10-11: JSON analysis, source-snapshot refusal, exact native golden and bounded handle recovery; live Premiere confirmation remains pending (verification/rough-cut-retirement-evidence.md)

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
- note: building blocks with no entry point of their own yet: `classify_frame` @ cutdeck/topic_layout.py (clip or studio layout), `host_turns` @ cutdeck/topic_speakers.py (host or guest voice). Design and findings: projects/hks/design-topic-cut.md; answer key: tests/data/topic_cut_starts_hks290969.json
- verify: Topic Cut
- status: suspected: current behavior not re-proven after source drift; historical proof at commit c279d6b: ran add_markers live on "Footages Copy 01" (31 markers, 1 undo step) and the Topic Cut tests, both with the real episode; the panel button, razor cuts and the topic judge do not exist

## Adjustment layer, matte and freeze frame
- what: Add an adjustment layer, colour matte or frame hold to the timeline (click spans all, Ctrl per clip, Shift every cut; hold: Alt/Shift clones instead of exporting).
- click: `#btn-adj` @ uxp/cutdeck/index.html
- click: `#btn-matte` @ uxp/cutdeck/index.html
- click: `#btn-hold` @ uxp/cutdeck/index.html
- trace: `bindAdjustmentButtons` @ uxp/cutdeck/core/panel.js > `onAdjust` @ uxp/cutdeck/main.js > `createAdjustFeature` @ uxp/cutdeck/features/adjust.js
- verify: CutDeck panel (UXP)
- status: traced: read the three bindings and main.js wiring; not run

## Panel navigation and tools
- what: One CutDeck panel with four tabs (Cut, FX, Transform, Align; the last one used reopens), Settings, reload, and diagnostic probes folded under Probes in the overflow menu.
- click: `#tab-edit` @ uxp/cutdeck/index.html
- click: `#tab-adj` @ uxp/cutdeck/index.html
- click: `#tab-transform` @ uxp/cutdeck/index.html
- click: `#tab-align` @ uxp/cutdeck/index.html
- click: `#tools-toggle` @ uxp/cutdeck/index.html
- click: `#menu-item-probes` @ uxp/cutdeck/index.html
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
- click: `#captiontimingprobe` @ uxp/cutdeck/index.html (also `python -m cutdeck.premiere_cli run_probe captiontiming`; read by tools/srt_roundtrip.py)
- trace: `bindTabs` @ uxp/cutdeck/core/panel.js > `onTab` @ uxp/cutdeck/main.js
- note: `alcreate`, `syncmoves` and `nativecut` probes edit the project (they say so in their tooltips); the others are read-only
- verify: CutDeck panel (UXP)
- status: tested: tab switching, per-tab views, busy dot, remembered tab and the Probes fold are covered by tests/cutdeck_one_panel.test.cjs (2026-10-26); not yet run in Premiere

## Transform and Align tabs
- what: Transform tab: edit the selected clip's Motion (incl. Crop) and Opacity rows, laid out as Effect Controls' fx blocks with fold and block reset. Align tab: a frame drawing whose edges and center lines align and whose nine dots on the clip set the anchor, plus Frame/Selection/Group and Distribute.
- click: `#align-refresh` @ uxp/cutdeck/index.html
- click: `#align-probe` @ uxp/cutdeck/index.html
- click: `#align-scale-reset` @ uxp/cutdeck/index.html
- click: `#align-rotation-reset` @ uxp/cutdeck/index.html
- click: `#align-copy` @ uxp/cutdeck/index.html
- click: `#align-line-left` (and the other five `#align-line-*`) @ uxp/cutdeck/index.html
- trace: `alignPanel` @ uxp/cutdeck/main.js > `bind` @ uxp/cutdeck/core/alignPanel.js
- needs: clips selected in Premiere; with none selected these only refuse ("Select a clip")
- verify: CutDeck panel (UXP)
- status: suspected: current behavior not re-proven after source drift; historical proof at commit 2ad7576 for the refusal path only (VERIFY.md live run 2026-09-28); success path on a real selection unproven

## Agent tools (MCP)
- what: Expose CutDeck to agents over MCP stdio: transcribe and `premiere_rough_cut` (the live sequence, no XML: panel read -> `prepare` -> `start`, then `premiere_apply_cuts`), job polling, and the `premiere_*` live commands.
- cli: `python scripts/start_cutdeck_mcp.py` @ scripts/start_cutdeck_mcp.py :: cutdeck.mcp_server
- cli: `python -m cutdeck.mcp_server` @ cutdeck/mcp_server.py :: --port
- trace: `main` @ cutdeck/mcp_server.py > `create_server` @ cutdeck/mcp_server.py > `premiere` @ cutdeck/ai_backend.py > `_ask` @ cutdeck/ai_backend.py
- needs: helper running; the panel open for `premiere_*` tools
- verify: CutDeck helper
- status: traced: read all tool definitions in mcp_server.py and the helper's dispatch; server not started. `premiere_rough_cut` proven against a real helper with a stubbed panel read (tests/test_cutdeck_mcp_backend.py, 2026-10-07); not run against live Premiere

## Timeline transcript (MCP)
- what: What a sequence says and where, without transcribing it again: each source file's transcript (made once by `transcribe`) mapped through one audio track's clips onto the timeline in exact ticks, word times tightened to the audio. Lines, phrase search, and every clip edge with audible sound at the cut (`cuts_in_sound`). Speed-changed clips are mapped. Works the same on a rough cut, a copy or a re-cut. Each file's transcript is the one `transcribe` last returned; a file with transcripts in both Thai and English gets a `warnings` line with the call that switches (also returned by cut by words, plan pieces and keep words).
- mcp: `premiere_timeline_transcript(sequence?, track?, query?, from_ticks?, to_ticks?, offset, limit)`
- cli: `python -m cutdeck.timeline_transcript --prproj <file> --sequence <name>` @ cutdeck/timeline_transcript.py :: main (a saved project, no Premiere)
- trace: `premiere_timeline_transcript` @ cutdeck/mcp_server.py > `_timeline_transcript` @ cutdeck/driver_commands.py > `read_timeline` (panel) > `build` @ cutdeck/timeline_transcript.py > `source_words` > `store.latest_transcript_job`
- needs: helper and panel; each source transcribed once (`missing` lists the rest)
- effect: `output/timeline_transcripts/<sequence>-<track>.json` (every line and word), level envelopes in `output/timeline_transcripts/levels/`
- verify: Timeline transcript and cut by words
- status: live-proven 2026-11-22 on Premiere 27.0 (docs/TIMELINE_LISTEN.md)

## Cut by words (MCP)
- what: Remove phrases (by their words, or a tick span) from a COPY of a sequence, each cut in the pauses around them, then read the copy back to prove the words are gone and no cut landed in speech.
- mcp: `premiere_cut_words(result_name, remove, sequence?, track?, keep_ms=250)`
- trace: `_cut_words` @ cutdeck/driver_commands.py > `plan` @ cutdeck/word_cut.py > `cut_copy` (panel) > `build` @ cutdeck/timeline_transcript.py
- effect: a new sequence `result_name`; the source is never edited
- verify: Timeline transcript and cut by words
- status: live-proven 2026-11-22 on a scratch rough cut: 3 fillers removed, 0 new cuts in sound; phrases inside continuous speech are removed but their cuts are reported in sound (no pause to cut in)

## Keep words on a copy (MCP)
- what: Keep only these phrases of a sequence, in its order, on a copy made by cut_copy (every track and layer kept); spans placed in the source's pauses; read back.
- mcp: `premiere_keep_words(result_name, keep, sequence?, track?, pad_ms=60, wordless_ms=0)`
- trace: `_keep_words` @ cutdeck/driver_commands.py > `keep_ranges` @ cutdeck/word_cut.py > `cut_copy` (panel)
- verify: Timeline transcript and cut by words
- status: live-proven 2026-11-22 on a 7-track scratch: every track kept, 0 cuts in sound

## Plan a Short by its words (MCP)
- what: Give the phrases to keep, in order; each piece's In/Out is placed in the source file's own pauses around its words; returns items for premiere_build_sequence. Edits nothing.
- mcp: `premiere_plan_pieces(keep, sequence?, track?, pad_ms=60, wordless_ms=0)`
- trace: `_plan_pieces` @ cutdeck/driver_commands.py > `plan_pieces` @ cutdeck/word_cut.py > `build` @ cutdeck/timeline_transcript.py
- verify: Timeline transcript and cut by words
- status: live-proven 2026-11-22: a reordered 3-piece Short built from its items read back with 0 cuts in sound

## General Premiere control (MCP)
- what: Hand-level control of Premiere for agents. `premiere_read_timeline`, `premiere_list_project`, `premiere_open_sequence`, `premiere_set_playhead`, `premiere_set_in_out`, `premiere_select_clips`, `premiere_edit_clips` (move, trim, enable/disable, rename, remove, in one undo step), `premiere_place_media` (overwrite, insert, nest), `premiere_list_effects`, `premiere_add_effect`, `premiere_set_param` (any effect parameter or keyframe), `premiere_add_transition`, `premiere_set_track_mute`, `premiere_remove_markers`, `premiere_import_files`, `premiere_save_project` and `premiere_export_frame` (a PNG of a frame). Plus `premiere_screenshot`, a PNG of the whole Premiere window (no panel needed). Clips are addressed by id `V<n>@<start_ticks>`. Every route, and what UXP cannot reach (razor, link, targeting, undo): docs/PREMIERE_CONTROL_MAP.md.
- trace: `premiere_edit_clips` (built from cutdeck/driver_commands.py) @ cutdeck/mcp_server.py > `premiere` @ cutdeck/ai_backend.py > `premiere` @ cutdeck/helper.py > `handle` @ uxp/cutdeck/features/driver.js > `editClips` @ uxp/cutdeck/timeline/control.js
- trace: `premiere_screenshot` @ cutdeck/mcp_server.py > `premiere` @ cutdeck/helper.py > `capture` @ cutdeck/screenshot.py
- needs: helper running and the CutDeck panel open (reloaded, so it has timeline/control.js); `premiere_screenshot` needs the helper and Premiere not minimised, not the panel
- verify: CutDeck panel (UXP); CutDeck helper
- status: live-proven 2026-11-21 on Premiere 27.0.0: every tool ran through the helper on scratch sequences in a real project (docs/PREMIERE_FACTS.md *General control live pass*). The live pass found and fixed a double-shift on ripple removes and made place_media fail when nothing lands. Not run through an MCP client session itself (the same helper path was used).

## Premiere menu and keyboard commands (MCP)
- what: Run what the panel API cannot do. `premiere_list_menu` and `premiere_menu_command` run any Premiere menu item by its path, e.g. "Edit > Undo", "Sequence > Add Edit to All Tracks", "Clip > Unlink". `premiere_list_key_commands` and `premiere_key_command` press any bound shortcut from the user's .kys, e.g. cmd.edit.rippledelete. Timeline commands first focus the named timeline (Window > Timelines > name) and check the active sequence. Dialog items and quit/close/open/import/export/save-as items are refused.
- trace: `premiere_menu_command` @ cutdeck/mcp_server.py > `premiere` @ cutdeck/helper.py > `run_focused` @ cutdeck/keys.py > `invoke` @ cutdeck/menu.py
- trace: `premiere_key_command` @ cutdeck/mcp_server.py > `premiere` @ cutdeck/helper.py > `run_command` @ cutdeck/keys.py > `press_command` @ cutdeck/keys.py
- needs: Premiere running on Windows, not minimised, and the helper running (it runs these). Timeline focus also needs the CutDeck panel (to open and check the sequence). Also `python -m cutdeck.premiere_cli menu_command "Edit > Undo"`.
- verify: CutDeck helper
- status: live-proven 2026-11-21 on 27.0.0 through the MCP tools: razor via menu and via keys, Undo/Redo via menu, Link/Unlink, ripple delete via Shift+Delete, End via the Program Monitor, File > Exit refused. Ctrl+Z and a Ctrl+Alt binding did nothing as keys (use the menu). Re-run 2026-11-21 after moving into the helper: menu_command (Window > Timelines, Edit > Undo) and key_command (End via the Program Monitor) worked from the helper process.

## Ask Premiere's AI Assistant (MCP)
- what: `premiere_assistant_ask(prompt, timeout_s)` types a prompt into Adobe's own AI Assistant (beta) chat panel through Windows UI Automation, waits for the reply and returns `{done, text, credits, buttons}`. Windows only. Each prompt spends the user's Adobe credits.
- trace: `premiere_assistant_ask` @ cutdeck/mcp_server.py > `premiere` @ cutdeck/helper.py > `ask` @ cutdeck/assistant.py > `_panel` @ cutdeck/assistant.py
- needs: Premiere running with the AI Assistant panel already open (its toolbar button can't be reached), and the helper running. Not the CutDeck panel.
- verify: CutDeck helper
- status: run live 2026-11-17 on Premiere 27.0.0.88 through the MCP tool: two read-only questions answered in 10-18 s. Moved into the helper 2026-11-21 and not re-run there (each prompt costs credits). Not tried: a prompt that edits, the Permission mode approval flow, Thai text, Premiere Beta.

## Live Premiere CLI
- what: Send one live command (status, read_sequence, apply_cuts, add_markers, run_probe, inspect_selection, transform/anchor/align/distribute) to the panel through the helper.
- cli: `python -m cutdeck.premiere_cli <command>` @ cutdeck/premiere_cli.py :: --port
- cli: `python -m cutdeck.live_check` @ cutdeck/live_check.py :: main
- trace: `main` @ cutdeck/premiere_cli.py > `premiere` @ cutdeck/ai_backend.py > `_ask` @ cutdeck/ai_backend.py
- verify: CutDeck helper
- status: suspected: current behavior not re-proven after source drift; historical proof at commit 2ad7576 for `--help` (lists the ten commands); live commands need Premiere + panel and were not run this session

## Read a Premiere project
- what: Print a read-only JSON summary of a `.prproj` (tracks, mute state, clip disable), check anchors, and read pixels.
- cli: `python -m cutdeck.prproj_reader <project>` @ cutdeck/prproj_reader.py :: --sequence
- cli: `python -m cutdeck.prproj_anchor_check` @ cutdeck/prproj_anchor_check.py :: main
- cli: `python -m cutdeck.prproj_pixels` @ cutdeck/prproj_pixels.py :: main
- trace: `main` @ cutdeck/prproj_reader.py
- verify: Premiere project readers
- status: proven @ 2ad7576 for `prproj_reader --help`; not run on a project

## Check a Short against the written rules
- what: Flag each 9:16 timeline in a saved `.prproj` that breaks the measurable 1RaceClub Shorts rules: moving race video over 3 s, a box outside the safe zone, a title not ending on a cut. Exit 1 when anything is flagged.
- cli: `python -m cutdeck.shorts_check <project>` @ cutdeck/shorts_check.py :: --sequence, --feed
- trace: `main` @ cutdeck/shorts_check.py > `check_sequence` @ cutdeck/shorts_check.py > `read_project` @ cutdeck/prproj_reader.py
- verify: Shorts rule check (issue 128)
- status: proven 2026-11-23 offline on the saved 11-21 and 11-22 projects; no fresh trial on unseen Shorts yet

## HKS episode drafts (โหนกระแส)
- what: Analyse an HKS episode offline (breaks, clock, layout, turns, sponsors, topics), have a select-only judge pick the cut, then draft the long form, FB and 1-min versions as source ranges and as a `build_sequence` request for a copy. The plan and every step's numbers: projects/hks/build-plan.md.
- cli: `python -m cutdeck.hks_judge prompt|apply <day folder> --task <task>` @ cutdeck/hks_judge.py :: sponsors, topics, cut, hook, fb, minute
- cli: `python -m cutdeck.hks_draft --all G:\Me\Works --check` @ cutdeck/hks_draft.py :: --holdout
- cli: `python -m cutdeck.hks_versions --all G:\Me\Works --prompt|--check` @ cutdeck/hks_versions.py :: --holdout
- cli: `python -m cutdeck.hks_assemble <day folder> --check --out <request.json>` @ cutdeck/hks_assemble.py
- cli: analysis and finishing checks: hks_episode, hks_breaks, hks_layout, hks_turns, hks_rough, hks_tighten, hks_covers, hks_finish, hks_bleep, hks_reels (each `--all G:\Me\Works --check`)
- trace: `request` @ cutdeck/hks_assemble.py > `draft` @ cutdeck/hks_draft.py > `kept_runs` @ cutdeck/hks_judge.py
- verify: HKS episode pipeline (projects/hks/build-plan.md)
- status: offline only (2026-11-23), on 8 tuning days with the holdout run once where a step allows it; no live build of a draft yet (it needs a copied project the user opens)
