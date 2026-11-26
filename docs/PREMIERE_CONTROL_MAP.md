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

Every route has one way in: `Backend().premiere(command, args)` (or `python -m cutdeck.premiere_cli`,
or the `premiere_<command>` MCP tool) asks the helper, and the helper runs the command from the one
table `cutdeck/driver_commands.py`. Panel commands go on to the CutDeck panel; the menu, keyboard,
window-pixel and AI Assistant commands run in the helper itself, which reaches the panel through
the same table when it needs a sequence opened or read.

| Route | Reaches | Limits |
|---|---|---|
| **UXP panel API** (CutDeck panel, `features/driver.js` + `timeline/control.js`) | Everything in `reference/adobe/api/premierepro.txt`: project, bins, sequences, tracks, clips, effects, keyframes, markers, export | Third-party allow-list: no razor (until 27.1), link/unlink, track targeting, nesting of a selection, undo, panel focus, Essential Graphics text in place (`MogrtText` reads AE-template text, its write blanks the layer on 27.0), masks |
| **Native Control Surface plugin** (`tools/native-cutter-spike/`, C++) | Premiere's whole command table: 1,417 commands in 19 contexts on 26.5.2 | Proven for one command (Add Edit to All Tracks, live 2026-10-16). Builds against the 27.0 SDK (`files/`, 2026-11-21), not installed: the install needs admin rights and a Premiere restart. It adds little over the menu and key routes, beyond commands found in neither |
| **Menu bar** (`cutdeck/menu.py`, `premiere_list_menu`, `premiere_menu_command`) | All 478 items of the Win32 menu bar (303 runnable): Undo/Redo, Add Edit, Lift, Extract, Link/Unlink, Group, Ripple Delete, Frame Hold, Scale to Frame Size, Enable, ... | Timeline items act on the focused panel; CutDeck focuses the named timeline through Window > Timelines first. Items that open a dialog, and quit/close/open/import/export/save-as items, are never run. The enabled flag can be stale |
| **Keyboard shortcuts** (`cutdeck/keys.py`, `premiere_list_key_commands`, `premiere_key_command`; the user's active `.kys`) | 459 bound commands (334 pressable), including ones with no menu item (transport, track targeting toggles) | Takes over the keyboard for about a second. Ctrl+Z and a Ctrl+Alt binding did nothing when sent, so prefer the menu route |
| **Pixels** (`cutdeck/screenshot.py`, `Exporter.exportSequenceFrame`) | What Premiere draws: panels, Effect Controls, Program Monitor; a rendered sequence frame | Read-only. Premiere's own UI is invisible to UI Automation |
| **Premiere UI** (`cutdeck/premiere_ui.py`: dialogs, mouse and typing, approved by the user 2026-11-21) | Speed/Duration and Nest dialogs; typing into a text layer in the Program Monitor | Takes the mouse and keyboard for seconds. Each step is gated on what is in front and read back from pixels; a failure presses nothing more |
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
| Hear the timeline: what is said where, cuts that land in sound, speech the engine dropped (from each source's one transcript, no re-listening) | `premiere_timeline_transcript` | UXP read + helper | LIVE 2026-11-22 |
| Cut words out (each cut in the pause; read back) | `premiere_cut_words` | helper + `cut_copy` | LIVE 2026-11-22 |
| Clean speech on a copy: cut fillers, repeats, restarts in their pauses; mark what needs a call (`apply: false` lists it all with context) | `premiere_clean_speech` | helper + `cut_copy` + `add_markers` | dry run LIVE 2026-11-25; apply LIVE 2026-11-26 |
| Plan a Short by its words (piece edges in the source's pauses; items for build) | `premiere_plan_pieces` | helper | LIVE 2026-11-22 |
| Keep only these phrases on a copy, every track kept (a Short from a synced rough cut) | `premiere_keep_words` | helper + `cut_copy` | LIVE 2026-11-22 |
| A range of a sequence as its own sequence, every track and effect (Make Subsequence) | `premiere_make_subsequence` | UXP | LIVE 2026-11-24 |
| Copy several pieces of one sequence into another, in play order (a Short from yt, hook pieces into a draft, a pool from a split): into an existing sequence in place, or a new copy of a 9:16 template; every track, effect and Graphic kept, fixed cost whatever the piece count, never piece by piece | `premiere_paste_pieces` | helper: `make_subsequence` + `cut_copy` + `arrange` (4 steps) + one `paste_from` + `remove_piece`, saves before and after | LIVE 2026-11-26 |
| Make a new empty project (scratch work the user asked for) | `premiere_create_project` | UXP `Project.createProject` | LIVE 2026-11-26 |
| Take a range of one sequence (split, backup pool, YT cut) into another at a time, every track and effect kept, overwriting (a third paste into one target needs `per_piece_reason`) | `premiere_paste_from` | helper: `make_subsequence` + menu Copy/Paste + `build_sequence` into + `remove_piece` | LIVE 2026-11-24 |
| Reorder pieces of a sequence on a copy, every track and effect kept (blocks in play order) | `premiere_arrange` | helper: `duplicate_sequence` + `build_sequence` into | LIVE 2026-11-24 |
| Delete a piece sequence `paste_from` kept (name ends ` (CutDeck piece)`) | `premiere_remove_piece` | UXP | LIVE 2026-11-24 |
| Active sequence summary | `premiere_read_sequence` | UXP | LIVE |
| Open / switch sequence | `premiere_open_sequence` | UXP | LIVE 2026-11-21 |
| Delete rough-cut copies (CutDeck > Rough Cuts only, never the active one) | `premiere_remove_rough_cuts` | UXP `FolderItem.createRemoveItemAction` | LIVE 2026-11-22 |
| Playhead | `premiere_set_playhead` | UXP | LIVE 2026-11-21 |
| In/Out marks | `premiere_set_in_out` | UXP | LIVE 2026-11-21 |
| Select clips | `premiere_select_clips` | UXP `setSelection` | LIVE 2026-11-21 |
| Move, trim head/tail, enable/disable, rename, remove (ripple or not) | `premiere_edit_clips` | UXP | LIVE 2026-11-21 (ripple: video and audio in one action, else it shifts twice) |
| Place media / nest a sequence, overwrite or insert | `premiere_place_media` | UXP | LIVE 2026-11-21 (nest across frame size/rate placed nothing: now an error) |
| Import files | `premiere_import_files` | UXP | LIVE 2026-11-21 |
| Import sequences (by GUID) from a saved `.prproj`; a donor copy from `python -m cutdeck.prproj_donor` | `premiere_import_sequences` | UXP `Project.importSequences` | LIVE 2026-11-23 (a patched Motion Scale read back; issue #130) |
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
| Lift / extract (In/Out) | `premiere_menu_command` "Sequence > Lift" / "Sequence > Extract" | Menu | LIVE 2026-11-21 (In/Out 1-2 s: Lift left a gap on V1+A1, Extract rippled both; one Undo each restored) |
| Ripple trim to playhead, slip/slide by frames | `premiere_key_command` cmd.sequence.rippletrim*, cmd.timeline.slip.*, cmd.timeline.slide.* | Keys | ripple trim LIVE 2026-11-21 (W at 4 s cut V1+A1 to end at 4 s; Undo restored); slip (Ctrl+Alt+←/→) and slide (Alt+, / Alt+.) by frame on the selected clip LIVE 2026-11-25 |
| Freeze a frame from the playhead (still person for a J/L hold) | `premiere_menu_command` "Clip > Video Options > Add Frame Hold" (clip selected with `premiere_select_clips`, playhead set) | Menu | LIVE 2026-11-25 (no ripple; Insert Frame Hold Segment ripples all tracks) |
| Roll an edit by frames | `premiere_menu_command` "Sequence > Trim Edit" + `premiere_key_command` cmd.sequence.trimforward / trimbackward | Menu + Keys | LIVE 2026-11-25 (only tracks with an edit there; one Undo per frame) |
| Slip, ripple extend, J/L split edit, audio fade | `premiere_edit_clips` trims/moves per clip; `premiere_set_param` Volume keyframes | UXP | LIVE 2026-11-25 (recipes in PREMIERE_FACTS) |
| Extend/ripple an edit to the playhead | keys Shift+Q/W, Q/W | Keys | CATCH 2026-11-25: act on every targeted track, covers included; avoid on layered timelines |
| Close Gap (menu) | none | Menu | did nothing 2026-11-25; use `premiere_edit_clips` |
| Match Frame (source frame of the clip under the playhead) | `premiere_menu_command` "Sequence > Match Frame" | Menu | LIVE 2026-11-25 (Source monitor at the exact frame, clip range marked) |
| Three-point overwrite / insert from the Source monitor | `premiere_key_command` cmd.clip.overlay (.) / cmd.clip.insert (,) | Keys | overwrite LIVE 2026-11-25 with the range Match Frame marked; setting source In/Out by key unproven |
| Paste Insert, labels, range markers, Mark Clip, volume ±1 dB, next/prev edit | menu Edit > Paste Insert, Edit > Label > *, Markers > *, keys ] [ and Shift+↓/↑ | Menu + Keys | LIVE 2026-11-25 (PREMIERE_FACTS) |
| Track lock | key cmd.timeline.togglelockvideotracks | Keys | CATCH 2026-11-25: the API ignores locks and can't read them |
| Track targeting toggles | `premiere_key_command` cmd.tlnav.toggle.all.target.video/audio | Keys | LIVE 2026-11-25 (untargeted video: Add Edit cut A1 only); no UXP getter, check with `premiere_screenshot` |
| Undo / redo | `premiere_menu_command` "Edit > Undo" / "Edit > Redo" (focus null) | Menu | LIVE 2026-11-21 (Ctrl+Z as keys did nothing) |
| Speed / duration, reverse, ripple | `premiere_set_speed` | Premiere UI: fills the Clip > Speed/Duration... dialog | LIVE 2026-11-21 (200%, 50% + reverse, back to 100%; Undo restores) |
| Nest a selection | `premiere_nest_clips` | Premiere UI: fills the Clip > Nest... dialog | LIVE 2026-11-21 (Thai name; Undo removes clip and sequence) |
| Copy one clip's effects onto many (Paste Attributes) | `premiere_paste_attributes` | Premiere UI: Edit > Copy, then fills Edit > Paste Attributes... | LIVE 2026-11-22, also through MCP (744 clips in 24 s; one Undo reverts; a clip that already has the effect gets it twice) |
| Multicam, subclip | none | dialogs, same route as Nest | GAP |
| Place a text Graphic with your own text (Thai too), from any .mogrt | `premiere_place_text` | Helper bakes the text into a copy of the template, UXP `insertMogrtFromPath` | LIVE 2026-11-21 (Thai into Premiere's Basic Title and an AE template; frames + read-back; a wrong key lists the texts) |
| Read MOGRT text | `premiere_read_timeline` (`params: true`: `{text, font, size}`) | UXP `MogrtText` | After Effects templates; Premiere-made text reads null in UXP, read it from the saved `.prproj` (`prproj_reader`) |
| Edit the text of a Graphic already on the timeline | `premiere_edit_text` | Premiere UI: double-click in the Program Monitor, type (UXP `MogrtText` write is BROKEN) | LIVE 2026-11-21 on a one-line Premiere-made text; AE-template text still via `place_text` |
| Masks, Lumetri (onto another sequence) | `python -m cutdeck.prproj_donor --effect` (copy the effect from a clip that has it), `premiere_import_sequences`, then `premiere_select_clips` + `premiere_menu_command` Edit > Copy / Edit > Paste (`premiere_set_playhead` first) | Offline .prproj + UXP import + Menu | LIVE 2026-11-23 (masked blur box and Lumetri params read back on the target; issue #130). Inside one sequence: clone. Editing a mask's shape: GAP |
| Playback, playhead moves | `premiere_key_command` cmd.transport.* (focus program) | Keys | LIVE 2026-11-21 (End) |
| Subtitles from an .srt as styled, editable Graphics (captions + Upgrade Caption to Graphic) | `premiere_srt_subtitles` | UXP import + Premiere UI drag and dialog + menu + UXP build | LIVE 2026-11-22 (4 cues in 13 s, frame-exact, the user's Style and place) |
| Other caption editing | none | UI only | GAP |
| Panels, workspaces, dialogs | none | Pixels + keys | GAP |

## Next steps, in order

1. **Done 2026-11-21:** every tool ran live on scratch sequences (PREMIERE_FACTS *General control live pass*).
2. **Done 2026-11-21:** the menu and keyboard routes (PREMIERE_FACTS *Menu and keyboard routes*).
3. Native plugin: built against the 27.0 SDK, not installed. Install it only for a command found in neither the menu nor the shortcut file.
4. **Done 2026-11-21:** `MogrtText` probed on 27.0 (reads AE text; write BROKEN). Text goes in through `place_text` (baked template).
