# HKS rule registry

One JSON file per rule or principle in `rules/` (schema `rules.schema.json`, loader
`cutdeck/hks_registry.py`). It is the source of truth: `before-you-cut.md` and the stage skills
`.claude/skills/hks-*` are generated from it (`python tools/hks_registry_build.py`), and a test
fails on a hand edit of a generated file.

- **A new user correction** becomes a new rule file (next free `HKS-X<n>`, `kind_source: proposed`)
  or a status change on an old one (`superseded`, `superseded_by`). Run
  `python -m cutdeck.hks_rule_conflicts --correction "<the user's words>"` first: it names the active
  rules the correction overturns.
- **Commits:** `python tools/hks_registry_extract.py` fills `commit`/`added` from git; `--check` recomputes.
- **Evidence and decisions:** [../gates/redesign-20261126.md](../gates/redesign-20261126.md);
  extraction notes: [EXTRACTION.md](EXTRACTION.md).
