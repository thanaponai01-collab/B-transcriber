### 2. Prove an Adobe API or route exists before using it

Applies to anything in the UXP panel (`uxp/cutdeck/`) or any Premiere / UXP call. Never
write an Adobe API from memory. All sources are pinned in the repo
(`reference/adobe/README.md`); nothing needs downloading. Check them in this order:

1. **`docs/PREMIERE_FACTS.md`**: what each API actually did when run live (catches,
   BROKEN, ABSENT, proven enum values). Add a row after every live run.
2. **`reference/adobe/api/premierepro.txt`** and **`reference/adobe/api/uxp.txt`**: one
   line per declared member (`grep "^SequenceEditor\." …`), generated from
   `@adobe/premierepro@27.0.0` (the installed Premiere) and `@adobe/cc-ext-uxp-types`.
   `NOT IN 26.2.1` marks members missing at the manifest's `minVersion` 26.2.0.
3. **`reference/adobe/docs/`** (Adobe's `uxp-premiere-pro` docs) and
   **`reference/adobe/samples/`** (Adobe's sample panels).
4. **Live probe** for what typings can't tell you: numeric enum values and runtime
   semantics (e.g. keyframe time units; `InterpolationMode` is LINEAR 0 / HOLD 4 /
   BEZIER 5).

Enforcement: `node tools/adobe/check-api.mjs` (also run by
`tests/cutdeck_adobe_api.test.cjs`) fails on any member name no Adobe source explains.
Its TypeScript tooling installs on the first test run, or by hand with
`npm ci --prefix tools/adobe`. Test fakes build on `tests/fakes/premiere.cjs`, which
enforces the proven rules and is itself checked against the typings.

In the change, name the source that confirmed the API. **UXP is one route, not the limit.**
If UXP doesn't have the feature, don't fake it in the panel: use a command in
`cutdeck/driver_commands.py` whose routes (menu, keys, Premiere UI, AI Assistant) have a LIVE
row in `docs/PREMIERE_FACTS.md` "Route proof per command" (`tests/cutdeck_route_proof.test.cjs`;
tasks in `docs/PREMIERE_CONTROL_MAP.md`), or prove a new route live first. Premiere's built-in
MCP server and `hSLScripting` stay off limits.
