# Text Graphics

An agent places a text Graphic with its own text (any language, Thai included) from a Motion
Graphics Template, and replaces the text of a Premiere-made text Graphic already on the
timeline. Premiere 27.0's API cannot write text in place, so placing bakes the text into a copy
of the template, and editing types into the Program Monitor as a person does.

## Sub-features

- `place` inserts a template with chosen texts on an empty track; After Effects templates read their texts back.
- `edit` finds a Graphic's text in the Program Monitor, double-clicks it and types the new text.
- `refuse` place refuses a track with a clip at or after the point and an unknown text name; edit refuses Graphics with several text layers and After Effects templates.

## How to get to it (user POV)

- MCP tools `premiere_place_text` and `premiere_edit_text`.
- `premiere_read_timeline` `effects: "params"` shows After Effects template texts as `{text, font, size}`.

## Driving it with cdv.py

Preconditions:

- Baseline from the index. The Program Monitor and the Tools panel are visible (for edit).
- `T` below is `"template": "C:/Program Files/Adobe/Adobe Premiere Pro 2027/Essential Graphics/Basic Title.mogrt"`, shipped with Premiere.

- **Refusals.** `C call place_text '{"sequence": "CutDeck verify (scratch)", T, "texts": {"0": "x"}, "at_ticks": "0", "v": 0}'` fails "V1 has a clip at or after 0". With `"v": 1` and `"texts": {"Nope": "x"}` it fails listing `0 "TextLayer"`.
- **Place.** `C call place_text '{"sequence": "CutDeck verify (scratch)", T, "texts": {"0": "OLD TEXT"}, "at_ticks": "0", "v": 1}'`. Reply clip `V2@0`, `end_ticks` 1244678400000, `texts` empty (Premiere-made text cannot be read). Set the playhead to 508032000000 and `C shot placed --frame`: "OLD TEXT" mid-frame.
- **Edit.** `C call edit_text '{"sequence": "CutDeck verify (scratch)", "clip": "V2@0", "text": "ข้อความใหม่"}'`. Reply `changed_px_elsewhere` 0, `left_editing` true; `C shot edited --frame` shows the Thai text in the same style.
- **Undo.** One Undo restores "OLD TEXT" (`C shot edit-undone --frame`). Three more Undos (Enable, Disable, place) remove `V2@0`; read back V1 and A1 only.

Proven 2026-11-22 with this skill, every step above (run `20261122-000256-maintain-timeline`); edit and undo again 2026-11-23 after its fixed pauses became waits on the window (run `20261123-001015-edit-text-sleeps`, median 7.65 s to 4.21 s); place from an After Effects template with read-back proven 2026-11-21 (run `20261121-230511-mogrttext`).

## Gotchas

- `place_text` inserts: on a busy track it would push later clips (and leave audio out of sync), hence the refusal.
- `edit_text` takes the mouse and keyboard for a few seconds, picks the Selection tool, and moves the playhead and selection.
- Never press tool shortcuts around it: V switched on Object Selection (then double-click selects the clip, not its text). Escape does not leave text editing; clicking the Selection tool does.
- Each After Effects template placement adds a folder to `Motion Graphics Template Media` beside the project.
