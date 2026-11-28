### 2. Prove the route; never write an Adobe API from memory

UXP is not the limit of what agents can do in Premiere. Before saying an action can't be done,
or building a workaround, look it up in `docs/PREMIERE_CONTROL_MAP.md`: every route (UXP, menu,
keys, Premiere UI, AI Assistant) and the `premiere_*` command for each task. Use a command only
through routes with a LIVE row in `docs/PREMIERE_FACTS.md` "Route proof per command"
(`tests/cutdeck_route_proof.test.cjs` enforces it), follow the control map's "One route per
action", and read the result back. Premiere's built-in MCP server and `hSLScripting` are off
limits: first-party only, never force them.

For panel code (`uxp/cutdeck/`), never write an Adobe API from memory: check
`docs/PREMIERE_FACTS.md`, then `reference/adobe/api/premierepro.txt` / `api/uxp.txt`, then
`reference/adobe/docs/` and `samples/`, then a live probe; name the source in the change.
`node tools/adobe/check-api.mjs` enforces it. Test fakes build on `tests/fakes/premiere.cjs`.
