# cutdeck features

## CutDeck helper
- what: Local websocket service (ws://127.0.0.1:7891) that runs CutDeck jobs (rough cut, transcribe, sync plan) and relays live-Premiere commands between agents and the panel.
- cli: `python -m cutdeck.helper` @ cutdeck/helper.py :: --jobs-dir
- trace: `main` @ cutdeck/helper.py > `serve` @ cutdeck/helper.py > `dispatch` @ cutdeck/helper.py > `_run` @ cutdeck/helper.py
- effect: job folders under `output/premiere/`, `helper.log`
- verify: CutDeck helper
- status: suspected: current behavior not re-proven after source drift; historical proof at commit 2ad7576 (earlier live run 2026-09-28, per VERIFY.md): helper live-proven in Premiere; not restarted in this session

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
- effect: a new sequence `<name> — CutDeck <id>`; the original is untouched
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
- note: building blocks with no entry point of their own yet: `classify_frame` @ cutdeck/topic_layout.py (clip or studio layout), `host_turns` @ cutdeck/topic_speakers.py (host or guest voice). Design and findings: docs/DESIGN_TOPIC_CUT.md; answer key: tests/data/topic_cut_starts_hks290969.json
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
- status: suspected: current behavior not re-proven after source drift; historical proof at commit 2ad7576 for the refusal path only (VERIFY.md live run 2026-09-28); success path on a real selection unproven

## Agent tools (MCP)
- what: Expose CutDeck to agents over MCP stdio: transcribe and `premiere_rough_cut` (the live sequence, no XML: panel read -> `prepare` -> `start`, then `premiere_apply_cuts`), job polling, and the `premiere_*` live commands.
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
- status: suspected: current behavior not re-proven after source drift; historical proof at commit 2ad7576 for `--help` (lists the ten commands); live commands need Premiere + panel and were not run this session

## Read a Premiere project
- what: Print a read-only JSON summary of a `.prproj` (tracks, mute state, clip disable), check anchors, and read pixels.
- cli: `python -m cutdeck.prproj_reader <project>` @ cutdeck/prproj_reader.py :: --sequence
- cli: `python -m cutdeck.prproj_anchor_check` @ cutdeck/prproj_anchor_check.py :: main
- cli: `python -m cutdeck.prproj_pixels` @ cutdeck/prproj_pixels.py :: main
- trace: `main` @ cutdeck/prproj_reader.py
- verify: Premiere project readers
- status: proven @ 2ad7576 for `prproj_reader --help`; not run on a project
