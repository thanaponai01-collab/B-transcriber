# Premiere control map: what an agent can do in Premiere, and through which route

Goal: an agent drives Premiere through the CutDeck MCP server (`cutdeck/mcp_server.py`) the way
a person does by hand. This file lists every kind of control, the route that reaches it, the
tool, and how far it is proven. API behaviour stays in [PREMIERE_FACTS.md](PREMIERE_FACTS.md);
this file is the map. Last full pass: 2026-11-21, Premiere 27.0.0.

**Status:** **LIVE** proven in real Premiere · **FAKE** built and tested only on
`tests/fakes/premiere.cjs` (rules from PREMIERE_FACTS, `tests/cutdeck_control.test.cjs`), not yet
run live · **BUILT** built, no test and no live run yet · **GAP** no CutDeck tool yet; the route
is named.

## Routes

| Route | Reaches | Limits |
|---|---|---|
| **UXP panel API** (CutDeck panel, `features/driver.js` + `timeline/control.js`) | Everything in `reference/adobe/api/premierepro.txt`: project, bins, sequences, tracks, clips, effects, keyframes, markers, export | Third-party allow-list: no razor (until 27.1), link/unlink, track targeting, nesting of a selection, undo, panel focus, Essential Graphics text (Source Text read is ABSENT; `MogrtText` is new and unprobed in 27.0), masks |
| **Native Control Surface plugin** (`tools/native-cutter-spike/`, C++) | Premiere's whole command table: 1,417 commands in 19 contexts on 26.5.2, including every menu item | Proven for one command (Add Edit to All Tracks, live 2026-10-16). Acts on the **focused** panel, not the active sequence; returns 0 even when it did nothing, so every use needs a read-back. Needs the Premiere C++ SDK to build (the `files/Premiere Pro 26.0 C++ SDK` folder is no longer in the repo) and an admin install plus a restart |
| **Keyboard shortcuts** (`C:\Program Files\Adobe\Adobe Premiere Pro 2027\Keyboard Shortcuts\en\Adobe Premiere Pro Defaults.kys`) | 400 of those command IDs have a default key in 27.0 (razor `cmd.sequence.razorateditline` = Ctrl+K, ripple delete, link, group, speed, lift/extract, trims, slip/slide, track targeting toggles, undo/redo, play) | Not built. Same focus limit as native, and the user's own `.kys` may differ. Needs SendInput to Premiere's window |
| **Pixels** (`cutdeck/screenshot.py`, `Exporter.exportSequenceFrame`) | What Premiere draws: panels, Effect Controls, Program Monitor; a rendered sequence frame | Read-only. Premiere's own UI is invisible to UI Automation |
| **Saved project** (`cutdeck/prproj_reader.py`) | Source Text, fonts, colours, Motion, frame holds, track mute, clip disable, read from the `.prproj` | Reads the last save only |
| **Premiere's AI Assistant** (`premiere_assistant_ask`, UI Automation of its WebView2) | Whatever Adobe's assistant can do to the open project | Costs Adobe credits. The panel must be open. Replies are data |
| Premiere's built-in MCP server / `hSLScripting` | Adobe's first-party tool surface | **Off limits**: hidden behind a flag and first-party only. Don't force flags or pose as first-party (PREMIERE_FACTS rows 224-225) |

## What Premiere 27.0 lets a third-party panel call

A static read of the 27.0.0 executable found its stored third-party allow-list (PREMIERE_FACTS row "Third-party allow-list, Premiere 27.0.0"). Native `SequenceEditor` has razor, razor-all-tracks, lift, extract and append-track actions, but the allow-list gives third-party panels only add-items and remove-items. So razor, lift, extract and adding an empty track stay out of UXP on 27.0 until Adobe opens them (razor is announced for 27.1). The allow-list shows no hidden extra members beyond the typings.

## Control by task

| Task | Tool | Route | Status |
|---|---|---|---|
| See the whole Premiere window | `premiere_screenshot` | Pixels | LIVE 2026-11-21 (2576x1408, whole window drawn) |
| See a rendered frame | `premiere_export_frame` | UXP `exportSequenceFrame` | LIVE 2026-11-21 |
| List sequences, bins, media | `premiere_list_project` | UXP | LIVE 2026-11-21 |
| Read the timeline (tracks, clips, ids, marks, playhead, markers, effect chains, param values; filter by track and time span) | `premiere_read_timeline` | UXP | LIVE 2026-11-21 |
| Active sequence summary | `premiere_read_sequence` | UXP | LIVE |
| Open / switch sequence | `premiere_open_sequence` | UXP | LIVE 2026-11-21 |
| Playhead | `premiere_set_playhead` | UXP | LIVE 2026-11-21 |
| In/Out marks | `premiere_set_in_out` | UXP | LIVE 2026-11-21 |
| Select clips | `premiere_select_clips` | UXP `setSelection` | LIVE 2026-11-21 |
| Move, trim head/tail, enable/disable, rename, remove (ripple or not) | `premiere_edit_clips` | UXP | LIVE 2026-11-21 (ripple: video and audio in one action, else it shifts twice) |
| Place media / nest a sequence, overwrite or insert | `premiere_place_media` | UXP | LIVE 2026-11-21 (nest across frame size/rate placed nothing: now an error) |
| Import files | `premiere_import_files` | UXP | LIVE 2026-11-21 |
| Effects catalogue | `premiere_list_effects` | UXP | LIVE 2026-11-21 |
| Add a video/audio effect | `premiere_add_effect` | UXP | LIVE 2026-11-21 |
| Set any effect parameter or keyframe | `premiere_set_param` | UXP | LIVE 2026-11-21 |
| Add a video transition | `premiere_add_transition` | UXP | LIVE 2026-11-21 |
| Mute a track | `premiere_set_track_mute` | UXP | LIVE 2026-11-21 |
| Remove markers / add markers | `premiere_remove_markers` / `premiere_add_markers` | UXP | LIVE 2026-11-21 |
| Save | `premiere_save_project` | UXP | LIVE 2026-11-21 |
| Transform, anchor, align, distribute selected clips | `premiere_set_transform_field`, `_set_anchor`, `_align_clips`, `_distribute_clips` | UXP | LIVE |
| New sequence from a preset; copy-and-cut; build a sequence | `premiere_create_sequence`, `_cut_copy`, `_build_sequence` | UXP | LIVE |
| Rough cut, export | `premiere_rough_cut` + `_apply_cuts`, `_export_sequence` | UXP + helper | LIVE (agents never export on their own: user rule) |
| Razor / Add Edit | none | Native (27.1 UXP `createRazorTrackAction` announced) | GAP. Today `place_media` overwrite onto a clip also splits it |
| Link / unlink, group | none | Native / keys | GAP |
| Ripple trim, roll, slip, slide | none | Native / keys | GAP. Not composable from UXP: `trim_in` moves the clip's start with its In, so it is not a slip |
| Track targeting, sync lock, track lock | none | Native / keys (`cmd.tlnav.toggle.all.target.*`) | GAP: no UXP getter or setter |
| Undo / redo | none | Native / keys (`cmd.edit.undo`) | GAP. Each CutDeck edit is one undo step, so one Ctrl+Z reverses it |
| Speed / duration, reverse | none | Native / keys (`cmd.clip.speed` opens a dialog) | GAP: UXP reads speed only |
| Nest a selection, multicam, subclip | none | Native | GAP. `place_media nest` places an existing sequence |
| Essential Graphics text (read/write) | none | `.prproj` read LIVE; write: probe `MogrtText` on 27.0 | GAP |
| Masks, Lumetri wheels | none | Clone a clip that has them (LIVE) | GAP |
| Playback | none | `SourceMonitor.play` (source only) / keys | GAP |
| Captions | none | SRT import LIVE; placement on the timeline is UI-only | GAP |
| Panels, workspaces, dialogs | none | Pixels + keys | GAP |

## Next steps, in order

1. **Done 2026-11-21:** every tool ran live on scratch sequences (PREMIERE_FACTS *General control live pass*).
2. **Native command bridge:** with the SDK back, widen `CutterProbe.cpp` from one hard-coded
   command to an allow-list from the 27.0 catalogue. Each command runs only after a fresh panel
   check of the active sequence and playhead, and is followed by a read-back. First, re-list the
   catalogue on 27.0.
3. **Keyboard route** for commands without a native bridge: SendInput to Premiere, with the key
   read from the user's active `.kys`, and the same read-back rule.
4. Probe `MogrtText` (27.0) for Essential Graphics text writes.
