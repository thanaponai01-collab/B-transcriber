---
name: shared-checkout
description: Another agent session can be working in the main checkout at the same time; never switch branches there
type: gotcha
status: current
updated: 2026-11-25
---
Seen 2026-11-21: another session committed this session's in-progress files.
Seen 2026-11-25: an agent ran `git checkout -b` and then `git checkout master` (with a stash and pull) in
the main checkout while another session was working there, first on `feat/clean-speech`, then on
`docs/system-map-reframe`. That session's uncommitted files moved branches twice under it. The agent put
the folder back on `docs/system-map-reframe`, and nothing was lost.
**Why it matters:** a branch switch in the shared folder changes the branch under another agent's
uncommitted work, and a stash or pull can mix the two sessions' changes.
**How to apply:** before any git command that moves HEAD, check `git status` and `git reflog -5` for work
that isn't yours. Commit your own files from a fresh worktree (`git worktree add`, copy only your files
in, commit, push, open the PR there). In the main folder, never check out, stash, pull or reset while
another session may be using it. Stage only your own files, and leave other sessions' changes as they are.
