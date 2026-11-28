### 2. Prove an Adobe API exists before using it

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

In the change, name the source that confirmed the API. **If UXP doesn't have the
feature, don't fake or approximate it in the panel.** Build it in the CutDeck helper
(`python -m cutdeck.helper`, `ws://127.0.0.1:7891`, exposed to agents by the MCP
server `cutdeck/mcp_server.py`) and have the panel call it through `core/rpc.js`.

