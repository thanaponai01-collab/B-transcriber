---
name: hks-day-setup
description: "HKS day setup rules from the rule registry. Load when starting an HKS (โหนกระแส) editing day: before the transcript, the markers, the colours on `Editing` and the `Backup` sequence are set up, and before the paper edit."
---

GENERATED from projects/hks/registry by tools/hks_registry_build.py; do not edit.

# HKS day setup: rules and do-confirm

The 13 active `day_setup` rules in [the registry](../../../projects/hks/registry/rules/). A gate id names the `hks_gates` check that measures the rule.

- **HKS-16** **Select by labelled topics before cutting.** The whole broadcast is razored at every topic change and each topic gets a colour; then the cut is trimmed from the kept topics (n = 1; "no colour = drop" is not general). For drafts: produce this pass first; it is the user's own review format.
- **HKS-C31** **Hot spots are marked yellow first.** The must-keep moments (hot spots, high-volume arguments, what needs to be in the video) are chosen and marked yellow before the paper edit, so the cut is built around them. (gate `day_setup`)
- **HKS-X13** Topic and colour pass first (HKS-16): razor the broadcast at every topic change and label each topic by colour (`python -m cutdeck.split_pieces` lists the question pieces). The user approves what goes in before the agent cuts how. (gate `day_setup`)
- **HKS-X14** **Split-screen index.** List every stretch where the broadcast shows a split screen (evidence, B-roll). That is the cover pool (HKS-C9).
- **HKS-X69** **I forgot the day's setup.** Split `Edit` first, fill `Backup`, keepers up to V2 and linked. Gate: "Draft workflow" step 1 plus `Backup`/`Edit` are done and listed in the handover before any draft is built. (gate `day_setup`)
- **HKS-X73** **Label colours and what each means.** The label colour of a clip says who speaks or what the piece is for: Pink first guest; Purple second guest; Blue lawyer; Green host; Yellow must be in the video or can be a highlight (hot spots such as a high-volume argument); Orange ending sentences; Teal caller; Light green insert/video or cover material. Replaces the 2026-11-20 log note "the colours themselves mean nothing". (gate `day_setup`)
- **HKS-X74** **Label per question, not per turn.** Each question piece gets ONE colour, for the person the host is asking. Don't split at every speaker change; both halves of a question cut by a break share its colour. A host-only piece (intro, reading the news) is green.
- **HKS-X76** **Working layout: keepers to V2.** The story is split at the topic marks; keepers go up to V2 with their audio left on A1 and re-linked; drops (opening, breaks, sponsor, credits) stay on V1. (gate `day_setup`)
- **HKS-X77** **Backup sequence = insert pool.** Inserts, B-roll, clips and static people not talking on camera go into the `backup` sequence (1920x1080). A split screen counts as an insert: zoom it so the clip fills the frame and no edge of the split screen shows (example: Scale 268, Position (0.844, 0.640) on a 1280x720 source). (gate `day_setup`)
- **HKS-X78** **Full-screen footage not zoomed; every zoom centred.** Footage the broadcast already shows full screen is not zoomed: Scale 100, Position (0.5, 0.5), clock and logo included. Every zoom is centred on what it shows: centre on the video inside the box, not the box (find the two hard pillar edges, centre them, zoom until the box edge can't show).
- **HKS-X79** **Measure the box each time.** The zoom depends on the layout, so measure the box each time (268 fits the two-box split; the narrow three-box layout needed Scale 280, Position (0.8675, 0.6244)). Check the left and right edges of every zoomed item in a rendered frame.
- **HKS-X88** Mark the hot spots yellow on `Editing`, not just the question colours: the loud arguments (raised voices, people talking over each other), the clash, the admissions, the lines the story can't lose. Mark the closing lines orange. Yellow is the must-keep list for the YT and the pool for the hook and highlight. Use the audio level to find the loud stretches, then listen to each one. On 20261125 I coloured only per question and marked no yellow at all. (gate `day_setup`)
- **HKS-X105** `Backup` is 1920x1080, built at the YT frame size, never from `Editing` (720p). Every insert is scaled to fill it: full-screen footage Scale 150 centred; a boxed split screen zoomed to its box, centred, about 8 % past the box edge; no studio shot of the host or a guest, no edge of the show frame. Render the frames and look before using any as a cover. On 20261126 I built it at 1280x720 from `Editing`, unzoomed, and the user had to tell me ("make sure the backup is 1920x1080 and all broll scale up and fit the rules").

## Do–confirm

Each question needs a written answer in the handover, keyed by its rule id.

1. **HKS-16** Is the topic pass (boundaries and a label each) done before the cut?
2. **HKS-C31** Which stretches are marked yellow on Editing, and how were they found?
3. **HKS-X13** Is Editing razored at every topic change with a colour per piece, and when did the user approve the pieces?
4. **HKS-X14** Where is the list of every split-screen stretch (timecodes) used as the cover pool?
5. **HKS-X69** Are Edit split, Backup filled and keepers on V2 linked, and are they listed in the handover?
6. **HKS-X73** Which colours are on Editing, including yellow hot spots and orange endings?
7. **HKS-X74** Does each question piece on Editing carry one colour, for the person being asked?
8. **HKS-X76** Are the keepers on V2 with audio on A1 re-linked, and the drops left on V1?
9. **HKS-X77** How many items are in Backup, and does any zoomed split screen show an edge in a rendered frame?
10. **HKS-X78** Are full-screen items at Scale 100, and is every zoomed item centred on the video inside its box (values)?
11. **HKS-X79** In a rendered frame of every zoomed item, do both side edges show no split-screen border?
12. **HKS-X88** Which stretches are yellow and orange on Editing, and how were the loud ones found?
13. **HKS-X105** What frame size is Backup, what is each insert's scale and position, and which rendered frames did you look at?
