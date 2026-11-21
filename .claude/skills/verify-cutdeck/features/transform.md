# Transform of selected clips

The panel's Transform tools act on the selected clips: set position, scale or rotation; move the
anchor to one of nine points while the picture stays put; align or distribute clips to the frame
or the selection. (The panel page itself also sets crop and opacity; the agent tools do not.)

## Sub-features

- `inspect` reads each selected clip's Motion values and sizes.
- `set-field` sets one transform field on every selected clip.
- `anchor` moves the anchor point keeping the picture in place.
- `align` aligns edges or centres to the frame or to the selection.
- `distribute` spaces three or more selected clips evenly.

## How to get to it (user POV)

- The CutDeck panel's Transform page.
- MCP tools `premiere_select_clips` then `premiere_inspect_selection`, `premiere_set_transform_field`, `premiere_set_anchor`, `premiere_align_clips`, `premiere_distribute_clips`.

## Driving it with cdv.py

Preconditions:

- Baseline from the index. Nothing selected in any other sequence.

- **Select.** Run `C call select_clips '{"sequence": "CutDeck verify (scratch)", "clips": ["V1@0"]}'`. The reply's `selected` is `["V1@0"]`.
- **Inspect.** Run `C call inspect_selection --label before`. One item, `transform.rotation.value` 0, `source_size` 1080x1920.
- **Set.** Run `C call set_transform_field '{"field": "rotation", "value": 7}'` then `C call inspect_selection --label after`. `done` 1 and rotation 7. `C shot rotated --frame` shows the bars tilted.
- **Undo.** Run `C call menu_command '{"path": "Edit > Undo", "focus": null}'` then `C call inspect_selection --label undone`. Rotation 0.
- **Align.** Run `C call set_transform_field '{"field": "scale", "value": 50}'`, then `C call align_clips '{"edge": "left", "to": "frame"}'`, then `C call inspect_selection`. Position reads `[0.25, 0.5]` (the half-size clip's left edge on the frame's). Undo twice; Position `[0.5, 0.5]`, Scale 100.
- **Deselect.** Run `C call select_clips '{"sequence": "CutDeck verify (scratch)", "clips": []}'`.

Proven 2026-11-22 with this skill (run `20261122-000256-maintain-timeline`): select, inspect, rotation 7 and undo, scale 50 + align left to frame and undo, deselect. Distribute was not driven (needs three clips).

## Gotchas

- These tools act on the SELECTION in the active sequence, not on a named clip. Always select
  on the scratch first and clear the selection at the end, or the user's clips get edited.
- With nothing selected, `inspect_selection` lists every video clip; `has_selection` is the truth,
  not `selected_count`.
- `set_transform_field` accepts only position-x, position-y, scale, rotation, anchor-x, anchor-y;
  `align_clips` `to` only frame or selection. Anything else is refused before Premiere is touched.
