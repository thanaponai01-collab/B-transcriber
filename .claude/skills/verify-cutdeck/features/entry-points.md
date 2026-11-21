# Ways in for agents and scripts

Every Premiere command has one way in, the helper, reached three ways: the MCP tools
`premiere_<command>`, the terminal `python -m cutdeck.premiere_cli`, and Python
`Backend().premiere(command, args)`. All three must reach panel and helper-run commands alike.

## Sub-features

- `cli` runs a tabled command from a terminal and prints JSON. It passes arguments only for
  commands with a CLI target form; others (e.g. `set_speed`, `place_text`) get none and fail
  their argument check, so drive those with `C call` or `Backend().premiere`.
- `mcp` builds one MCP tool per tabled command with typed parameters.
- `backend` is the Python call scripts use; `cdv.py call` is built on it.
- `helper-run` commands run in the helper, not the panel. screenshot, list_menu and
  list_key_commands work without the panel; menu_command/key_command with focus timeline,
  set_speed, nest_clips and edit_text also call panel commands, so they need it.

## How to get to it (user POV)

- An MCP client connected to `python -m cutdeck.mcp_server`.
- `python -m cutdeck.premiere_cli <command> [target]`.

## Driving it with cdv.py

Preconditions:

- `C doctor` exits 0.

- **CLI, panel command.** Run `python -m cutdeck.premiere_cli read_sequence`. Exit 0 and JSON with the active sequence's `name`.
- **CLI, helper command.** Run `python -m cutdeck.premiere_cli list_menu "Edit > Undo"`. Exit 0, `count` 1, keys `Ctrl+Z`.
- **MCP tools in process.** Run `python -c "import asyncio;from cutdeck.mcp_server import create_server;from cutdeck.ai_backend import Backend;print(len(asyncio.run(create_server(Backend()).list_tools())))"`. Prints 48.
- **MCP call.** Run `python -c "import asyncio;from cutdeck.mcp_server import create_server;from cutdeck.ai_backend import Backend;print(asyncio.run(create_server(Backend()).call_tool('premiere_list_key_commands', {'query': 'undo'})))"`. The text names the user's `.kys` file.
- **Recorded.** Run `C call screenshot --label helper-only`. The recorded file holds a PNG path; open it to see Premiere.

Proven 2026-11-22 with this skill (run `20261122-000256-maintain-timeline`): CLI both kinds, MCP
list (48) and call through the real helper, recorded screenshot; `premiere_cli set_speed` fails
its argument check as described.

## Gotchas

- A running MCP client keeps the tool list it loaded at start: after a table change, reconnect
  the client before testing through it.
- `premiere_status` lists only panel commands; helper-run ones are not in it.
- The AI Assistant command spends the user's Adobe credits: do not run it to verify routing.
