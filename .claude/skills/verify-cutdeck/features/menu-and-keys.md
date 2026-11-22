# Menu and keyboard commands

An agent runs any Premiere menu item or keyboard shortcut, as a click or key press would, on the
timeline it names. This reaches what the panel API cannot: Undo/Redo, Add Edit (razor),
Link/Unlink, ripple delete of a selection, transport.

## Sub-features

- `list-menu` lists menu items with an enabled hint and whether CutDeck will run them.
- `menu-command` posts one menu item; with focus `timeline` it first focuses the named timeline.
- `list-keys` lists commands bound in the user's shortcut file.
- `key-command` presses one command's shortcut after focusing a panel.
- `refusal` blocks File > exit, close, open, new, import, export, save-as, save-a-copy and
  revert, all of Help, and every dialog item (`...`). The two dialogs CutDeck fills itself,
  Speed/Duration and Nest, have their own tools: see [dialogs](./dialogs.md).

## How to get to it (user POV)

- MCP tools `premiere_list_menu`, `premiere_menu_command`, `premiere_list_key_commands`, `premiere_key_command`.
- `python -m cutdeck.premiere_cli menu_command "Edit > Undo"`.

## Driving it with cdv.py

Preconditions:

- Baseline from the index. Premiere is not minimised (it is brought to the front).

- **List.** Run `C call list_menu '{"query": "Add Edit"}'`. Items `Sequence > Add Edit` and `Sequence > Add Edit to All Tracks`, `runnable: true`.
- **Razor.** Run `C call set_playhead '{"sequence": "CutDeck verify (scratch)", "ticks": "762048000000"}'`, then `C call menu_command '{"path": "Sequence > Add Edit to All Tracks", "sequence": "CutDeck verify (scratch)"}' --label razor`. The reply's `sequence` is the scratch and `focus.via` is `Window > Timelines > CutDeck verify (scratch)`. Then `C call read_timeline '{"sequence": "CutDeck verify (scratch)"}'` shows `V1@0` and `V1@762048000000` (and the same on A1).
- **Undo.** Run `C call menu_command '{"path": "Edit > Undo", "focus": null}'`. A read shows one clip per track again.
- **Key.** Run `C call set_playhead '{"sequence": "CutDeck verify (scratch)", "ticks": "0"}'`, then `C call key_command '{"command": "cmd.transport.sequence.end", "focus": "program"}'`. A `read_timeline` shows `playhead_ticks` equal to `end_ticks`. With focus `program` the key goes to the open sequence and the reply's `sequence` is null, so the scratch must be the open one.
- **Refusal.** Run `C call menu_command '{"path": "File > Exit"}'`. It fails with "is never run for an agent" and Premiere stays open. `C call menu_command '{"path": "Clip > Nest..."}'` fails with "opens a dialog".

Proven 2026-11-22 with this skill, every step above (run `20261122-000256-maintain-timeline`):
list, razor (`V1@762048000000` and `A1@762048000000` added), undo, End key, both refusals.

## Gotchas

- A posted menu item or pressed key is not proof: always read the result back.
- Never use the Timelines shortcut (Shift+3) to focus: pressed again it cycles to the next sequence.
- Ctrl+Z and Ctrl+Alt bindings did nothing as keys; use the menu for Undo.
- The menu's enabled flag can be stale (Redo read disabled, then ran).
- Key presses take the keyboard for about a second; the user typing at that moment interferes.
