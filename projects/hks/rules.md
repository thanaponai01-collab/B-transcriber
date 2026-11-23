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
