---
name: gold-reading-gotchas
description: Non-obvious facts about reading the user's HKS projects as gold (audio decides kept footage, show end, hook end, frame holds)
type: gotcha
status: current
updated: 2026-11-21
---
- Kept footage must be read from the **audio**: the main picture alternates V1/V2.
- Show end = the last non-footage clip; the unused pool sits after it.
- Hook end = the `Transition Complex 14` SFX.
- Only 20261120 has an `Edit` sequence.
- A clip with Premiere's Frame Hold (`frame_hold` from `prproj_reader`) shows one frozen frame and is
  a cover; 9 of 11 day projects use it.
- `prproj_reader` has crashed on some text layers (worked around by monkeypatching `parse_source_text`).
**How to apply:** check these before trusting a gold number from a new episode.
