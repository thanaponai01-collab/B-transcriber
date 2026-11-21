# Ways in for agents and scripts

Every Premiere command has one way in, the helper, reached three ways: the MCP tools
`premiere_<command>`, the terminal `python -m cutdeck.premiere_cli`, and Python
`Backend().premiere(command, args)`. All three must reach panel and helper-run commands alike.

## Sub-features

- `cli` runs any tabled command from a terminal and prints JSON.
- `mcp` builds one MCP tool per tabled command with typed parameters.
- `backend` is the Python call scripts use; `cdv.py call` is built on it.
- `helper-only` commands (screenshot, menu, keys, assistant) work without the panel.

## How to get to it (user POV)

- An MCP client connected to `python -m cutdeck.mcp_server`.
- `python -m cutdeck.premiere_cli <command> [target]`.

## Driving it with cdv.py

Preconditions:

- `C doctor` exits 0.

- **CLI, panel command.** Run `python -m cutdeck.premiere_cli read_sequence`. Exit 0 and JSON with the active sequence's `name`.
- **CLI, helper command.** Run `python -m cutdeck.premiere_cli list_menu "Edit > Undo"`. Exit 0, `count` 1, keys `Ctrl+Z`.
- **MCP tools in process.** Run `python -c "import asyncio;from cutdeck.mcp_server import create_server;from cutdeck.ai_backend import Backend;print(len(asyncio.run(create_server(Backend()).list_tools())))"`. Prints 44.
- **MCP call.** Run `python -c "import asyncio;from cutdeck.mcp_server import create_server;from cutdeck.ai_backend import Backend;print(asyncio.run(create_server(Backend()).call_tool('premiere_list_key_commands', {'query': 'undo'})))"`. The text names the user's `.kys` file.
- **Recorded.** Run `C call screenshot --label helper-only`. The recorded file holds a PNG path; open it to see Premiere.

Proven 2026-11-21 (CLI both kinds, MCP list and call through the real helper).

## Gotchas

- A running MCP client keeps the tool list it loaded at start: after a table change, reconnect
  the client before testing through it.
- `premiere_status` lists only panel commands; helper-run ones are not in it.
- The AI Assistant command spends the user's Adobe credits: do not run it to verify routing.
