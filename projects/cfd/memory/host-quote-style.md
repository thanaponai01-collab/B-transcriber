---
name: host-quote-style
description: How the user's host advice quotes look and sit on the CFD 98 long form (style, place, timing)
type: reference
status: current
updated: 2026-11-26
---
Two text styles: **host advice = blue-green**; caller/guest = pink, which only appears on the highlight
(skip it for now). *(confirmed, user 2026-11-26)*

Seen on CFD 98, sequence `Editing`, quote at 6:05 (365.4–370.2 s) ([frame](host-quote-style.png)):
- A **Graphic on V3**: three Thai text lines in a blue-green handwritten-style font, staggered, inside
  big “ ” quote marks (5 text layers: 3 lines + 2 marks).
- Placed in the empty wall at upper left, clear of the host's face and of the bottom title banner.
  Vector Motion position ≈ (0.16, 0.20) of the frame, scale ≈ 58 %.
- Each graphic is on screen **about 3–5 s**; a longer quote is split into 2–4 graphics back to back
  (e.g. 2211.0 → 2214.6 → 2218.3 → 2220.9 s).
- Quotes mostly sit **near the end of each clip**, where the advice comes. 26 graphics across 8 clips.
- Font name: not read yet (`cutdeck/prproj_reader.py` on the saved project, or Essential Graphics).

**How to apply:** reuse the user's own graphic (copy it and change the text), don't rebuild the style.
How to place it by command is still to prove: `premiere_place_text` needs a .mogrt; `edit_text`
changes text of a graphic already on the timeline.
