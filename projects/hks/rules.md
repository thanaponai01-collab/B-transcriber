# HKS (โหนกระแส) rules (how, today)

How the show is cut and finished today. Rules can change; the why behind them belongs in
[principles.md](principles.md). Values are this episode's examples, not presets.

**Before any draft, read [before-you-cut.md](before-you-cut.md)**: the gates I broke on 20261125, and why.

**Status: under audit.** Every rule came from one episode (20261120). [rule-audit.md](rule-audit.md)
checks them on all 11 day folders. The user answered its seven questions on 2026-11-23 (end of
that file): rule 5 now allows inset camera changes and cuts under a still, and a punch-in needs
a cover.

**IDs:** `HKS-R<n>` = cut rule *n* below. Code cites the rule doc (`cutdeck/hks_*.py` →
[build-plan.md](build-plan.md) / [rule-audit.md](rule-audit.md)).

## Cut rules for the long form (step 3)

Moved word for word on 2026-11-22 from [workflow-log.md](workflow-log.md) (Automation candidates).

1. Get into each story fast: the guest's first story sentence, or the host's summary if the
   guest is slow, or the host question that sets it up (ask, then tell; HKS-C6, 2026-11-24).
2. (M-4) Each point told once. Drop retellings, off-topic asides, backstory and feelings that
   don't move events (shorten as much as possible). Law stays only as the answer to the guest's own
   case: right after the fact it explains, or as the verdict, often near the end once the story is
   told; never a lecture (HKS-C8, 2026-11-24).
3. Keep the host when he carries the story: the chapter question, the challenge the viewer wants
   asked, the clearest summary, the verdict, legal cover. Cut his warm-up, clarifying questions,
   name checks, filler, most jokes and his on-air intro and recap (HKS-C4, C7, 2026-11-24). Keep a
   host connector to bridge pieces that don't join. Host reactions may be added for drama.
4. Viewer comments read on air: cut, unless one is the objection a guest or the host then answers
   (HKS-C5, 2026-11-24). Sponsors: always cut.
5. No jump cuts: in studio picture cut only at a thought end or a camera change. Cut hard
   (stumbles, pauses, repeats) only under a cover.
6. Cover = B-roll from the same story (ideally the same moment, this episode only), else a
   static listener shot (`Backup`). Film damage on B-roll zoomed to full screen (HKS-C10).
   No fixed minimum length: a cover lasts as long as the words that point at it, on the footage
   at the moment the speaker talks about it. The broadcast's split screens are where the evidence
   and B-roll are: use that footage to cover a cut when it is on the topic or the broadcast was
   showing it then (HKS-C9, 2026-11-24).
   The trick (user, 2026-11-23): where the guest talks about something that has B-roll, put the
   B-roll on top and cut aggressively underneath.

   **Lessons from the user's finished 20261123 YT cut** (19:52; numbers in
   [memory/yt-20261123-lessons.md](memory/yt-20261123-lessons.md)). The user's words: learn why, don't
   copy; their cut is not the best possible one. Each lesson is the why, then the how:
   - *The story is the order, not the broadcast.* Material moves to where the viewer needs it: the
     "why 500k" answer right where the number comes up, the voice recording right after "it was
     still 500,000" as proof, the host's recap of what was paid at the end of a story part, the
     lawyer's legal framing after the events it explains (events first, law second).
   - *Cut hard only where nobody can see the cut.* Under B-roll the sound is cut tight (18 cuts under
     one 46 s CCTV piece). Where the live studio picture already changes camera, long stretches
     stay whole (10–76 s, no cut): the broadcast director's cuts already give the picture pace.
     Pace is uneven on purpose (S3.1: 27 pieces in 51 s; S2.3: 8 pieces in 251 s).
   - *B-roll is one continuous scene, as long as the talk is about it* (20–46 s, reused when it
     fits), starting and ending on a sound cut so the change of picture hides that cut too.
   - *A cutaway must be genuinely silent.* The user's studio cutaways are longer shots of the same
     scene from nearby (8–16 s, 15–26 s away), not 2–3 s pops. The agent's listener shots of
     2026-11-23 showed people talking out of sync: they were picked by voice labels (wrong for a
     stand-in host and two hooded guests), never by looking. Check every cutaway frame by eye
     before using it; a masked speaker's own continuous picture can carry tightened sound.
   - *Ask, then tell* (user, 2026-11-23): keep the host question that sets up the next beat ("and
     when you got home, what happened?"); it keeps the viewer tracking what happens next.
   - *Play an insert with its own sound* (a voice clip, a video the host plays): no studio talk
     over it, cut to its main point (here the recording's first 30 s, 30:17–30:47).
   - *Keep the law short and late:* the lawyer stays (148 s of 1171 s) where it explains what
     happened, not as a separate lecture. *End fast:* the last three topics take 31 s.

   **From the user's red markers on YT draft v4** (2026-11-23):
   - *Never a jump cut, not even one frame.* A cover must start on exactly the body's cut tick
     (v4's covers drifted 1–4 frames and flashed the jump). It must also open on a frame where the
     footage is fully on: v4's marker-1 cover started at a box insert's first second, which was still
     the studio. Render each cover's first and last frame before building.
   - *Full-frame footage, not the soft box crop,* wherever the show also aired that footage full
     screen (the user: "show the full one"), and B-roll that matches the words: the 16th's house
     CCTV and the phone video for "what happened on the 16th".
   - *No sponsor strip, no 3HD bug, no clock* on footage (on studio frames the bug and clock are
     fine, HKS-C3). The phone clip before the second break (src
     2536.5–2584.6) carries the sponsor and credits strip (from y 521). Zoom it in, centred on the
     video: Scale 240, Position (0.475, 0.667), which keeps the source window x 260–1060, y 60–510.
   - *No snappy scene changes.* A camera change within 1 s of a visible cut leaves a sliver shot
     (marker 3: 0.16 s). Don't trim speech to fix it; hold the picture on V2 instead (keep the
     outgoing shot to the change, or bring the incoming shot in at it). The hold must show a
     masked face or a wide shot, never a talking host. ~~Covers last at least 4 s.~~ Replaced by
   rule 6's "no fixed minimum" (user, 2026-11-24).
7. Swear words bleeped. Same ending every episode.

## Draft workflow and checks before handover (user agreed, 2026-11-24)

How the agent builds an HKS draft (why: [principles.md](principles.md) HKS-C13 to C19):

1. **Topic and colour pass first** (HKS-16; once saved, `python -m cutdeck.split_pieces --prproj <day>.prproj --sequence Editing` lists each question piece with its colour and words, ready for `premiere_paste_from` / `premiere_arrange`): razor the broadcast at every topic change and label each
   topic by colour. The user approves what goes in before the agent cuts how.
2. **Split-screen index:** list every stretch where the broadcast shows a split screen (evidence, B-roll).
   That is the cover pool (HKS-C9).
3. **2–3 hook options**, each built a different way (the clash, the shocking fact, the question). The
   user picks; record the pick and the user's reason in `memory/`.
4. **Cut:** tighten at speaker changes first; inside one speaker's run only under cover (HKS-C17).

**Route order** (user, 2026-11-24: XML stays, as the last way): (1) copy the parent sequence in
Premiere and pick from it (`paste_from`, `arrange`, `keep_words`, `cut_copy`, `duplicate_sequence`);
(2) build from the footage only when no sequence holds the material yet; (3) an FCP7 XML in the day's
`CutDeck` folder only when Premiere can't be driven live, saying in the handover why 1 and 2 failed.
Details: `docs/DERIVE_FROM_SEQUENCE.md` step 5.

Checks before handover (each one listed in the handover, with timecodes):
- **Promises:** every question from the hook, the cards and the host is answered, or open on purpose (HKS-C13).
- **Middle:** no stretch of about 3–4 min without a new picture, a host question or a turn (HKS-C14).
- **Strongest lines:** each side's single strongest line, named, and kept (HKS-C15).
- **Ending:** if the story is open, the last line says so (HKS-C16).
- **Challenge notes** (HKS-C19): where the hook could hit harder, where an explanation or B-roll runs long,
  where a cut is snappy or clips a word at a camera switch. Snappy cuts: `output/hks_study/sliver_check.py
  <export or render> <pieces>` lists every shot under 0.4 s at an edit point (a flicker; a 0.7–0.9 s shot
  that reads before the switch is fine, HKS-C20); look at the frames before calling one.

First run, on the user's own 1123 cut: [study/20261123-checks.md](study/20261123-checks.md).

## Short versions and finishing (from the user's fixes, 2026-11-24)

What the user changed in the agent's highlight, FB and 1-min builds of 20261124 (why: [principles.md](principles.md)
HKS-C23 to C26; numbers: [memory/yt-20261124-draft.md](memory/yt-20261124-draft.md)). Confirmed by the user on 2026-11-24.

- **Music bed under the whole piece, never a gap** (already the rule in [workflow-log.md](workflow-log.md),
  "BGM under the whole show"; the agent's builds broke it twice). `[BGM]Where Everything Began.wav` looped:
  −24 dB under the hook, −33 dB under talk, −12 dB under the end sting (Premiere stores these as levels
  0.0112 / 0.00398 / 0.0447). The agent's FB left 59–162 s with no music; its hook bed had no level set.
  Check: every second of a short sits under one BGM clip, at the level for what plays there.
- **A flash at every section change, including the start of the body** (hook → sting → body): glitch
  (`Glitch redblue.mov`) + an invert AL frame + a whoosh just before the cut. The user added one at the
  sting → body join that the agent left plain.
- **Hook button = set-up + payoff** (HKS-C23). Before picking a hook's last line, read the line before it in
  the source; if the payoff needs it, take both.
- **Short body: no mid-body clip that's already in the hook** (HKS-C24). Check the source ranges of every
  body piece against the hook's; only the ending may overlap, and then with more than the hook showed.
- **Square reframe per shot** (HKS-C25). A cover zoomed for 16:9 needs a bigger zoom in the 1080² frame
  (the user: 263 → 333, 363, 368). Where the subject moves, razor the cover and re-position each part.
  Render a frame of each cover in the square before handover.
- **The 1-min ends on a held face under the sting** (HKS-C26), then the end card; target just under 60 s
  (the user's: 58.00).
- **Tighten under a cover, and let a piece start early for its set-up.** In the FB the user cut one 18 s
  piece into seven under a new B-roll cover, and started pieces 1.5–6.7 s earlier or later than the agent
  to catch the line that sets them up.
- **Clock blur in squares: the user's `Blur below logo` boxes, enabled, one per span.** The agent's
  disabled YT blur ALs were deleted, not kept switched off.
- **Reels:** the user built `4 REEL SIZE D1` and `5 REEL 1-3 SIZE D1` as workflow-log steps 7–8 say (nest
  the square, `1.png` frame on top; the 3-min nests a logo-less FB copy). Unchanged from 20261120.
- **Export when asked:** `python -m cutdeck.honekasae_export "<day folder>"` (one command; picks the
  same-named copy with content, queues all four in AME). The agent hand-rolled `export_sequence` calls on
  20261124 instead; use the command.

## Trims and split edits (confirmed by the user 2026-11-25)

From the user's fixes to the 20261124 YT body (why: [principles.md](principles.md) HKS-32, HKS-33).

- **Each piece starts where a thought starts and ends where it ends.** Before building, read every edge
  with 2 s of source on each side. An end must finish the sentence, including its closing particle
  (ครับ / นะ / เลย). A piece that opens on a joining word (เพราะ / แล้วก็ / คือ / แต่) brings the line
  before it, or moves. A Thai word can be split across engine words: the edge must be in a real pause,
  not just between two engine words.
- **Tighten inside a thought only under a cover**, and then as hard as needed (the user cut one 18 s piece
  into seven). In studio picture, keep the take whole.
- **Add a moment as its whole passage or not at all.** No 1–3 s bits joined mid-sentence to an approved cut.
- **Split the cut.** Put the picture change 0.5–2 s off the sound cut. J: the next voice starts under the
  last picture or cover, then the picture cuts to the speaker. L: the picture changes first and the voice
  ends under it. Build it on the upper tracks (the picture clip on V2+ starts or ends off the A1 cut;
  `premiere_edit_clips` trims one clip without its partner; recipe in PREMIERE_FACTS, "split edit").
- **The held picture must be safe** (user, 2026-11-25). In the extra 0.5–2 s of a J or L, the picture
  plays source the viewer doesn't hear. Nobody in it may be talking, by sight (lips, gestures) or in the
  source sound behind it. Only use it when the person has stopped talking or is still (a listening face,
  a still wide shot). If the source there isn't safe, hold **B-roll or a still person shot** instead (on
  V2+, from `Backup` or a listening face from elsewhere; or freeze a listening frame with Add Frame
  Hold, see the playbook below), or leave that cut straight. Check both before
  choosing the offset: the source words in the held span (none) and its frames (no mouth or hand
  moving). Sound and picture cutting on the same frame
  is the exception, kept for a real camera change or a section flash.
- **Check** before handover: list every visible studio edge that sits in running speech (`python -m
  cutdeck.timeline_transcript --prproj <day> --sequence <name> --track A1 --json`, `cuts_in_sound`, and
  look at each one that isn't under a cover). Count the sound cuts that are also picture cuts on the same
  frame; the user's 20261124 body had 30 of 180.

## Story first, then the speech (user, on YT agent v1, 2026-11-25)

The user's verdict on `1 YOUTUBE agent v1`: the storyline lost the context, cuts jumped into speech the
viewer had no set-up for, some cuts ended unfinished, and same-scene jumps showed.

- **Tell it like a film to someone seeing it the first time.** This is long form: before the guest's
  detail, give the viewer a taste of the context (who these people are, where, what happened between
  them), then go into the story picked for it. Never open a story part on a line that only makes sense if
  you already know the case. Rule 1's "get in fast" means no warm-up, not no context.
- **Never cut a thing that isn't finished.** A thought, a sentence or an answer is in whole or out
  (Trims and split edits). This held as a rule and still failed in v1: run the cut check and fix every edge
  it lists before handover.
- **A jump to another speech inside the same scene needs a cover.** Insert, B-roll or a still person
  (`Backup`) over the join; never two takes of the same shot butted together in plain view (rule 5).
- **J and L cuts are made on a copy.** Duplicate the clip, put the copy on the track above, and trim the
  copy. The raw clip stays untouched underneath as the backup; never trim the raw layer itself.
- **Blur: make the adjustment layer and draw the mask.** New adjustment layer, Gaussian Blur, then the
  Ellipse (circle) or Rectangle mask tool in Effect Controls; feather the mask. Don't stop at copying the
  user's layers or stack crops to fake a shape: learn how effects, adjustment layers and masks work and
  build what the shot needs. Masks have no API (PREMIERE_FACTS), so the mask tools are a Premiere UI
  route still to be proven here; explore Premiere's own tools before working around them.

## Timeline playbook: which move for which edit (agent, live 2026-11-25)

What I tried on a study copy of v4 and how each behaved (rows in `docs/PREMIERE_FACTS.md`, run
`20261125-120645-timeline-study`). On HKS's layered timeline (body V1/V2, covers V3+, sound A1), only
use moves that touch the clips I name; playhead keys reach every targeted track, covers included.

| Editor's move | When on HKS | How (proven) |
|---|---|---|
| J / L split | most speaker changes in studio | `edit_clips`: shrink one picture, then extend the other; sound untouched |
| Still person for a J/L hold | the held source shows someone talking | Add Frame Hold on a listening frame (menu, clip selected, playhead set): freezes from the playhead, no ripple |
| Roll an edit by frames | move a cut a few frames to a better word or face | Trim Edit + Ctrl+Right/Left (rolls only tracks with an edit there), or `edit_clips` trim pair |
| Ripple trim by frames | an end or start a few frames off, the rest follows | Trim Edit + Ctrl+Shift+T (ripple) + Ctrl+Right/Left |
| Slip | same length and place, different moment (better face, cleaner start) | select V+A, Ctrl+Alt+←/→ per frame (right = earlier source), or `edit_clips` trim_in +d, move −d, trim_out +d |
| Slide | move a short insert a few frames without changing it, neighbours absorb it | select V+A, Alt+, / Alt+. per frame |
| Find the source of a shot | where in the broadcast is this face / moment | Sequence > Match Frame (Source monitor at the exact frame) |
| Cutaway from the source | a listening face or B-roll over the talk | Match Frame or open the source, then `.` (overwrite) with the timeline playhead set; target only the V track you want |
| Insert a copied moment | put a set-up line in front of a punchline | Edit > Copy, playhead, Edit > Paste Insert (ripples every track) |
| Cut only some tracks | razor sound but not picture (or the reverse) | untarget tracks (Ctrl+0 video / Ctrl+9 audio), Add Edit, retarget |
| Ripple extend | an end that stops before the sentence ends ("มานานมาก \| นะ") | `edit_clips` move later clips +d, then trim_out +d; **also extend or split any cover spanning the edit** |
| Audio fade at a cut | a click or a breath at a sound cut | `set_param` Volume keyframes, 2–3 frames |
| Remove a stretch | tightening | `edit_clips` remove with ripple, V and A in one call |
| Cut on a repeated word | a stutter ("เหรอ เหรอ", "อยู่แล้ว อยู่แล้ว") | end on the first copy, start on the second: the user's way to tighten in plain view (seen in D1, 2026-11-25) |
| Fix an edge mid-word / mid-phrase | the check lists it | ripple-extend to the next gap of ≥ 0.2 s between words; pull back instead when the added words would be a dangling opener (แล้ว, ก็, คือ); skip when the added source already plays elsewhere |

Don't: Shift+Q/W or Q/W on a layered timeline (they trimmed the cover), E (disabled the clip instead of
extending), Insert Frame Hold Segment (ripples every track), Close Gap from the menu (did nothing). Mark
Clip takes the topmost clip (the cover), not the body. Track locks don't stop API edits. Linked Selection
on: a video-only selection + Clear does nothing.

The toolbar's mouse tools and their routes here: Razor (C) = Add Edit; Ripple (B) / Roll (N) = Trim Edit
+ nudges; Rate Stretch (R) = `premiere_set_speed`; Slip (Y) / Slide (U) = their frame keys; Pen (P) =
`set_param` keyframes; Track Select (A) = `select_clips` of every clip after a time; Type (T) =
`place_text`. Hand / Zoom only move the view. Undo one step at a time with a read-back:
a command that does nothing leaves no undo step, and a counted run of Undos goes too far.

## My own mistakes, and what stops each one (agent, 2026-11-25)

The user asked me to name my mistakes in my own words and build what prevents them. Each mistake has
a gate that runs before handover, not a reminder.

1. **I cut in the middle of a thought, sometimes in the middle of a word.** I checked edges against the
   engine's word boundaries and called them clean, but the engine splits Thai words ("กลัวน้ำตา | ไหล").
   v4 even opened on "เพราะ". *Gate:* `python -m cutdeck.hks_cut_check --prproj <day> --sequence <draft>
   --from <body start>`. It reads the audio, not the word list, and lists every cut in speech the viewer
   can see. I fix each one or say why it stays (a sentence end said without a pause, a repeated word).
2. **I added moments as 1–3 s bits joined mid-sentence** to an approved cut (v4's fun pass). *Gate:* the
   same list, plus "a moment goes in whole or not at all" (Trims and split edits).
3. **I cut sound and picture on the same frame, so the cut shows.** *Gate:* the check's same-frame count.
   Most cuts should be hidden under a cover or split as J/L; the user's 20261124 YT body has 12 of 173 on
   the same frame.
4. **A split edit can hold a picture of someone talking without their sound.** *Gate:* the check's
   "unsafe holds". Then I look at the frames of each one; where someone talks, I hold B-roll or a still
   person, or leave the cut straight.
5. **I trusted my own measure before testing it on the user's cut.** Here I first proposed "every edge
   in a pause", and the user's own finished cut would have failed it. *Gate:* any new check runs on the
   user's finished cut first and on my draft second. It's kept only if it separates them, or it's kept
   as a list to look at and said to be one (like hks_cut_check).
6. **I read a sequence the user had since changed** (FB v1 cut the host's question mid-line). *Gate:* read
   the parent sequence fresh (save + reader, or `read_timeline`) right before every derived build.
7. **I forgot the day's setup** (split `Edit` first, fill `Backup`, keepers up to V2 and linked). The user
   reminded me three times. *Gate:* "Draft workflow" step 1 plus `Backup`/`Edit` are done and listed in the
   handover before any draft is built.
8. **I left `(FAILED)` copies in the project when the panel crashed.** *Gate:* after a panel error, save,
   `reload_panel`, read back, finish the remaining steps, and list any failed copy in the handover for
   the user to delete. I never delete it myself.
9. **I built the story as a list of picked speeches, with no context first** (20261125 v1). *Gate:* before
   building, write the story's set-up in two lines (who, where, what happened) and check that the cut
   gives the viewer those facts before the first detail that needs them.
10. **I worked around Premiere instead of using it** (copied the user's layer, then faked a circle with
   crops for the blood blur). *Gate:* when a picture fix needs a Premiere tool (mask, effect), find and try
   that tool first; a workaround is the last way and gets named in the handover.

## Clip label colours (user, 2026-11-23)

The label colour of a clip says who speaks or what the piece is for. This replaces the
2026-11-20 log note "the colours themselves mean nothing": that note described topic
boundaries, not these meanings.

| Colour | Means |
|---|---|
| Pink | first guest (mainly the guest) |
| Purple | second guest |
| Blue | lawyer |
| Green | host |
| Yellow | must be in the video, or can be a highlight: hot spots such as a high-volume argument (user, 2026-11-25: the agent never used it) |
| Orange | ending sentences |
| Teal | caller phoned in |
| Light green | insert and video, or things that can be B-roll or a static person (cover) |

**Label per question, not per turn** (user, 2026-11-23: "just simple, like host asking guest 1
thats it color one … i mainly relate to question"): each question piece gets ONE colour, for the
person the host is asking. Don't split at every speaker change; both halves of a question cut by a
break share its colour. A host-only piece (intro, reading the news) is green.
Every draft the agent builds is labelled too (user, 2026-11-23: "you forget on all your draft"):
each body piece takes the colour of the question piece its source comes from, and every cover on
the upper tracks (B-roll, cutaway, zoomed insert) is light green.

Working layout seen the same day: the story is split at the topic marks; keepers go up to V2 with
their audio left on A1 and re-linked; drops (opening, breaks, sponsor, credits) stay on V1.

## Backup sequence = insert pool (user, 2026-11-23)

Inserts, B-roll, clips and static people not talking on camera go into the `backup` sequence
(1920x1080). A split screen (clip in a box beside the studio) counts as an insert: zoom it so the
clip fills the frame and **no edge of the split screen shows**. The user's own example: Scale 268,
Position (0.844, 0.640) on a 1280x720 source.

**Footage the broadcast already shows full screen is not zoomed** (user, 2026-11-25, red marker on the
20261125 `Backup`): Scale 100, Position (0.5, 0.5), clock and logo included. **Every zoom is centred** on what
it shows: the agent had shifted a full-screen insert to x 0.469 to hide the logo, and the user marked it.
Centre on the **video inside the box**, not the box: a phone clip sits in the box between blurred side fills,
often right of the box centre (20261125: video x 330–587 in a box x 28–821, centre 458 vs 424). Find the two
hard pillar edges (median |dx| per column over several frames), centre them, and zoom up until the box edge
can't show (Scale = 658 / the shorter distance from the video centre to a box side; 176–196 that day).

The zoom depends on the layout, so measure the box each time. 268 fits the two-box studio split
(box about x 32–804). The narrow three-box layout (box interior x 39–737, y 30–593) still showed
the studio strip at 268 and needed Scale 280, Position (0.8675, 0.6244). The user marked that miss
red on 2026-11-23. Check the left and right edges of every zoomed item in a rendered frame.

## Other rules, still in the log with their evidence

Not yet lifted out; each is a user rule recorded in [workflow-log.md](workflow-log.md):

- **Story opening, cuts, host and viewers:** Step 3 ("User rule for the story opening", "User rules
  for cuts", "User rules on the host and viewers").
- **Picture finishing** (clock blur, insert zoom, film damage): Step 5.
- **Sound bed and audio levels** (BGM loop, −33 / −24 / −12 dB): "Long form: sound bed and graphics"
  (the short form is lifted into "Short versions and finishing" above).
- **Facebook cut** (1080x1080, 2:59:24, main story only, same hook, no end logo): Step 6.
- **1-min and 3-min reels:** Steps 7–8.
- **Export** (BAS4, `<day folder>\5. EXPORTS`, `โหนกระแส <DDMMYY BE> <YT|FB|REEL 3M|REEL 1M> D<n>.mp4`):
  "Long form: sound bed and graphics" and the export notes at the end.
