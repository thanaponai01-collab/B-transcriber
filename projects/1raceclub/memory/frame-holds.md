---
name: frame-holds
description: How a CutDeck frame hold is made, where it lives, and how to crop one into a callout in a Short
type: fact
status: current
updated: 2026-11-22
---
The panel's **Add Frame Hold** writes a sequence-size (1080x1920) `CutDeck_Hold_<ms>.png`, transparent above the
seam, into `<project folder>\CutDeck\` beside the .prproj (LV GP: `4. PROJECTS\1. PREMIERE PRO\CutDeck\`), imports
it to the CutDeck > Frame Holds bin and places it on the track above the clip, leaving the clip whole.
It is a panel button, not a helper command. The agent makes the same thing:
1. Disable whatever sits above the feed at that frame, `export_frame` at the frame, then re-enable it.
2. Set alpha 0 above the seam (y < 742), then save as `CutDeck_Hold_<ms>.png` in that folder.
3. Place it on the track above the feed: `build_sequence` item, scale 100, centred. Stills under ~120 frames land
   one frame short, so ask n+1 and read back.
**Callout crop** on a hold (box l,t,r,b in hold pixels): anchor ((l+r)/2/1080, (t+b)/2/1920), position = where it
goes, Crop L l/10.8, T t/19.2, R (1080−r)/10.8, B (1920−b)/19.2, scale so the box stays inside the safe zone
(x 60–890, y 742–1440 under the seam; Russell radio: 190% / 150% at (475, 1091)).
**Gotcha:** `edit_clips trim_out` on a placed PNG still failed with "A nullptr was dereferenced."; remove and
re-place it at the right length instead.
**How to apply:** any freeze or callout in a Short ([shorts-rules.md](../shorts-rules.md) sections 4–5).
