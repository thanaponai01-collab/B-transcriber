---
name: shorts-captions
description: CFD Short subtitles: captions (never Graphics) in CFD SUBTITLE, one line inside the guide window, user recolours and retimes; never touch their tracks
type: preference
status: current
updated: 2026-11-27
---
- **Captions, not Graphics.** The user recolours them per speaker: caller purple, host cyan.
  `srt_subtitles` with `upgrade: false`, style CFD SUBTITLE, one new caption track per batch. *(confirmed 2026-11-27)*
- **All text inside the guide window** (`guideline.png`: clear window x 196–875, y 191–1347 of 1080x1920).
  **One line by default; two lines only when a cue is too long, and both must stay inside.** *(confirmed,
  2026-11-27: "if too long it could be two lines but one line in the main, but both need to be inside guide line")*
  In CFD SUBTITLE the first line sits at y ≈ 1230 and a second line drops to y ≈ 1320–1350, onto the bottom
  edge. So a two-line cue only fits if its captions are raised, and no agent route moves a caption track yet.
  Prefer one line: **19 characters or fewer** (Thai combining marks don't count), splitting a long cue in time
  at a phrase break.
- **The user edits captions after placement** (re-times, merges, recolours): C4 went 49 → 46 → 52 captions by
  hand. *(seen)* **Never clear, replace or upgrade a caption track without reading it first and asking.**
  Edit > Select All + Upgrade Caption to Graphic upgrades every caption on the sequence, including the user's.
- SRT times: keep them on the 0.1 s grid (Premiere imports SRT at 30 fps and floors).

**Why it matters:** one agent clear wiped the user's speaker colours (recovered only through their History panel).
**How to apply:** read the tracks with the `captiontiming` probe before and after any caption work, and leave
existing caption tracks alone. Related: [[shorts-layout]], CFD-R8
