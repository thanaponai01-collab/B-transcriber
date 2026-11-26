---
name: hks-build
description: "HKS build rules from the rule registry. Load when building an HKS (โหนกระแส) draft in Premiere from an approved paper edit, before the first cut, and until the cut checks pass."
---

GENERATED from projects/hks/registry by tools/hks_registry_build.py; do not edit.

# HKS build: rules and do-confirm

The 80 active `build` rules in [the registry](../../../projects/hks/registry/rules/). A gate id names the `hks_gates` check that measures the rule.

- **HKS-7** **Cut hard under a proving picture; elsewhere keep pieces long.** Cut hard under a picture that proves the words; elsewhere keep pieces long. Frame-checked: of 345 uncovered joins, 311 land on a camera change, 9 on a layout or inset change, 5 under a still; only 2 are real same-shot jumps. (study/joins.md checks only joins with the studio picture on both sides.)
- **HKS-17** **Dress the cut from the template kit.** Every day uses the same nine pieces: the hook stack (dim 50, black tone + vignette, zoom, film damage, red-blue glitch, a 1-2 frame invert), the `SFX_โหนกระแส` sting, the BGM bed on its 56.48 s loop grid, the end stack and `CG_END LOGO`; headline cards are After Effects Linked Comps. Weakened: film damage is not a clean lifted-footage marker; the BGM bed is a daily-cut rule (EP.162/167 have none).
- **HKS-20** **The picture moves; the words stay in order.** A proof picture is taken from anywhere in the broadcast and laid under the claim it proves, even 100+ minutes away. This is why HKS-5's word moves are rare.
- **HKS-32** A piece is a whole thought (confirmed 2026-11-25: "Sounds right"). 28 of v4's edges sat in running speech with no pause; some split a Thai word the engine had split ("กลัวน้ำตา | ไหล"), and v4 opened on "เพราะ | อยู่ในเรื่องนี้". Fun moments added as 1-3 s bits had the same problem; the user kept them whole or not at all. (gate `visible_cuts_in_speech`)
- **HKS-33** Sound and picture cut at different times (confirmed 2026-11-25: "feel way better", with the safe-hold condition). A cut where sound and picture jump on the same frame is the one the eye notices; offset, each hides the other. The held picture must be safe. (gate `same_frame_share`)
- **HKS-C1** No jump cuts in the studio picture (rule 5): viewers notice them and the show should look like the broadcast. Both reasons. (gate `same_frame_share`)
- **HKS-C2** **Cover only with the episode's own footage.** Cover only with footage from the episode itself (rule 6): it keeps the story honest (the picture is this case's real evidence) and avoids copyright claims.
- **HKS-C3** **The TV clock is blurred to hide the re-cut.** The TV clock is blurred to hide that it is a re-cut: a clock that jumps between pieces shows the edit. The clock and the 3HD bug are fine on studio frames; cover them where they would show the cut.
- **HKS-C9** A cover has no fixed minimum length (replaces "covers >= 4 s"; HKS-21 confirmed): it lasts as long as the words that point at it, and sits on the footage at the moment the speaker talks about it. Look for the broadcast's split screens first; that footage may cover a cut when it is on the topic, or when the broadcast was showing it at that moment.
- **HKS-C10** **Film damage on B-roll zoomed to full screen.** Film damage goes on B-roll that is zoomed to full screen (rule 6 narrowed). The study's exceptions (HKS-17 note) are not yet re-checked against "zoomed full screen".
- **HKS-C17** Tighten at speaker changes first (HKS-27 confirmed). Dropping another speaker's restatement lands on the broadcast's own camera switch, so no cover is needed; tighten inside one speaker's run only under split-screen cover (HKS-C9).
- **HKS-C20** **A flicker is a jump; a short shot is not.** The "no snappy scene changes" rule is about a shot too short to read (v4: 0.16 s), not any shot under 1 s (1123's 0.7-0.9 s shots are fine).
- **HKS-C25** Every shot is framed on its own (HKS-30 confirmed). One zoom for a whole set of shots is a preset (M-1), not framing; where the subject moves, cut the cover and re-position.
- **HKS-C26** A short ends on a held face (HKS-31 confirmed): the last speaker's face held under the sting, with glitch flashes and a whoosh, then the end card. The last thing the viewer sees is a reaction, not the logo.
- **HKS-C28** **Nothing unfinished.** Don't ever cut the things that are not finished (HKS-32 again): no piece ending mid-thought ("...ก็", "...คือ"), no neighbouring pieces overlapping so words play twice. (gate `visible_cuts_in_speech`)
- **HKS-C29** **A same-scene speech jump is covered.** A jump to another speech in the same scene is covered with an insert, B-roll or a static person (HKS-R5 again). (gate `same_frame_share`)
- **HKS-C30** **Every edit keeps the raw underneath.** For J and L cuts, always duplicate the layer on top and edit the copy; the raw layer stays below as backup (same idea as 1RaceClub RC-15).
- **HKS-R5** No jump cuts: in studio picture cut only at a thought end or a camera change. Cut hard (stumbles, pauses, repeats) only under a cover. (Status note, user 2026-11-23: rule 5 now allows inset camera changes and cuts under a still, and a punch-in needs a cover.) (gate `same_frame_share`)
- **HKS-R6** Cover = B-roll from the same story (ideally the same moment, this episode only), else a static listener shot (`Backup`). Film damage on B-roll zoomed to full screen (HKS-C10). No fixed minimum length: a cover lasts as long as the words that point at it, on the footage at the moment the speaker talks about it. The broadcast's split screens are where the evidence and B-roll are: use that footage to cover a cut when it is on the topic or the broadcast was showing it then (HKS-C9, 2026-11-24). The trick (user, 2026-11-23): where the guest talks about something that has B-roll, put the B-roll on top and cut aggressively underneath.
- **HKS-R7** **Swear words bleeped; same ending.** Swear words bleeped. Same ending every episode.
- **HKS-X2** **Cut hard only where nobody can see the cut.** Under B-roll the sound is cut tight (18 cuts under one 46 s CCTV piece). Where the live studio picture already changes camera, long stretches stay whole (10-76 s, no cut): the broadcast director's cuts already give the picture pace. Pace is uneven on purpose.
- **HKS-X3** B-roll is one continuous scene, as long as the talk is about it (20-46 s, reused when it fits), starting and ending on a sound cut so the change of picture hides that cut too.
- **HKS-X4** **A cutaway must be genuinely silent.** The user's studio cutaways are longer shots of the same scene from nearby (8-16 s, 15-26 s away), not 2-3 s pops. Listener shots picked by voice labels showed people talking out of sync. Check every cutaway frame by eye before using it; a masked speaker's own continuous picture can carry tightened sound.
- **HKS-X6** Play an insert with its own sound (a voice clip, a video the host plays): no studio talk over it, cut to its main point.
- **HKS-X8** Never a jump cut, not even one frame. A cover must start on exactly the body's cut tick (v4's covers drifted 1-4 frames and flashed the jump). It must also open on a frame where the footage is fully on. Render each cover's first and last frame before building. (gate `near_miss_covers`)
- **HKS-X9** Full-frame footage, not the soft box crop, wherever the show also aired that footage full screen (the user: "show the full one"), and B-roll that matches the words.
- **HKS-X10** **No sponsor strip, bug or clock on footage.** No sponsor strip, no 3HD bug, no clock on footage (on studio frames the bug and clock are fine, HKS-C3). Zoom a clip that carries the sponsor strip in, centred on the video.
- **HKS-X11** **No snappy scene changes.** A camera change within 1 s of a visible cut leaves a sliver shot. Don't trim speech to fix it; hold the picture on V2 instead (keep the outgoing shot to the change, or bring the incoming shot in at it). The hold must show a masked face or a wide shot, never a talking host.
- **HKS-X16** **Cut: tighten at speaker changes first.** Tighten at speaker changes first; inside one speaker's run only under cover (HKS-C17).
- **HKS-X17** Route order (user, 2026-11-24: XML stays, as the last way): (1) copy the parent sequence in Premiere and pick from it (several pieces: `paste_pieces`, never `paste_from` in a loop; one insert: `paste_from`; `arrange`, `keep_words`, `cut_copy`, `duplicate_sequence`); (2) build from the footage only when no sequence holds the material yet; (3) an FCP7 XML only when Premiere can't be driven live, saying in the handover why 1 and 2 failed.
- **HKS-X23** Music bed under the whole piece, never a gap. `[BGM]Where Everything Began.wav` looped: -24 dB under the hook, -33 dB under talk, -12 dB under the end sting (levels 0.0112 / 0.00398 / 0.0447). Check: every second of a short sits under one BGM clip, at the level for what plays there.
- **HKS-X24** A flash at every section change, including the start of the body (hook -> sting -> body): glitch (`Glitch redblue.mov`) + an invert AL frame + a whoosh just before the cut.
- **HKS-X27** Square reframe per shot (HKS-C25). A cover zoomed for 16:9 needs a bigger zoom in the 1080 square frame. Where the subject moves, razor the cover and re-position each part. Render a frame of each cover in the square before handover.
- **HKS-X28** The 1-min ends on a held face under the sting (HKS-C26), then the end card; target just under 60 s.
- **HKS-X29** **Tighten under a cover; start early for set-up.** Tighten under a cover, and let a piece start early for its set-up (the user cut one 18 s piece into seven under a new B-roll cover, and moved piece starts 1.5-6.7 s to catch the line that sets them up).
- **HKS-X30** Clock blur in squares: the user's `Blur below logo` boxes, enabled, one per span. Disabled YT blur ALs are deleted, not kept switched off.
- **HKS-X31** **Reels built per workflow-log steps 7-8.** Reels: `4 REEL SIZE D1` and `5 REEL 1-3 SIZE D1` as workflow-log steps 7-8 say (nest the square, `1.png` frame on top; the 3-min nests a logo-less FB copy).
- **HKS-X33** **Each piece starts and ends on a thought.** Each piece starts where a thought starts and ends where it ends. Read every edge with 2 s of source on each side. An end must finish the sentence, including its closing particle (ครับ / นะ / เลย). A piece that opens on a joining word (เพราะ / แล้วก็ / คือ / แต่) brings the line before it, or moves. The edge must be in a real pause, not just between two engine words. (gate `visible_cuts_in_speech`)
- **HKS-X34** Tighten inside a thought only under a cover, and then as hard as needed. In studio picture, keep the take whole.
- **HKS-X35** **Add a moment whole or not at all.** Add a moment as its whole passage or not at all. No 1-3 s bits joined mid-sentence to an approved cut.
- **HKS-X36** **Split the cut (J/L).** Split the cut. Put the picture change 0.5-2 s off the sound cut. J: the next voice starts under the last picture or cover, then the picture cuts to the speaker. L: the picture changes first and the voice ends under it. Build it on the upper tracks (`premiere_edit_clips` trims one clip without its partner). (gate `same_frame_share`)
- **HKS-X37** **The held picture must be safe.** In the extra 0.5-2 s of a J or L, nobody in the held picture may be talking, by sight (lips, gestures) or in the source sound behind it. Otherwise hold B-roll or a still person shot (from `Backup`, a listening face, or Add Frame Hold), or leave that cut straight. Check the source words in the held span (none) and its frames. Sound and picture cutting on the same frame is the exception, kept for a real camera change or a section flash. (gate `unsafe_holds`)
- **HKS-X40** **Never cut a thing that isn't finished.** A thought, a sentence or an answer is in whole or out. Run the cut check and fix every edge it lists before handover. (gate `visible_cuts_in_speech`)
- **HKS-X41** **Same-scene speech jump needs a cover.** A jump to another speech inside the same scene needs a cover: insert, B-roll or a still person (`Backup`) over the join; never two takes of the same shot butted together in plain view (rule 5). (gate `same_frame_share`)
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
- **HKS-X63** I cut in the middle of a thought, sometimes in the middle of a word (the engine splits Thai words). Gate: `python -m cutdeck.hks_cut_check --prproj <day> --sequence <draft> --from <body start>` reads the audio and lists every cut in speech the viewer can see; fix each one or say why it stays. (gate `visible_cuts_in_speech`)
- **HKS-X64** I added moments as 1-3 s bits joined mid-sentence to an approved cut. Gate: the same list, plus "a moment goes in whole or not at all". (gate `visible_cuts_in_speech`)
- **HKS-X65** I cut sound and picture on the same frame, so the cut shows. Gate: the check's same-frame count. Most cuts should be hidden under a cover or split as J/L; the user's 20261124 YT body has 12 of 173 on the same frame. (gate `same_frame_share`)
- **HKS-X66** **A split edit can hold a talking picture.** A split edit can hold a picture of someone talking without their sound. Gate: the check's "unsafe holds"; look at the frames of each; where someone talks, hold B-roll or a still person, or leave the cut straight. (gate `unsafe_holds`)
- **HKS-X68** **I read a stale parent sequence.** Read the parent sequence fresh (save + reader, or `read_timeline`) right before every derived build.
- **HKS-X72** **I worked around Premiere.** When a picture fix needs a Premiere tool (mask, effect), find and try that tool first; a workaround is the last way and gets named in the handover.
- **HKS-X75** **Every draft is labelled.** Every draft the agent builds is labelled too: each body piece takes the colour of the question piece its source comes from, and every cover on the upper tracks (B-roll, cutaway, zoomed insert) is light green. (gate `draft_labels`)
- **HKS-X81** **Build the effect the shot needs.** Finishing, not editing: build the effect the shot needs. Blur = own adjustment layer + mask (ELLIPSE mask tool); explore the tools Premiere has. The agent copied the user's look layer, then faked a circle with crop effects.
- **HKS-X95** J/L on a copy: duplicate the clip onto the track above and trim the copy. The raw clip stays below, untouched, as the backup.
- **HKS-X96** Use Premiere's own tool first: blur = my own adjustment layer + Gaussian Blur + an Ellipse or Rectangle mask, feathered. "No API" means: try the UI route. It doesn't mean impossible. A workaround is the last way, and the handover names it.
- **HKS-X100** **Ripple fixes can overlap neighbours.** My ripple fixes made neighbouring pieces overlap in source, and I didn't check for it. (gate `source_repeats`)
- **HKS-X101** **No API does not mean impossible.** For the blur I read "masks have no API" as "masks can't be done", and copied your layer instead of building one.
- **HKS-X106** ****A cover belongs to its cut, never one insert on every cut.**.** A cover belongs to its cut, never one insert repeated on every cut. Every cut is different: cover it only with the insert or B-roll the words at that cut point at, or what the broadcast showed at that moment; a cut on a camera change gets a J/L split instead, or stays straight. On 20261126 v1 I put a 4 s cover from the same few inserts on all 42 cuts, and the user said: "you spam a lot of like one insert ... every cut is not the same ... use the one that may be related to that cut ... not just spam it in every cut".
- **HKS-X108** ****Tighten word by word, then hide every cut.**.** Inside every kept passage cut out the pauses, restarts and doubled words, fillers and tag questions, the host's calls to the crew and his asides about the show; hide each cut with a J/L copy, a short cover from the same moment or the broadcast's own camera change. Seen in the user's D1 of 20261126: 176 such cuts took out 360 s (median sound clip 1.9 s, the agent's v1 21.9 s), and only 21 of 226 sound cuts were in-sync jumps.
- **M-3** **Never edit the user's working project in place.** Held candidate: never edit the user's working project in place. The HKS build plan says "nothing edits the user's day project" (agent-written).

## Do–confirm

Each question needs a written answer in the handover, keyed by its rule id.

1. **HKS-7** Where are the hard cuts, and does a proving picture sit over each?
2. **HKS-17** Which template-kit pieces are in the cut, and is any made by hand?
3. **HKS-20** For each proof picture, which claim does it sit under, and where is it from?
4. **HKS-32** Does every piece start and end on a whole thought, read with its sound?
5. **HKS-C1** Is there any same-shot jump in plain studio view (timecodes)?
6. **HKS-C2** Is every cover from this episode's footage (sources listed)?
7. **HKS-C3** Where would a jumping clock show a cut, and is it covered there?
8. **HKS-C9** For each cover, which words point at it, and is it on the topic or what the broadcast showed then?
9. **HKS-C10** Does every B-roll zoomed to full screen carry film damage, and nothing else?
10. **HKS-C17** Which tightenings fall inside one speaker's run, and what covers each?
11. **HKS-C20** Which shots under 0.4 s sit at an edit point, and how was each fixed?
12. **HKS-C25** What scale and position does each shot have, and was each set from its own frame?
13. **HKS-C26** Which face is held under the sting before the end card?
14. **HKS-C28** Which piece ends were read as unfinished, and how was each fixed?
15. **HKS-C29** List each same-scene speech jump and its cover.
16. **HKS-C30** Is the raw layer untouched under every trimmed copy?
17. **HKS-R5** List every visible studio cut that is not at a camera change or a thought end; what covers each?
18. **HKS-R6** For each cover, what footage is it (source timecode), and do the words under it point at it?
19. **HKS-R7** Are all swear words bleeped (timecodes), and is the standard ending in place?
20. **HKS-X2** Where are the tight cuts (timecodes), and is each under B-roll or at a broadcast camera change?
21. **HKS-X3** How long is each B-roll scene, and does each start and end on a sound cut?
22. **HKS-X4** Which cutaways did you look at frame by frame (timecodes), and is nobody in any of them talking?
23. **HKS-X6** For each insert with its own sound, is there no studio talk over it, and what span of it plays?
24. **HKS-X9** For each boxed insert, did the show also air it full screen, and which version is in the cut?
25. **HKS-X10** In a rendered frame of each footage cover, does any show a sponsor strip, the 3HD bug or the clock?
26. **HKS-X11** Which slivers did sliver_check list, and how was each held (track, shot)?
27. **HKS-X16** Where was a speaker's run tightened inside, and what covers each such cut?
28. **HKS-X17** Which route built the draft, and if not route 1, why did the earlier routes fail?
29. **HKS-X23** Does every second of the short sit under one BGM clip at the level for what plays there?
30. **HKS-X24** Is there a glitch, invert frame and whoosh at every section change, including sting to body (timecodes)?
31. **HKS-X27** In a rendered square frame of each cover, is each framed on its own subject (scale, position)?
32. **HKS-X28** Which face is held under the sting, and how long is the 1-min?
33. **HKS-X29** Which pieces start earlier to catch their set-up line, and which tightening sits under a cover?
34. **HKS-X30** Is there one enabled Blur below logo box per span, and no disabled YT blur layer left?
35. **HKS-X31** Are both reels nested as steps 7-8 say (square nested, 1.png on top, 3-min from a logo-less FB copy)?
36. **HKS-X33** With 2 s of source each side, does every end finish its sentence and no piece open on a joining word?
37. **HKS-X34** List every cut inside a thought and the cover over it.
38. **HKS-X35** Which moments were added to the approved cut, and is each a whole passage (source range)?
39. **HKS-X36** How many sound cuts are split as J or L, and are they built on V2+ with A1 untouched?
40. **HKS-X40** Reading every piece end, which end unfinished, and how was each fixed?
41. **HKS-X41** List each jump to another speech in the same scene and the cover over it.
42. **HKS-X42** For each J or L, is the raw clip untouched below the trimmed copy?
43. **HKS-X43** For each blur, is it your own adjustment layer with Gaussian Blur and a feathered mask?
44. **HKS-X44** Did every edit touch only the clips named, with covers on V3+ read back unchanged?
45. **HKS-X45** Where a 'J / L split' edit was made, which route was used and was the result read back?
46. **HKS-X46** Where a 'Still person for a J/L hold' edit was made, which route was used and was the result read back?
47. **HKS-X47** Where a 'Roll an edit by frames' edit was made, which route was used and was the result read back?
48. **HKS-X48** Where a 'Ripple trim by frames' edit was made, which route was used and was the result read back?
49. **HKS-X49** Where a 'Slip' edit was made, which route was used and was the result read back?
50. **HKS-X50** Where a 'Slide' edit was made, which route was used and was the result read back?
51. **HKS-X51** Where a 'Find the source of a shot' edit was made, which route was used and was the result read back?
52. **HKS-X52** Where a 'Cutaway from the source' edit was made, which route was used and was the result read back?
53. **HKS-X53** Where a 'Insert a copied moment' edit was made, which route was used and was the result read back?
54. **HKS-X54** Where a 'Cut only some tracks' edit was made, which route was used and was the result read back?
55. **HKS-X55** Where a 'Ripple extend' edit was made, which route was used and was the result read back?
56. **HKS-X56** Where a 'Audio fade at a cut' edit was made, which route was used and was the result read back?
57. **HKS-X57** Where a 'Remove a stretch' edit was made, which route was used and was the result read back?
58. **HKS-X58** Where a 'Cut on a repeated word' edit was made, which route was used and was the result read back?
59. **HKS-X59** Where a 'Fix an edge mid-word / mid-phrase' edit was made, which route was used and was the result read back?
60. **HKS-X60** Did the build use any move on the don't list (Q/W, E, Insert Frame Hold Segment, Close Gap)?
61. **HKS-X61** For each toolbar tool the edit needed, which route was used?
62. **HKS-X62** Was each Undo followed by a read-back of the timeline?
63. **HKS-X64** Which moments were added, and is each a whole passage with no mid-sentence join?
64. **HKS-X68** When was the parent sequence read, relative to the derived build?
65. **HKS-X72** For each picture fix, which Premiere tool was tried first, and is any workaround named?
66. **HKS-X81** Which effects did the shots need, and was each built with Premiere's own tool?
67. **HKS-X95** Is every J/L made on a copy with the raw clip untouched below?
68. **HKS-X96** Which Premiere tool did each picture fix use, and is any workaround named?
69. **HKS-X101** Where an API was missing, which UI route was tried?
70. **HKS-X106** For each cover, which words at that cut point at it (timecode), and is any insert used on more than one unrelated cut?
71. **HKS-X108** How many cuts inside kept passages, how many seconds they took out (pauses, restarts, fillers, crew talk), and how is each hidden (J/L copy, cover, camera change)?
72. **M-3** Was every edit made in a copy, with the user's day project untouched?
