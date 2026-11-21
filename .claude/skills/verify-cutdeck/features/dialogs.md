# Premiere dialogs: speed and nest

An agent changes clip speed (with reverse and ripple) and nests clips into a new sequence by
filling Premiere's own Clip > Speed/Duration and Clip > Nest dialogs, the only route to these
(the user approved driving dialogs, 2026-11-21).

## Sub-features

- `speed` sets speed in percent, reverse and ripple for the given clips.
- `nest` replaces the given clips with one nested clip of a chosen name.

## How to get to it (user POV)

- MCP tools `premiere_set_speed` and `premiere_nest_clips`.
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
- `premiere_cli` cannot pass these commands' arguments; use `C call` or `Backend().premiere`.
