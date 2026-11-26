### 2. Reach Premiere only by a proven route; never write an Adobe API from memory

Applies to anything that acts on Premiere: the UXP panel (`uxp/cutdeck/`), the helper, and
every `premiere_*` command. UXP is one route, not the limit of what an agent can do. An action
is in reach when a command in `cutdeck/driver_commands.py` does it through a route with a LIVE
row in `docs/PREMIERE_FACTS.md` "Route proof per command" (the task list is
`docs/PREMIERE_CONTROL_MAP.md`). When several routes reach it, take the first in this order,
ranked by measured success:

1. **UXP panel API** (99.6% of 10,532 logged calls).
2. **Menu** (`premiere_menu_command`; 919 of 919 posted, read the result back).
3. **Keys** (`premiere_key_command`; Undo and Ctrl+Alt bindings did nothing live).
4. **Premiere UI** (`set_speed`, `nest_clips`, `paste_attributes`, `edit_text`, `srt_subtitles`:
   dialogs, mouse and typing; 53 of 58).
5. **AI Assistant** (`premiere_assistant_ask`; spends the user's Adobe credits).

Read every edit back (`premiere_read_timeline`); a posted command is not proof. If no proven
route does it, say so and name the route that would need a live proof; don't approximate it.
**Off limits:** Premiere's built-in MCP server and `hSLScripting` are first-party only. Never
force their flags or pose as a first-party plugin (PREMIERE_FACTS rows on both).

Writing panel code: never write an Adobe API from memory. Check, in order:
`docs/PREMIERE_FACTS.md` (what each API did live), `reference/adobe/api/premierepro.txt` and
`api/uxp.txt` (one line per declared member; `NOT IN 26.2.1` marks members missing at
`minVersion` 26.2.0), `reference/adobe/docs/` and `reference/adobe/samples/`, then a live probe
for enum values and runtime semantics. Name the source in the change.

Enforcement: `node tools/adobe/check-api.mjs` (in `tests/cutdeck_adobe_api.test.cjs`) fails on
an undeclared member; `tests/cutdeck_route_proof.test.cjs` fails on a command with no LIVE
route row or an off-limits route. A new route or command gets its row after a live run
(verify-cutdeck). Test fakes build on `tests/fakes/premiere.cjs`.
