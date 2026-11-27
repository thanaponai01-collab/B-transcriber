---
name: shorts-export
description: Export CFD Shorts with the user's BAS7 preset, one In/Out per Short (end card included), named Short<k>_ClubFriday EP.<ep> D<n>.mp4
type: preference
status: current
updated: 2026-11-27
---
- **Preset: BAS7** (user's own; `C:\Users\thana\OneDrive\Documents\Adobe\Adobe Media Encoder\27.0\Presets\BAS7.epr`):
  H.264, 15 Mbps, Match Source, so a 1080x1920 50 fps sequence exports 1080x1920 50 fps. *(confirmed 2026-11-27: "use my BAS7 preset export")*
- **One export per Short:** set In/Out from its first clip to the end of its end card, then render.
  *(confirmed: "mark in and out each short")*
- **Name:** `5. EXPORTS\Short<k>_ClubFriday EP.<ep> D<n>.mp4` (D = draft). *(confirmed: "Short1_ClubFriday EP.99 D1")*
- CFD 99 D1, 2026-11-27: Short1 0–68.00 (68.00 s), Short2 119.16–179.36 (60.20 s), Short3 230.02–293.84 (63.82 s),
  rendered in Premiere in 49–79 s each. Afterwards In/Out was set back to the user's own (0–68).
- Gotcha: pass **backslash** Windows paths to `export_sequence`. With forward slashes it exported nothing yet reported ok
  (`extension ""`, `resolved false`). Check the file with ffprobe after every export.

**Why it matters:** agents never export unasked. When asked, this is the user's exact way.
**How to apply:** export only on the user's request; don't overwrite an existing file (bump D<n> or ask).
Related: [[shorts-layout]], [[episode-folders]]
