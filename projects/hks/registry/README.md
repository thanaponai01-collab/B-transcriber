# HKS rule registry

One JSON file per rule or principle in `rules/` (schema `rules.schema.json`, loader
`cutdeck/hks_registry.py`). It is the source of truth: `before-you-cut.md` and the stage skills
`.claude/skills/hks-*` are generated from it (`python tools/hks_registry_build.py`), and a test
fails on a hand edit of a generated file.

- **A new user correction** goes through `python tools/hks_correct.py "<the user's words>" ...` and
  nothing else. It runs the conflict check against the active rules, asks which rule wins and "gate
  or note?", then writes `corrections/K<n>.json` and the rule (a new `HKS-X<n>`, or the correction
  added to the rule it enforces again), and regenerates the pages and skills. `rules.md` and
  `principles.md` are frozen (`frozen.json`).
- **Corrections:** `corrections/K<n>.json`, the user's words, one file each. `tests/test_hks_corrections.py`
  fails on a correction no rule cites, on a correction quoted in `memory/` with no `(K<n>)` next to
  it, and on a rule pair the lexical check flags that `conflicts.json` doesn't list.
  `python tools/hks_corrections_report.py` counts corrections and repeats per episode.
- **Commits:** `python tools/hks_registry_extract.py` fills `commit`/`added` from git; `--check` recomputes.
- **Evidence and decisions:** [../gates/redesign-20261126.md](../gates/redesign-20261126.md);
  extraction notes: [EXTRACTION.md](EXTRACTION.md).
