---
name: watch-method
description: How the agent watches the user edit 1RaceClub (save diffs + screenshots) and logs it
type: decision
status: current
updated: 2026-11-21
---
Since 2026-11-21 the agent watches the user's 1RaceClub edits: a watcher diffs each Ctrl+S / Auto-Save
of the open `.prproj` with `cutdeck/prproj_reader.py` (scratchpad `watch_prproj.py`; rewrite it if
gone), logs each step in [workflow-log.md](../workflow-log.md) and asks the reason behind each judgment call.
**Why it matters:** the user wants to teach the edit, then automate it (same as HKS).
**How to apply:** re-arm the watcher when a session resumes. The save is the source of truth for what
changed; the user gives the why. Record whys in [principles.md](../principles.md), not the log.
