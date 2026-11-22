# Effects, parameters and transitions

An agent adds an effect to clips, sets any effect parameter as in Effect Controls (or keyframes
it), and adds a video transition, each one undo step.

## Sub-features

- `list` lists every video effect (match name + display name), audio effect and video transition.
- `add` appends an effect to clips and returns their component chains.
- `set` sets one parameter by component (index or match name) and parameter index.
- `transition` adds a video transition to the end (default) or start of clips.

## How to get to it (user POV)

- MCP tools `premiere_list_effects`, `premiere_add_effect`, `premiere_set_param`, `premiere_add_transition`.
- Read parameters with `premiere_read_timeline` `effects: "params"`.

## Driving it with cdv.py

Preconditions:

- Baseline from the index.

- **List.** Run `C call list_effects`. About 115 video effects, including `AE.ADBE Tint`; transitions include `AE.ADBE Cross Dissolve New`.
- **Add.** Run `C call add_effect '{"sequence": "CutDeck verify (scratch)", "clips": ["V1@0"], "effect": "AE.ADBE Tint"}'`. The chain reads 0 Opacity, 1 Motion, 2 `AE.ADBE Tint`.
- **Set.** Run `C call set_param '{"sequence": "CutDeck verify (scratch)", "clip": "V1@0", "component": "AE.ADBE Tint", "param": 2, "value": 50}'` (param 2 is Amount to Tint, default 100). Then `C call read_timeline '{"sequence": "CutDeck verify (scratch)", "tracks": ["V1"], "effects": "params"}'`: Amount to Tint 50.
- **Undo.** Undo twice; a read with `effects: "names"` shows only Opacity and Motion.
- **Transition.** Run `C call set_playhead '{"sequence": "CutDeck verify (scratch)", "ticks": "1507161600000"}'` (2 frames before the end) and `C shot end-before --frame`, then `C call add_transition '{"sequence": "CutDeck verify (scratch)", "clips": ["V1@0"], "transition": "AE.ADBE Cross Dissolve New"}'` and `C shot end-dissolve --frame`. The frame's mean alpha drops from 255 to about 17 (the clip fades out). Undo; the frame is opaque again.

Proven 2026-11-22 with this skill, every step above (run `20261122-000256-maintain-timeline`).

## Gotchas

- `read_timeline` does not list transitions; prove one from the frame.
- Point parameters (Position, Anchor) take `[x, y]` as fractions of the sequence frame.
- `at_ticks` on `set_param` is MEDIA time (like `in_ticks`) and turns keyframing on.
