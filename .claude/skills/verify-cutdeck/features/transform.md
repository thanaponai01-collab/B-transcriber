# Transform of selected clips

The panel's Transform tools act on the selected clips: set position, scale, rotation, crop or
opacity; move the anchor to one of nine points while the picture stays put; align or distribute
clips to the frame or the selection.

## Sub-features

- `inspect` reads each selected clip's Motion values and sizes.
- `set-field` sets one transform field on every selected clip.
- `anchor` moves the anchor point keeping the picture in place.
- `align` aligns edges or centres to frame, selection or as a group.

## How to get to it (user POV)

- The CutDeck panel's Transform page.
- MCP tools `premiere_select_clips` then `premiere_inspect_selection`, `premiere_set_transform_field`, `premiere_set_anchor`, `premiere_align_clips`.

## Driving it with cdv.py

Preconditions:

- Baseline from the index. Nothing selected in any other sequence.

- **Select.** Run `C call select_clips '{"sequence": "CutDeck verify (scratch)", "clips": ["V1@0"]}'`. The reply's `selected` is `["V1@0"]`.
- **Inspect.** Run `C call inspect_selection --label before`. One item, `transform.rotation.value` 0, `source_size` 1080x1920.
- **Set.** Run `C call set_transform_field '{"field": "rotation", "value": 7}'` then `C call inspect_selection --label after`. `done` 1 and rotation 7. `C shot rotated --frame` shows the bars tilted.
- **Undo.** Run `C call menu_command '{"path": "Edit > Undo", "focus": null}'` then `C call inspect_selection --label undone`. Rotation 0.
- **Deselect.** Run `C call select_clips '{"sequence": "CutDeck verify (scratch)", "clips": []}'`.

Proven 2026-11-21 (select, set rotation 7, undo to 0) through the helper; not yet run with cdv.py.

## Gotchas

- These tools act on the SELECTION in the active sequence, not on a named clip. Always select
  on the scratch first and clear the selection at the end, or the user's clips get edited.
- With nothing selected, `inspect_selection` lists every video clip; `has_selection` is the truth,
  not `selected_count`.
- `set_transform_field` accepts only position-x, position-y, scale, rotation, anchor-x, anchor-y.
