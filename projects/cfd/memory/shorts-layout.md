---
name: shorts-layout
description: Track layout of a finished CFD Short on the `Shorts` sequence (CFD 99), body plus the ~8.8 s ending sting and end card
type: reference
status: current
updated: 2026-11-27
---
Read live from CFD 99 `Shorts` (1080x1920, 50 fps; three Shorts back to back with gaps between) at export time,
2026-11-27. The user built and rebuilt this; *(seen, not explained by the user)* unless marked.

**Body** (from the first clip to the end of the dialogue, e.g. 0–59.16, 119.16–170.52, 230.02–285.0):

| Track | What |
|---|---|
| V1 + A1 | source clip pieces at 100%, untouched (linked dialogue) |
| V2 | **video-only copy** of each V1 piece, reframed (see [[shorts-reframe]]); cut wherever the framing changes |
| two tracks above | `GRADIENT BAR.png` and `GRADIENT BAR2.png` over the whole body and sting (darken the bottom for subtitles) |
| one track | `guideline.png` from `F:\Me\1.All Pr&Ae\3-AnyMind\Project Atime\CFD SUBTITLE\`, **disabled**: a check overlay only. At export time only Short 3 still had it |
| caption tracks | subtitles as captions in style CFD SUBTITLE (see [[shorts-captions]]) |
| A6 | music `Dimension No.5.wav` under the whole Short, end card included |

**Ending** (same on all three; times relative to the end of the dialogue D):
- D → D+3.84: **sting**. V2 (or V3) holds a last 3.84 s of picture, with an Adjustment Layer (Transform),
  `FILM_DAMAGE2.mov` (scale 180.6) over it, and `Medium Cinematic Boom 14.wav` from D−0.04 to D+3.48.
- D+3.12 → D+4.60: `CG_Transition_ClubFriday.mov` (three pieces, scale 345), with `SFX_โหนกระแส 2.wav` from D+2.96 to D+5.0.
- D+3.84 → D+8.84: **end card**, the `20261111 - template Linked Comp` After Effects comp
  ("ฟังต่อเต็มๆ ได้ที่ FULL EP", 5 s).
- A Short ends at D+8.84 (68.00, 179.36, 293.84). That is the export Out point ([[shorts-export]]).

Track numbers differ between Shorts (V3–V11 moved as the user rebuilt), so find items by name, not by track.
**Why it matters:** an agent building a Short must reproduce this, and must not mistake the sting for dialogue.
**How to apply:** read `read_timeline` on `Shorts` first; copy the ending from an existing Short rather than rebuilding it.
Related: [[episode-folders]], CFD-R6–R9
