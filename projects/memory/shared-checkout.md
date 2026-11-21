---
name: shared-checkout
description: Another agent session can be working in the main checkout at the same time
type: gotcha
status: current
updated: 2026-11-21
---
Seen 2026-11-21: another session committed this session's in-progress files.
**How to apply:** check `git status` and `git log` before assuming the tree is as you left it.
