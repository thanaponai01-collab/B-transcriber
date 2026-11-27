---
name: hks-build
description: "HKS build rules from the rule registry. Load when building an HKS (โหนกระแส) draft in Premiere from an approved paper edit, before the first cut, and until the cut checks pass."
---

GENERATED from projects/hks/registry by tools/hks_registry_build.py; do not edit.

# HKS build: rules and do-confirm

The 56 active `build` rules in [the registry](../../../projects/hks/registry/rules/). Gated rules are checked by `hks_gates`; the gate is the answer, so they ask nothing.

## Enforced by a gate

- **HKS-R5** No jump cuts (gate `same_frame_share`)
- **HKS-X8** Never a jump cut, not even one frame (gate `near_miss_covers`)
- **HKS-X33** Each piece starts and ends on a thought (gate `visible_cuts_in_speech`)
- **HKS-X35** Add a moment whole or not at all (gate `visible_cuts_in_speech`)
- **HKS-X36** Split the cut (J/L) (gate `same_frame_share`)
- **HKS-X37** The held picture must be safe (gate `unsafe_holds`)
- **HKS-X75** Every draft is labelled (gate `draft_labels`)
- **HKS-X100** Ripple fixes can overlap neighbours (gate `source_repeats`)

## Rules

- **HKS-7** **Cut hard under a proving picture; elsewhere keep pieces long.** Cut hard under a picture that proves the words; elsewhere keep pieces long. Frame-checked: of 345 uncovered joins, 311 land on a camera change, 9 on a layout or inset change, 5 under a still; only 2 are real same-shot jumps. (study/joins.md checks only joins with the studio picture on both sides.)
- **HKS-17** **Dress the cut from the template kit.** Every day uses the same nine pieces: the hook stack (dim 50, black tone + vignette, zoom, film damage, red-blue glitch, a 1-2 frame invert), the `SFX_โหนกระแส` sting, the BGM bed on its 56.48 s loop grid, the end stack and `CG_END LOGO`; headline cards are After Effects Linked Comps. Weakened: film damage is not a clean lifted-footage marker; the BGM bed is a daily-cut rule (EP.162/167 have none).
- **HKS-20** **The picture moves; the words stay in order.** A proof picture is taken from anywhere in the broadcast and laid under the claim it proves, even 100+ minutes away. This is why HKS-5's word moves are rare.
- **HKS-C2** **Cover only with the episode's own footage.** Cover only with footage from the episode itself (rule 6): it keeps the story honest (the picture is this case's real evidence) and avoids copyright claims.
- **HKS-C17** Tighten at speaker changes first (HKS-27 confirmed). Dropping another speaker's restatement lands on the broadcast's own camera switch, so no cover is needed; tighten inside one speaker's run only under split-screen cover (HKS-C9).
- **HKS-C25** Every shot is framed on its own (HKS-30 confirmed). One zoom for a whole set of shots is a preset (M-1), not framing; where the subject moves, cut the cover and re-position.
- **HKS-C26** A short ends on a held face (HKS-31 confirmed): the last speaker's face held under the sting, with glitch flashes and a whoosh, then the end card. The last thing the viewer sees is a reaction, not the logo.
- **HKS-R6** Cover = B-roll from the same story (ideally the same moment, this episode only), else a static listener shot (`Backup`). Film damage on B-roll zoomed to full screen (HKS-C10). No fixed minimum length: a cover lasts as long as the words that point at it, on the footage at the moment the speaker talks about it. The broadcast's split screens are where the evidence and B-roll are: use that footage to cover a cut when it is on the topic or the broadcast was showing it then (HKS-C9, 2026-11-24). The trick (user, 2026-11-23): where the guest talks about something that has B-roll, put the B-roll on top and cut aggressively underneath.
- **HKS-R7** **Swear words bleeped; same ending.** Swear words bleeped. Same ending every episode.
- **HKS-X3** B-roll is one continuous scene, as long as the talk is about it (20-46 s, reused when it fits), starting and ending on a sound cut so the change of picture hides that cut too.
- **HKS-X4** **A cutaway must be genuinely silent.** The user's studio cutaways are longer shots of the same scene from nearby (8-16 s, 15-26 s away), not 2-3 s pops. Listener shots picked by voice labels showed people talking out of sync. Check every cutaway frame by eye before using it; a masked speaker's own continuous picture can carry tightened sound.
- **HKS-X6** Play an insert with its own sound (a voice clip, a video the host plays): no studio talk over it, cut to its main point.
- **HKS-X9** Full-frame footage, not the soft box crop, wherever the show also aired that footage full screen (the user: "show the full one"), and B-roll that matches the words.
- **HKS-X10** **No sponsor strip, bug or clock on footage.** No sponsor strip, no 3HD bug, no clock on footage (on studio frames the bug and clock are fine, HKS-C3). Zoom a clip that carries the sponsor strip in, centred on the video.
- **HKS-X11** **No snappy scene changes.** A camera change within 1 s of a visible cut leaves a sliver shot. Don't trim speech to fix it; hold the picture on V2 instead (keep the outgoing shot to the change, or bring the incoming shot in at it). The hold must show a masked face or a wide shot, never a talking host.
- **HKS-X17** Route order (user, 2026-11-24: XML stays, as the last way): (1) copy the parent sequence in Premiere and pick from it (several pieces: `paste_pieces`, never `paste_from` in a loop; one insert: `paste_from`; `arrange`, `keep_words`, `cut_copy`, `duplicate_sequence`); (2) build from the footage only when no sequence holds the material yet; (3) an FCP7 XML only when Premiere can't be driven live, saying in the handover why 1 and 2 failed.
- **HKS-X23** Music bed under the whole piece, never a gap. `[BGM]Where Everything Began.wav` looped: -24 dB under the hook, -33 dB under talk, -12 dB under the end sting (levels 0.0112 / 0.00398 / 0.0447). Check: every second of a short sits under one BGM clip, at the level for what plays there.
- **HKS-X24** A flash at every section change, including the start of the body (hook -> sting -> body): glitch (`Glitch redblue.mov`) + an invert AL frame + a whoosh just before the cut.
- **HKS-X29** **Tighten under a cover; start early for set-up.** Tighten under a cover, and let a piece start early for its set-up (the user cut one 18 s piece into seven under a new B-roll cover, and moved piece starts 1.5-6.7 s to catch the line that sets them up).
- **HKS-X30** Clock blur in squares: the user's `Blur below logo` boxes, enabled, one per span. Disabled YT blur ALs are deleted, not kept switched off.
- **HKS-X31** **Reels built per workflow-log steps 7-8.** Reels: `4 REEL SIZE D1` and `5 REEL 1-3 SIZE D1` as workflow-log steps 7-8 say (nest the square, `1.png` frame on top; the 3-min nests a logo-less FB copy).
- **HKS-X34** Tighten inside a thought only under a cover, and then as hard as needed. In studio picture, keep the take whole.
- **HKS-X42** **J and L cuts are made on a copy.** Duplicate the clip, put the copy on the track above, and trim the copy. The raw clip stays untouched underneath as the backup; never trim the raw layer itself.
- **HKS-X43** **Blur: adjustment layer and mask.** New adjustment layer, Gaussian Blur, then the Ellipse or Rectangle mask tool in Effect Controls; feather the mask. Don't copy the user's layers or stack crops to fake a shape. Masks have no API, so the mask tools are a Premiere UI route still to be proven; explore Premiere's own tools before working around them.
- **HKS-X44** **Only moves that touch the named clips.** On HKS's layered timeline (body V1/V2, covers V3+, sound A1), only use moves that touch the clips I name; playhead keys reach every targeted track, covers included.
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
- **HKS-X68** **I read a stale parent sequence.** Read the parent sequence fresh (save + reader, or `read_timeline`) right before every derived build.
- **HKS-X106** ****A cover belongs to its cut, never one insert on every cut.**.** A cover belongs to its cut, never one insert repeated on every cut. Every cut is different: cover it only with the insert or B-roll the words at that cut point at, or what the broadcast showed at that moment; a cut on a camera change gets a J/L split instead, or stays straight. On 20261126 v1 I put a 4 s cover from the same few inserts on all 42 cuts, and the user said: "you spam a lot of like one insert ... every cut is not the same ... use the one that may be related to that cut ... not just spam it in every cut".
- **HKS-X108** ****Tighten word by word, then hide every cut.**.** Inside every kept passage cut out the pauses, restarts and doubled words, fillers and tag questions, the host's calls to the crew and his asides about the show; hide each cut with a J/L copy, a short cover from the same moment or the broadcast's own camera change. Pauses of about 0.15 s or more go; a swear word can go by sound instead of a bleep. A cover that hides a cut is short (the user's median 2.6 s), with film damage on a full-screen one (rules.md "Tighten word by word"). Seen in the user's D1 of 20261126: 176 such cuts took out 360 s (median sound clip 1.9 s, the agent's v1 21.9 s), and only 21 of 226 sound cuts were in-sync jumps. Confirmed by the user 2026-11-26 ("Yes, confirm both").
- **HKS-X113** **The first voice pre-laps under a full sting.** After a sting the body never starts flat: the sting plays its full length and the body's first voice starts under it (the user's fixes of 20261124: the host's question pre-lapped 2.16 s under a 4.04 s sting, in the YT and the 1-min).
- **M-3** **Never edit the user's working project in place.** Held candidate: never edit the user's working project in place. The HKS build plan says "nothing edits the user's day project" (agent-written).

## Do–confirm

Each question needs a written answer in the handover, keyed by its rule id.

1. **HKS-7** Where are the hard cuts, and does a proving picture sit over each?
2. **HKS-17** Which template-kit pieces are in the cut, and is any made by hand?
3. **HKS-20** For each proof picture, which claim does it sit under, and where is it from?
4. **HKS-C2** Is every cover from this episode's footage (sources listed)?
5. **HKS-C17** Which tightenings fall inside one speaker's run, and what covers each?
6. **HKS-C25** What scale and position does each shot have, and was each set from its own frame?
7. **HKS-C26** Which face is held under the sting before the end card?
8. **HKS-R6** For each cover, what footage is it (source timecode), and do the words under it point at it?
9. **HKS-R7** Are all swear words bleeped (timecodes), and is the standard ending in place?
10. **HKS-X3** How long is each B-roll scene, and does each start and end on a sound cut?
11. **HKS-X4** Which cutaways did you look at frame by frame (timecodes), and is nobody in any of them talking?
12. **HKS-X6** For each insert with its own sound, is there no studio talk over it, and what span of it plays?
13. **HKS-X9** For each boxed insert, did the show also air it full screen, and which version is in the cut?
14. **HKS-X10** In a rendered frame of each footage cover, does any show a sponsor strip, the 3HD bug or the clock?
15. **HKS-X11** Which slivers did sliver_check list, and how was each held (track, shot)?
16. **HKS-X17** Which route built the draft, and if not route 1, why did the earlier routes fail?
17. **HKS-X23** Does every second of the short sit under one BGM clip at the level for what plays there?
18. **HKS-X24** Is there a glitch, invert frame and whoosh at every section change, including sting to body (timecodes)?
19. **HKS-X29** Which pieces start earlier to catch their set-up line, and which tightening sits under a cover?
20. **HKS-X30** Is there one enabled Blur below logo box per span, and no disabled YT blur layer left?
21. **HKS-X31** Are both reels nested as steps 7-8 say (square nested, 1.png on top, 3-min from a logo-less FB copy)?
22. **HKS-X34** List every cut inside a thought and the cover over it.
23. **HKS-X42** For each J or L, is the raw clip untouched below the trimmed copy?
24. **HKS-X43** For each blur, is it your own adjustment layer with Gaussian Blur and a feathered mask?
25. **HKS-X44** Did every edit touch only the clips named, with covers on V3+ read back unchanged?
26. **HKS-X45** Where a 'J / L split' edit was made, which route was used and was the result read back?
27. **HKS-X46** Where a 'Still person for a J/L hold' edit was made, which route was used and was the result read back?
28. **HKS-X47** Where a 'Roll an edit by frames' edit was made, which route was used and was the result read back?
29. **HKS-X48** Where a 'Ripple trim by frames' edit was made, which route was used and was the result read back?
30. **HKS-X49** Where a 'Slip' edit was made, which route was used and was the result read back?
31. **HKS-X50** Where a 'Slide' edit was made, which route was used and was the result read back?
32. **HKS-X51** Where a 'Find the source of a shot' edit was made, which route was used and was the result read back?
33. **HKS-X52** Where a 'Cutaway from the source' edit was made, which route was used and was the result read back?
34. **HKS-X53** Where a 'Insert a copied moment' edit was made, which route was used and was the result read back?
35. **HKS-X54** Where a 'Cut only some tracks' edit was made, which route was used and was the result read back?
36. **HKS-X55** Where a 'Ripple extend' edit was made, which route was used and was the result read back?
37. **HKS-X56** Where a 'Audio fade at a cut' edit was made, which route was used and was the result read back?
38. **HKS-X57** Where a 'Remove a stretch' edit was made, which route was used and was the result read back?
39. **HKS-X58** Where a 'Cut on a repeated word' edit was made, which route was used and was the result read back?
40. **HKS-X59** Where a 'Fix an edge mid-word / mid-phrase' edit was made, which route was used and was the result read back?
41. **HKS-X60** Did the build use any move on the don't list (Q/W, E, Insert Frame Hold Segment, Close Gap)?
42. **HKS-X61** For each toolbar tool the edit needed, which route was used?
43. **HKS-X62** Was each Undo followed by a read-back of the timeline?
44. **HKS-X68** When was the parent sequence read, relative to the derived build?
45. **HKS-X106** For each cover, which words at that cut point at it (timecode), and is any insert used on more than one unrelated cut?
46. **HKS-X108** How many cuts inside kept passages, how many seconds they took out (pauses, restarts, fillers, crew talk), and how is each hidden (J/L copy, cover, camera change)?
47. **HKS-X113** Where does each sting end, and does the first voice of the body start under it?
48. **M-3** Was every edit made in a copy, with the user's day project untouched?
