# Timeline editing

An agent reads a sequence the way the timeline shows it and edits clips the way a person does by
hand (select, move, trim, enable/disable, rename, remove), each edit one undo step.

## Sub-features

- `read` lists tracks, clips (id, times, media, disabled), marks, playhead and markers.
- `select` replaces the timeline selection with clip ids.
- `disable` / `enable` toggles a clip's output.
- `trim` moves a clip's In or Out (media time).
- `remove` deletes clips, optionally rippling.
- `undo` reverses the last edit through the menu.

## How to get to it (user POV)

- MCP tools `premiere_read_timeline`, `premiere_select_clips`, `premiere_edit_clips`.
- `python -m cutdeck.premiere_cli read_timeline`.
- Edit > Undo in Premiere, or `premiere_menu_command "Edit > Undo"`.

## Driving it with cdv.py

Preconditions:

- Baseline from the index: scratch holds `V1@0` and `A1@0`, open.

- **Read.** Run `C call read_timeline '{"sequence": "CutDeck verify (scratch)", "tracks": ["V1","A1"]}' --label before`. V1 and A1 each list one clip, `end_ticks` 1524096000000, `disabled` false.
- **Frame before.** Run `C call set_playhead '{"sequence": "CutDeck verify (scratch)", "ticks": "762048000000"}'` then `C shot enabled --frame`. The frame PNG shows colour bars with `00:00:03.000` and `90` in the corner.
- **Disable.** Run `C call edit_clips '{"sequence": "CutDeck verify (scratch)", "edits": [{"clip": "V1@0", "op": "disable"}]}' --label disable`. The reply's `tracks_after` shows `V1@0` with `disabled: true`.
- **Frame after.** Run `C shot disabled --frame`. The frame PNG is empty (transparent, shows white).
- **Undo.** Run `C call menu_command '{"path": "Edit > Undo", "focus": null}' --label undo`, then `C call read_timeline '{"sequence": "CutDeck verify (scratch)", "tracks": ["V1"]}' --label after-undo`. `V1@0` reads `disabled: false`.
- **Trim.** Run `C call edit_clips '{"sequence": "CutDeck verify (scratch)", "edits": [{"clip": "V1@0", "op": "trim_out", "out_ticks": "762048000000"}]}'`. `V1@0` ends at 762048000000; A1 is unchanged (linked audio does not follow). Undo and read back.
- **Remove.** Run `C call edit_clips '{"sequence": "CutDeck verify (scratch)", "edits": [{"clip": "V1@0", "op": "remove"}, {"clip": "A1@0", "op": "remove"}]}'`. V1 and A1 are empty. Undo and read back both clips.

Proven 2026-11-21 with this skill: read, disable, frame before/after, undo (run `20261121-224619-prove`); trim and undo (run `20261121-224911-timeline-editing`).

## Gotchas

- A clip id is its start time: after a move or head trim, re-read to get the new id.
- Linked audio does NOT follow a video move or trim. Edit the A clip too.
- Ripple remove did not close the gap on a sequence whose other tracks had clips across it
  (PREMIERE_FACTS CATCH row, 2026-11-21). On the one-clip scratch there is nothing to ripple, so
  ripple needs a second clip placed after `V1@0` (`place_media` at 1524096000000) to prove anything.
- An empty frame PNG is transparent; it looks white, not black.
