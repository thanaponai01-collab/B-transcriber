# HKS build playbook (READ-DO)

GENERATED from projects/hks/registry by tools/hks_registry_build.py; do not edit.

- **HKS-X45** **Playbook: J / L split.** Most speaker changes in studio: `edit_clips`, shrink one picture, then extend the other; sound untouched.
- **HKS-X46** **Playbook: Still person for a J/L hold.** The held source shows someone talking: Add Frame Hold on a listening frame (menu, clip selected, playhead set); freezes from the playhead, no ripple.
- **HKS-X47** **Playbook: Roll an edit by frames.** Move a cut a few frames to a better word or face: Trim Edit + Ctrl+Right/Left (rolls only tracks with an edit there), or `edit_clips` trim pair.
- **HKS-X48** **Playbook: Ripple trim by frames.** An end or start a few frames off: Trim Edit + Ctrl+Shift+T (ripple) + Ctrl+Right/Left.
- **HKS-X49** **Playbook: Slip.** Same length and place, different moment: select V+A, Ctrl+Alt+Left/Right per frame (right = earlier source), or `edit_clips` trim_in +d, move -d, trim_out +d.
- **HKS-X50** **Playbook: Slide.** Move a short insert a few frames, neighbours absorb it: select V+A, Alt+, / Alt+. per frame.
- **HKS-X51** **Playbook: Find the source of a shot.** Sequence > Match Frame (Source monitor at the exact frame).
- **HKS-X52** **Playbook: Cutaway from the source.** A listening face or B-roll over the talk: Match Frame or open the source, then `.` (overwrite) with the timeline playhead set; target only the V track you want.
- **HKS-X53** **Playbook: Insert a copied moment.** Put a set-up line in front of a punchline: Edit > Copy, playhead, Edit > Paste Insert (ripples every track).
- **HKS-X54** **Playbook: Cut only some tracks.** Razor sound but not picture (or the reverse): untarget tracks (Ctrl+0 video / Ctrl+9 audio), Add Edit, retarget.
- **HKS-X55** **Playbook: Ripple extend.** An end that stops before the sentence ends: `edit_clips` move later clips +d, then trim_out +d; also extend or split any cover spanning the edit.
- **HKS-X56** **Playbook: Audio fade at a cut.** A click or a breath at a sound cut: `set_param` Volume keyframes, 2-3 frames.
- **HKS-X57** **Playbook: Remove a stretch.** Tightening: `edit_clips` remove with ripple, V and A in one call.
- **HKS-X58** **Playbook: Cut on a repeated word.** A stutter ("เหรอ เหรอ", "อยู่แล้ว อยู่แล้ว"): end on the first copy, start on the second; the user's way to tighten in plain view (seen in D1, 2026-11-25).
- **HKS-X59** **Playbook: Fix an edge mid-word / mid-phrase.** The check lists it: ripple-extend to the next gap of >= 0.2 s between words; pull back instead when the added words would be a dangling opener (แล้ว, ก็, คือ); skip when the added source already plays elsewhere.
- **HKS-X60** **Timeline moves not to use.** Don't: Shift+Q/W or Q/W on a layered timeline (they trimmed the cover), E (disabled the clip instead of extending), Insert Frame Hold Segment (ripples every track), Close Gap from the menu (did nothing). Mark Clip takes the topmost clip (the cover), not the body. Track locks don't stop API edits. Linked Selection on: a video-only selection + Clear does nothing.
- **HKS-X61** **Toolbar tools and their routes.** Razor (C) = Add Edit; Ripple (B) / Roll (N) = Trim Edit + nudges; Rate Stretch (R) = `premiere_set_speed`; Slip (Y) / Slide (U) = their frame keys; Pen (P) = `set_param` keyframes; Track Select (A) = `select_clips` of every clip after a time; Type (T) = `place_text`. Hand / Zoom only move the view.
- **HKS-X62** Undo one step at a time with a read-back: a command that does nothing leaves no undo step, and a counted run of Undos goes too far.
