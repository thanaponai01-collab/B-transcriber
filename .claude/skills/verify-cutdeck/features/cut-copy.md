# Cut a copy (Rough Cut engine)

Cuts frame ranges out of a copy of a sequence, keeping every synced layer, effect and disabled
state; the source is never edited and the copy opens when done. Rough Cut's apply uses the same engine.

## Sub-features

- `copy` clones the source sequence under a new name.
- `cut` removes each frame range from every track and closes the gap.
- `open` makes the copy the active sequence.

## How to get to it (user POV)

- The CutDeck panel's Rough Cut, then apply.
- MCP tools `premiere_cut_copy`, or `premiere_rough_cut` then `premiere_apply_cuts`.

## Driving it with cdv.py

Preconditions:

- Baseline from the index. No sequence named `CutDeck verify cut` exists (`C call list_project '{"depth": 1}'`).

- **Cut.** Run `C call cut_copy '{"sequence_name": "CutDeck verify (scratch)", "result_name": "CutDeck verify cut", "cuts": {"ticks_per_frame": "8467200000", "cuts_frames": [[30, 60]]}}'`. Reply: `cuts` 1, `removed_seconds` 1.0, `undo_steps` N.
- **Read the copy.** Run `C call read_timeline '{"sequence": "CutDeck verify cut"}'`. `active` true and `end_ticks` 1270080000000 (6 s minus 30 frames).
- **Source untouched.** Run `C call read_timeline '{"sequence": "CutDeck verify (scratch)"}'`. Still one 6 s clip per track.
- **Remove the copy.** Run `C call menu_command '{"path": "Edit > Undo", "focus": null}'` N times (the `undo_steps` from the reply), then `C call list_project '{"depth": 1}'`. No `CutDeck verify cut`.

Not yet run with cdv.py. Proven 2026-11-21 on another scratch sequence (copy exactly 30 frames
shorter, copy active). Undoing the copy away is unproven: if it stays, report it to the user
(no API deletes a sequence).

## Gotchas

- `result_name` must not exist yet and must differ from the source.
- `ticks_per_frame` must be the source's own (`read_timeline` prints it): 8467200000 for the 30 fps scratch.
- The copy becomes the active sequence; `C cleanup` gives the user's sequence back.
