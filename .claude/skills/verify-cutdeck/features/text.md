# Text Graphics

An agent places a text Graphic with its own text (any language, Thai included) from a Motion
Graphics Template, and replaces the text of a Premiere-made text Graphic already on the
timeline. Premiere 27.0's API cannot write text in place, so placing bakes the text into a copy
of the template, and editing types into the Program Monitor as a person does.

## Sub-features

- `place` inserts a template with chosen texts on an empty track; After Effects templates read their texts back.
- `edit` finds a Graphic's text in the Program Monitor, double-clicks it and types the new text.
- `style` place with `styles` (Premiere-made templates): size, colours, stroke, caps, faux styles, alignment, leading, shadow, background; the bake re-encodes the layer's Source Text.
- `restyle` `restyle_text` changes one layer of a Graphic already placed, as Premiere does: a style written and imported, set on the layer by Properties > Linked style, set back to None (the look stays), its bin removed; read back from the saved project.
- `layers` `set_param` moves, scales, rotates and fades each text layer (one `AE.ADBE Text` component each), and Vector Motion and Wiggle; read the chain with `read_timeline` `effects: "params"` (on the CFD template: 4-7 Text, 2 Vector Motion, 3 Wiggle).
- `refuse` place refuses a track with a clip at or after the point and an unknown text name; edit refuses Graphics with several text layers and After Effects templates.

## How to get to it (user POV)

- MCP tools `premiere_place_text`, `premiere_edit_text` and `premiere_restyle_text` (with `premiere_remove_style_bin` for a bin a failed restyle left).
- `premiere_read_timeline` `effects: "params"` shows After Effects template texts as `{text, font, size}`.

## Driving it with cdv.py

Preconditions:

- Baseline from the index. The Program Monitor and the Tools panel are visible (for edit).
- `T` below is `"template": "C:/Program Files/Adobe/Adobe Premiere Pro 2027/Essential Graphics/Basic Title.mogrt"`, shipped with Premiere.

- **Refusals.** `C call place_text '{"sequence": "CutDeck verify (scratch)", T, "texts": {"0": "x"}, "at_ticks": "0", "v": 0}'` fails "V1 has a clip at or after 0". With `"v": 1` and `"texts": {"Nope": "x"}` it fails listing `0 "TextLayer"`.
- **Place.** `C call place_text '{"sequence": "CutDeck verify (scratch)", T, "texts": {"0": "OLD TEXT"}, "at_ticks": "0", "v": 1}'`. Reply clip `V2@0`, `end_ticks` 1244678400000, `texts` empty (Premiere-made text cannot be read). Set the playhead to 508032000000 and `C shot placed --frame`: "OLD TEXT" mid-frame.
- **Edit.** `C call edit_text '{"sequence": "CutDeck verify (scratch)", "clip": "V2@0", "text": "ข้อความใหม่"}'`. Reply `changed_px_elsewhere` 0, `left_editing` true; `C shot edited --frame` shows the Thai text in the same style.
- **Undo.** One Undo restores "OLD TEXT" (`C shot edit-undone --frame`). Three more Undos (Enable, Disable, place) remove `V2@0`; read back V1 and A1 only.

Proven 2026-11-22 with this skill, every step above (run `20261122-000256-maintain-timeline`); edit and undo again 2026-11-23 after its fixed pauses became waits on the window (run `20261123-001015-edit-text-sleeps`, median 7.66 s to 4.27 s over the bars, 7.73 s to 4.34 s over real footage with Thai text); place from an After Effects template with read-back proven 2026-11-21 (run `20261121-230511-mogrttext`).

- **Style.** With a Premiere-made multi-layer template `U` (e.g. the user's CFD `20261111 - template.mogrt`): `C call place_text '{"sequence": "CutDeck verify (scratch)", U, "texts": {"0": "STYLE ล่าง"}, "styles": {"0": {"fill": "#FFD400", "size": 180, "underline": true, "shadow_on": false}}, "at_ticks": "<free>", "v": <free track>}'`, then `export_frame` at a tick inside it: yellow, larger, underlined, no glow. `save_project` (only with the user's OK) and decode the layer with `cutdeck.text_document.decode`: the values read back. Proven 2026-11-27 (run `20261127-110807-text-full-control`, steps 27-35). `{"0": {"font": "x"}}` fails "unknown style" listing the styles; Basic Title / AE templates fail "no text layer".

- **Restyle.** On a placed CFD Graphic `V2@0` (4 text layers), with Effect Controls (every Text row folded and in view) and Properties visible: `C call restyle_text '{"sequence": "CutDeck verify (scratch)", "clip": "V2@0", "layer": 0, "styles": {"fill": "#FFCC00", "size": 110, "alignment": "left", "background_on": true, "background": "#000000", "background_opacity": 80}}'` replies `style_removed` true; `C shot restyled --frame` shows layer 0 yellow on a black box, the others unchanged. Four Edit > Undo steps revert it. Proven 2026-11-27 (run `20261127-121925-text-restyle-probe`, steps 39-45, about 17 s). `{"font": "x"}` fails "unknown style" before anything moves.

## Gotchas

- `place_text` inserts: on a busy track it would push later clips (and leave audio out of sync), hence the refusal.
- `edit_text` takes the mouse and keyboard for a few seconds, picks the Selection tool, and moves the playhead and selection.
- Never press tool shortcuts around it: V switched on Object Selection (then double-click selects the clip, not its text). Escape does not leave text editing; clicking the Selection tool does.
- Each After Effects template placement adds a folder to `Motion Graphics Template Media` beside the project.
- `restyle_text` saves the project (before and after), takes the mouse for about 15 s and needs the Effect Controls and Properties panels showing; it refuses while a `CutDeck restyle *.prtextstyle` bin is left in the project (unlink any layer showing it, then `remove_style_bin`).
- A failed restyle names the style it left; a layer still linked to it shows the style in Properties > Linked style.
