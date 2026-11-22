# Transform of selected clips

The panel's Transform tools act on the selected clips: set position, scale or rotation; move the
anchor to one of nine points while the picture stays put; align or distribute clips to the frame
or the selection, or the whole selection to the frame as one group.

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
Proven again 2026-11-22 (run `20261122-073257-pr115-gaps`, commit 924a926): rotation 7, Edit > Undo,
then anchor top-left wrote Position and Anchor [0, 0] with the frame unchanged to the pixel (the
earlier run wrote 0.112, -0.031 and moved it); crop-left 20 (left 20% of the frame transparent),
opacity 50 (alpha 128), and scale 50 + align left `to: "group"` (Position 0.25), each undone.

## Gotchas

- These tools act on the SELECTION in the active sequence, not on a named clip. Always select
  on the scratch first and clear the selection at the end, or the user's clips get edited.
- With nothing selected, `inspect_selection` lists every video clip; `has_selection` is the truth,
  not `selected_count`.
- `set_transform_field` takes position-x, position-y, scale, scale-width, uniform-scale (1/0),
  rotation, anchor-x, anchor-y, anti-flicker (0-1), crop-left/top/right/bottom (%) and opacity (%);
  `align_clips` `to` takes frame, selection or group. Anything else is refused before Premiere is touched.
- Edits read the clip's values fresh from Premiere, so an Edit > Undo or a change in Effect
  Controls just before is taken into account (before 2026-11-22 a cached read was used, and
  anchor after rotate + undo moved the picture).
