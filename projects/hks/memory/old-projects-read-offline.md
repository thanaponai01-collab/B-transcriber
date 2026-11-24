---
name: old-projects-read-offline
description: Day projects saved by Premiere 26 get a _1 copy when opened in Premiere 27; read them offline
type: feedback
status: current
updated: 2026-11-24
---
Read Premiere 26 day projects offline with `cutdeck/prproj_reader.py`. Never open one in Premiere 27.
As of 2026-11-24 those are 20261001, 1002, 1003, 1012, 1020, 1109 and 1110 (`<Project Version="45">`;
Premiere 27 saves 46).

**Why:** opening a Premiere 26 project in Premiere 27 converts it and saves `<name>_1.prproj` next to
the original. A day folder with two `.prproj` breaks the one-project-per-day rule in
`tests/test_hks_reels.py` and `cutdeck/hks_gold.read_day`. On 2026-11-24 07:28 the overnight study
([overnight-study-2026-11-23.md](overnight-study-2026-11-23.md)) most likely did this to 20261012: two
reel tests failed until the user deleted the copy. The timelines in the copy were unchanged.

**How to apply:** if a day really must be opened live, tell the user afterwards about the new `_1` file
so they can delete it. Don't delete or save their `.prproj` yourself. Check a day's version with
`zcat <file> | head -c 3000 | grep -o 'Project ObjectID="1"[^>]*'`.
