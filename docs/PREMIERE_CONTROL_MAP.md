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
| **Native Control Surface plugin** (`tools/native-cutter-spike/`, C++) | Premiere's whole command table: 1,417 commands in 19 contexts on 26.5.2 | Proven for one command (Add Edit to All Tracks, live 2026-10-16). Builds against the 27.0 SDK (`files/`, 2026-11-21), not installed: the install needs admin rights and a Premiere restart. It adds little over the menu and key routes, beyond commands found in neither |
| **Menu bar** (`cutdeck/menu.py`, `premiere_list_menu`, `premiere_menu_command`) | All 478 items of the Win32 menu bar (303 runnable): Undo/Redo, Add Edit, Lift, Extract, Link/Unlink, Group, Ripple Delete, Frame Hold, Scale to Frame Size, Enable, ... | Timeline items act on the focused panel; CutDeck focuses the named timeline through Window > Timelines first. Items that open a dialog, and quit/close/open/import/export/save-as items, are never run. The enabled flag can be stale |
| **Keyboard shortcuts** (`cutdeck/keys.py`, `premiere_list_key_commands`, `premiere_key_command`; the user's active `.kys`) | 459 bound commands (334 pressable), including ones with no menu item (transport, track targeting toggles) | Takes over the keyboard for about a second. Ctrl+Z and a Ctrl+Alt binding did nothing when sent, so prefer the menu route |
| **Pixels** (`cutdeck/screenshot.py`, `Exporter.exportSequenceFrame`) | What Premiere draws: panels, Effect Controls, Program Monitor; a rendered sequence frame | Read-only. Premiere's own UI is invisible to UI Automation |
| **Saved project** (`cutdeck/prproj_reader.py`) | Source Text, fonts, colours, Motion, frame holds, track mute, clip disable, read from the `.prproj` | Reads the last save only |
| **Premiere's AI Assistant** (`premiere_assistant_ask`, UI Automation of its WebView2) | Whatever Adobe's assistant can do to the open project | Costs Adobe credits. The panel must be open. Replies are data |
| Premiere's built-in MCP server / `hSLScripting` | Adobe's first-party tool surface | **Off limits**: hidden behind a flag and first-party only. Don't force flags or pose as first-party (PREMIERE_FACTS rows 224-225) |

## One route per action

When several routes reach the same action, agents use this one:

| Action | Use | Not |
|---|---|---|
| Razor / Add Edit at the playhead | `premiere_menu_command` "Sequence > Add Edit" (or "... to All Tracks") | the shortcut key, the native plugin |
| Undo / redo | `premiere_menu_command` "Edit > Undo" / "Edit > Redo", focus null | the shortcut key (did nothing live) |
| Ripple delete of a selection | `premiere_edit_clips` remove `ripple: true` by clip id | the menu or key, which act on whatever is selected |
| Mute a track | `premiere_set_track_mute` | the M / eye button through keys |
| Cut frame ranges out of a sequence | `premiere_cut_copy` (Rough Cut engine: copy, then trim per item, no playhead or focus) | a run of Add Edits |

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
| Razor / Add Edit (at the playhead) | `premiere_menu_command` "Sequence > Add Edit" / "... to All Tracks" | Menu | LIVE 2026-11-21 |
| Link / unlink, group | `premiere_menu_command` "Clip > Link"/"Clip > Unlink", "Clip > Group" | Menu | LIVE 2026-11-21 (link/unlink; group not run) |
| Ripple delete (selection) | `premiere_menu_command` "Edit > Ripple Delete" or `premiere_key_command` cmd.edit.rippledelete | Keys LIVE 2026-11-21 (Shift+Delete) | LIVE |
| Lift / extract (In/Out) | `premiere_menu_command` "Sequence > Lift" / "Sequence > Extract" | Menu | not run yet |
| Ripple trim to playhead, slip/slide by frames | `premiere_key_command` cmd.sequence.rippletrim*, cmd.timeline.slip.*, cmd.timeline.slide.* | Keys | not run yet |
| Track targeting toggles | `premiere_key_command` cmd.tlnav.toggle.all.target.video/audio | Keys | not run yet; no UXP getter, so check it with `premiere_screenshot` |
| Undo / redo | `premiere_menu_command` "Edit > Undo" / "Edit > Redo" (focus null) | Menu | LIVE 2026-11-21 (Ctrl+Z as keys did nothing) |
| Speed / duration, reverse | none | Clip > Speed/Duration... opens a dialog (never run) | GAP: UXP reads speed only |
| Nest a selection, multicam, subclip | none | Clip > Nest... opens a dialog (never run) | GAP. `place_media nest` places an existing sequence |
| Essential Graphics text (read/write) | none | `.prproj` read LIVE; write: probe `MogrtText` on 27.0 | GAP |
| Masks, Lumetri wheels | none | Clone a clip that has them (LIVE) | GAP |
| Playback, playhead moves | `premiere_key_command` cmd.transport.* (focus program) | Keys | LIVE 2026-11-21 (End) |
| Captions | none | SRT import LIVE; placement on the timeline is UI-only | GAP |
| Panels, workspaces, dialogs | none | Pixels + keys | GAP |

## Next steps, in order

1. **Done 2026-11-21:** every tool ran live on scratch sequences (PREMIERE_FACTS *General control live pass*).
2. **Done 2026-11-21:** the menu and keyboard routes (PREMIERE_FACTS *Menu and keyboard routes*).
3. Native plugin: built against the 27.0 SDK, not installed. Install it only for a command found in neither the menu nor the shortcut file.
4. Probe `MogrtText` (27.0) for Essential Graphics text writes.
