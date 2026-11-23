---
name: marker-draft
description: What the user wants in the day's marker draft on the timeline: questions by story phase, plus breaks and sponsors
type: feedback
status: current
updated: 2026-11-23
---
The user's slowest manual step is listing the host's questions on the timeline and grouping them.
On 20261123 the draft went onto the `Editing` sequence (the user chose to keep it there), as
ranged markers:
- each question `S<phase>.<n> <Thai title>`, with the opening question in the comment, grouped
  into **story phases** (S1–S5) when the episode is one incident: one "story" alone did not help;
- `[OPENING]`, `[BREAK]`, `[CREDITS]` cut blocks from `hks_breaks`, `[BREAK 3] social part
  starts` where the TV clock goes, and `[SPONSOR?]` for sponsor reads outside a break.

**Why:** the user said "what you didn't do is flag the break, sponsor" after the first draft held
questions only.
**How to apply:** `python -m cutdeck.hks_day "<day folder>"` does all of it (transcript,
breaks, judges via headless `claude -p`, files, markers). Every marker draft carries all three: questions by phase, breaks, sponsors.
The list goes next to the Premiere project, not in the repo:
`<day folder>\4. PROJECTS\1. PREMIERE PRO\CutDeck\Questions\<day> questions.md` (the same
`CutDeck\<kind>` layout as `srt_subtitles.py`'s `CutDeck\Subtitles`). Ask whether the user moved or deleted
markers after the cut: that is the feedback for the next day's draft.
