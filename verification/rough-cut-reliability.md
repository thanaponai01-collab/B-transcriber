# Rough Cut reliability evidence - 2026-10-11

Fixed and proven offline: a stale first handle now triggers a fresh read in both
split and move batches. Live-host confirmation remains pending.

## Reproduction and proof
- Before implementation: new tests ran the actual applyNativeCut entry point;
  14 passed / 4 failed with action 1, "The script object is no longer valid."
  Full output: output/rough-cut-reliability/before.txt.
- Fake handles stay invalid once stale; only rereading returns fresh handles.
- Restoring the original first-action exclusion in a scratch copy caused 4 of 37
  cases to fail; the unchanged implementation passed all 37. The mutation is
  verification/rough-cut-first-handle.json; verify.py challenge reported caught.
- verify.py baseline, run --strict, status on
  .verify-evidence/rough-cut-reliability returned VERIFY-STATE: green.
- Scoped copy contains the same uxp source, three selected test files, golden
  fixture, docs/rough-cut.md and verification/rough-cut.md as the working tree.
- Full panel suite: 635 passed / 0 failed, including the Adobe API source check.
  Output: output/rough-cut-reliability/panel-suite.txt.
- Related helper restart, native-plan golden and sequence JSON tests: 36 passed.
- verify.py tests --strict passed, but its scanner does not itemize JavaScript
  tests; test execution and the mutation rejection provide the behavioral proof.

## Conditions and limits
Commands use Node v22.16.0 and the installed verify-loop/scripts/verify.py under
C:/Users/thana/.agents/skills. The scoped recipe has no live-server dependency.
The checker records rejection and green receipts in its .verify-state.json.
Its green status applies only to the mapped recovery claim, not the whole repo.
Read-only `python -m cutdeck.live_check` failed at "Premiere Pro is running";
no real timeline was edited. Original preservation and exact output were checked
against the fake host and existing XML-recut golden result, not live Premiere.
No GPU ASR, Premiere runtime semantics, or source-edit-during-analysis guarantee
is established here. No new Adobe API was introduced; existing clone/move APIs
are documented in docs/PREMIERE_FACTS.md and pinned Adobe declarations.

Committed with the Rough Cut recovery fix. Reload the CutDeck panel before testing it live.
