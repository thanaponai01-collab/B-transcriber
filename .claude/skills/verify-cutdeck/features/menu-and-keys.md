# Menu and keyboard commands

An agent runs any Premiere menu item or keyboard shortcut, as a click or key press would, on the
timeline it names. This reaches what the panel API cannot: Undo/Redo, Add Edit (razor),
Link/Unlink, ripple delete of a selection, transport.

## Sub-features

- `list-menu` lists menu items with an enabled hint and whether CutDeck will run them.
- `menu-command` posts one menu item; with focus `timeline` it first focuses the named timeline.
- `list-keys` lists commands bound in the user's shortcut file.
- `key-command` presses one command's shortcut after focusing a panel.
- `refusal` blocks quit, close, open, import, export, save-as and dialog items.

## How to get to it (user POV)

- MCP tools `premiere_list_menu`, `premiere_menu_command`, `premiere_list_key_commands`, `premiere_key_command`.
- `python -m cutdeck.premiere_cli menu_command "Edit > Undo"`.

## Driving it with cdv.py

Preconditions:

- Baseline from the index. Premiere is not minimised (it is brought to the front).

- **List.** Run `C call list_menu '{"query": "Add Edit"}'`. Items `Sequence > Add Edit` and `Sequence > Add Edit to All Tracks`, `runnable: true`.
- **Razor.** Run `C call set_playhead '{"sequence": "CutDeck verify (scratch)", "ticks": "762048000000"}'`, then `C call menu_command '{"path": "Sequence > Add Edit to All Tracks", "sequence": "CutDeck verify (scratch)"}' --label razor`. The reply's `sequence` is the scratch and `focus.via` is `Window > Timelines > CutDeck verify (scratch)`. Then `C call read_timeline '{"sequence": "CutDeck verify (scratch)"}'` shows `V1@0` and `V1@762048000000` (and the same on A1).
- **Undo.** Run `C call menu_command '{"path": "Edit > Undo", "focus": null}'`. A read shows one clip per track again.
- **Key.** Run `C call set_playhead '{"sequence": "CutDeck verify (scratch)", "ticks": "0"}'`, then `C call key_command '{"command": "cmd.transport.sequence.end", "focus": "program"}'`. A `read_timeline` shows `playhead_ticks` equal to `end_ticks`.
- **Refusal.** Run `C call menu_command '{"path": "File > Exit"}'`. It fails with "is never run for an agent" and Premiere stays open.

Proven 2026-11-21 through the helper (focus check, Undo, End key); razor proven through the MCP
server before the routes moved into the helper. Not yet run with cdv.py.

## Gotchas

- A posted menu item or pressed key is not proof: always read the result back.
- Never use the Timelines shortcut (Shift+3) to focus: pressed again it cycles to the next sequence.
- Ctrl+Z and Ctrl+Alt bindings did nothing as keys; use the menu for Undo.
- The menu's enabled flag can be stale (Redo read disabled, then ran).
- Key presses take the keyboard for about a second; the user typing at that moment interferes.
