# Premiere dialogs: speed, nest and paste attributes

An agent changes clip speed (with reverse and ripple) and nests clips into a new sequence by
filling Premiere's own Clip > Speed/Duration and Clip > Nest dialogs, the only route to these
(the user approved driving dialogs, 2026-11-21).

## Sub-features

- `speed` sets speed in percent, reverse and ripple for the given clips.
- `nest` replaces the given clips with one nested clip of a chosen name.
- `paste attributes` copies one clip's Motion, Opacity and effects onto many clips (Edit > Copy, Edit > Paste Attributes...) and reads every clip back against the source.

## How to get to it (user POV)

- MCP tools `premiere_set_speed`, `premiere_nest_clips` and `premiere_paste_attributes`.
- `premiere_read_timeline` shows each clip's `speed` and `reversed`.

## Driving it with cdv.py

Preconditions:

- Baseline from the index. Premiere is not minimised; nobody types during the call (it takes the keyboard).

- **Speed.** `C call set_speed '{"sequence": "CutDeck verify (scratch)", "clips": ["V1@0", "A1@0"], "speed": 200, "reverse": true}'`. Reply `selected_after`: `V1@0` and `A1@0` end at 762048000000, `speed` 2, `reversed` true.
- **Undo.** One Undo; a read shows both clips 6 s, speed 1, `reversed` false.
- **Nest.** `C call nest_clips '{"sequence": "CutDeck verify (scratch)", "clips": ["V1@0", "A1@0"], "name": "CutDeck verify nest"}'`. Reply `nested`: `V1@0` and `A1@0` named `CutDeck verify nest`.
- **Undo.** One Undo; the original clips are back and `list_project` has no `CutDeck verify nest` sequence (the count of `sequences` is as before).

Proven 2026-11-22 with this skill, every step above (run `20261122-000256-maintain-timeline`).

## Gotchas

- A failed fill presses Escape on the dialog and nothing more; doctor afterwards.
- The checkbox positions were measured on a 488x437 dialog at 96 DPI; another size is refused.
- **Paste attributes** (not yet run through cdv.py; proven 2026-11-22 directly and as the MCP tool over stdio): give the scratch's V1@0 an effect with `add_effect`, split it, then `C call paste_attributes '{"sequence": "CutDeck verify (scratch)", "source": "V1@0", "clips": [...]}'`. Reply `differ` is empty. One Undo removes it.
- Paste Attributes adds a second copy of an effect a target already has; the dialog measurements are for 402x811 at 96 DPI.
- `premiere_cli` cannot pass these commands' arguments; use `C call` or `Backend().premiere`.
