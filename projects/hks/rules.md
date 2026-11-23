# HKS (โหนกระแส) rules (how, today)

How the show is cut and finished today. Rules can change; the why behind them belongs in
[principles.md](principles.md). Values are this episode's examples, not presets.

**Status: under audit.** Every rule came from one episode (20261120). [rule-audit.md](rule-audit.md)
checks them on all 11 day folders. The user answered its seven questions on 2026-11-23 (end of
that file): rule 5 now allows inset camera changes and cuts under a still, and a punch-in needs
a cover.

**IDs:** `HKS-R<n>` = cut rule *n* below. Code cites the rule doc (`cutdeck/hks_*.py` →
[build-plan.md](build-plan.md) / [rule-audit.md](rule-audit.md)).

## Cut rules for the long form (step 3)

Moved word for word on 2026-11-22 from [workflow-log.md](workflow-log.md) (Automation candidates).

1. Get into each story fast: the guest's first story sentence, or the host's summary if the
   guest is slow.
2. (M-4) Each point told once. Drop retellings, off-topic asides, backstory, legal analysis and
   feelings that don't move events (shorten as much as possible).
3. Cut host prompts, clarifications and opinions. Keep a host connector only to bridge pieces
   that don't join. Host reactions may be added for drama.
4. Viewer comments read on air: always cut. Sponsors: always cut.
5. No jump cuts: in studio picture cut only at a thought end or a camera change. Cut hard
   (stumbles, pauses, repeats) only under a cover.
6. Cover = B-roll from the same story (ideally the same moment, this episode only), else a
   static listener shot (`Backup`). Film damage on all B-roll.
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
   - *No sponsor strip, no 3HD bug, no clock.* The phone clip before the second break (src
     2536.5–2584.6) carries the sponsor and credits strip (from y 521). Zoom it in, centred on the
     video: Scale 240, Position (0.475, 0.667), which keeps the source window x 260–1060, y 60–510.
   - *No snappy scene changes.* A camera change within 1 s of a visible cut leaves a sliver shot
     (marker 3: 0.16 s). Don't trim speech to fix it; hold the picture on V2 instead (keep the
     outgoing shot to the change, or bring the incoming shot in at it). The hold must show a
     masked face or a wide shot, never a talking host. Covers last at least 4 s.
7. Swear words bleeped. Same ending every episode.

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
| Yellow | must be in the video, or can be a highlight |
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

The zoom depends on the layout, so measure the box each time. 268 fits the two-box studio split
(box about x 32–804). The narrow three-box layout (box interior x 39–737, y 30–593) still showed
the studio strip at 268 and needed Scale 280, Position (0.8675, 0.6244). The user marked that miss
red on 2026-11-23. Check the left and right edges of every zoomed item in a rendered frame.

## Other rules, still in the log with their evidence

Not yet lifted out; each is a user rule recorded in [workflow-log.md](workflow-log.md):

- **Story opening, cuts, host and viewers:** Step 3 ("User rule for the story opening", "User rules
  for cuts", "User rules on the host and viewers").
- **Picture finishing** (clock blur, insert zoom, film damage): Step 5.
- **Sound bed and audio levels** (BGM loop, −33 / −24 / −12 dB): "Long form: sound bed and graphics".
- **Facebook cut** (1080x1080, 2:59:24, main story only, same hook, no end logo): Step 6.
- **1-min and 3-min reels:** Steps 7–8.
- **Export** (BAS4, `<day folder>\5. EXPORTS`, `โหนกระแส <DDMMYY BE> <YT|FB|REEL 3M|REEL 1M> D<n>.mp4`):
  "Long form: sound bed and graphics" and the export notes at the end.
