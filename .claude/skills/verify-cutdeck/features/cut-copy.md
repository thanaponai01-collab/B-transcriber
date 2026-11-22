# Cut a copy (Rough Cut engine)

Cuts frame ranges out of a copy of a sequence, keeping every synced layer, effect and disabled
state; the source is never edited and the copy opens when done. Rough Cut's apply uses the same engine.

## Sub-features

- `copy` clones the source sequence under a new name, filed in the project's CutDeck > Rough Cuts
  bin (created if missing).
- `cut` removes each frame range from every track and closes the gap.
- `open` makes the copy the active sequence.

## How to get to it (user POV)

- The CutDeck panel's Rough Cut, then apply.
- MCP tools `premiere_cut_copy`, or `premiere_rough_cut` then `premiere_apply_cuts`.

## Driving it with cdv.py

Preconditions:

- Baseline from the index. No sequence named `CutDeck verify cut` exists: `C call list_project '{"depth": 1}'`, and note the number of `sequences`.

- **Cut.** Run `C call cut_copy '{"sequence_name": "CutDeck verify (scratch)", "result_name": "CutDeck verify cut", "cuts": {"ticks_per_frame": "8467200000", "cuts_frames": [[30, 60]]}}'`. Reply: `cuts` 1, `removed_seconds` 1.0, `undo_steps` N.
- **Read the copy.** Run `C call read_timeline '{"sequence": "CutDeck verify cut"}'`. `active` true and `end_ticks` 1270080000000 (6 s minus 30 frames).
- **Source untouched.** Run `C call read_timeline '{"sequence": "CutDeck verify (scratch)"}'`. Still one 6 s clip per track.
- **Remove the copy.** Run `C call menu_command '{"path": "Edit > Undo", "focus": null}'` N + 3 times (`undo_steps` from the reply, plus copy, rename and file-in-bin; one more for each bin the run created). Then `C call list_project '{"depth": 1}'` lists the same number of `sequences` as before, with no `CutDeck verify cut` and no `CutDeck verify (scratch) Copy`. After N + 2 undos the copy is only renamed back to `... Copy`, so check the count, not just the name.

Proven 2026-11-22 with this skill (run `20261122-000256-maintain-timeline`): `undo_steps` 5, copy
active and 1270080000000 long, source untouched, and 8 undos (5 + 3; the bins already existed)
left the project with the same 14 sequences as before. If a copy ever stays, tell the user: no
API deletes a sequence.

## Gotchas

- `result_name` must differ from the source and from every sequence already in the project
  (refused otherwise, before anything is copied; live 2026-11-22, run `20261122-073257-pr115-gaps`:
  "already exists", project item count unchanged).
- A run that fails mid-way leaves its copy in the project renamed `<result_name> (FAILED)`.
- `ticks_per_frame` must be the source's own (`read_timeline` prints it): 8467200000 for the 30 fps scratch.
- The copy becomes the active sequence; `C cleanup` gives the user's sequence back.
