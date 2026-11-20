# HKS rule audit (build plan step 0.3)

Written 2026-11-20. Every rule in [HKS_BUILD_PLAN.md](HKS_BUILD_PLAN.md) came from one episode
(20261120). This audit checks each rule on all 11 day folders in `G:\Me\Works`. It measures and
reports. It changes no rule. **A rule that fails or is unclear goes back to the user before
anything is built on it** (questions at the end).

Regenerate every number below (about 25 min cold, 12 s with a warm cache):

    python -m cutdeck.hks_audit --all G:\Me\Works [--cache DIR] [--json out.json]

The frame checks named below were done by eye on frames that `cutdeck.hks_audit.grab_frame` pulled.

## How it measures

- **Reader:** `cutdeck/hks_gold.py` gives the YT keeps, cuts, hook end and show end. "Body" means
  after the hook (`body()`).
- **TV clock:** `cutdeck/hks_clock.clock_in_frame` runs on every second of each footage file and
  each latest YT export (1 fps, cached).
  - Positive control: a 20 s piece of 20261120 with the clock, scaled to 1920x1080 and encoded
    at 15 Mbit/s like the `BAS4` preset → 20 of 20 s detected.
  - Negative control: the same piece with a Gaussian blur over the clock box → 0 of 20.
- **Exports:** the latest `… YT/FB/REEL 1M D<n>.mp4` in `5. EXPORTS`. Every YT export lasts
  exactly the reader's show end, so the reader's timeline is the exported timeline.
- **Frame difference:** mean absolute RGB difference of two frames scaled to 1280x720 (0–255).
  - Rule 1 measures it twice per cut: on the source footage either side of the cut, and on the
    export one frame either side of the cut.
  - On all 294 cuts the two agree within 2.6. The reader's model of which footage shows at a
    cut matches the finished video.

## Rule 1: no jump cuts

Rule: an uncovered cut in the YT body is allowed only on a camera change.

| episode | body cuts | uncovered (reader) | under a frame hold | camera change (diff ≥ 20) | diff below 20 |
|---|---|---|---|---|---|
| 20261001 | 160 | 25 | 0 | 23 | 2 |
| 20261002 | 135 | 25 | 0 | 23 | 2 |
| 20261003 | 183 | 30 | 0 | 30 | 0 |
| 20261012 | 70 | 30 | 0 | 27 | 3 |
| 20261020 | 119 | 38 | 0 | 34 | 4 |
| 20261109 | 112 | 15 | 0 | 15 | 0 |
| 20261110 | 82 | 68 | 39 | 29 | 0 |
| 20261112 | 105 | 35 | 0 | 34 | 1 |
| 20261117 | 255 | 18 | 0 | 17 | 1 |
| 20261118 | 122 | 25 | 0 | 23 | 2 |
| 20261120 | 159 | 24 | 0 | 22 | 2 |
| **total** | **1502** | **333** | **39** | **277** | **17** |

**Threshold.** Calibrated on 20261120. Its 24 uncovered cuts are:

- 22 cuts with diff 27.7–95.8;
- the 2 same-shot cuts of the hand check (0.56 s → diff 6.0, 1.6 s → diff 12.7).

The hand check counted 22 uncovered cuts (20 angle changes, 2 same-shot). Which 2 of the 22
above it left out is not identified. On the 18:12 save (`p9`) the reader gives 24 uncovered
cuts with `min_jump_frames` 1 and 4 alike, so the difference is not the 3-frame jumps.
The hand check's low end of "27" is most likely the punch-in at tl 681.92, diff 27.7 (inferred).

The threshold sits at 20, in the gap between 12.7 and 27.7. I looked at the frames of 38 cuts
above it:

- 13 cuts with diff 20–33: 12 are real picture changes; 1 is the punch-in (below).
- All 25 cuts with diff 33–60: all are real picture changes (full frame, inset or window).
- The 239 cuts at 60 or more are counted as camera changes by the threshold alone.

**Below 20 the number alone cannot decide.** I looked at all 17 such cuts:

| episode | tl | jump s | diff | what the frames show |
|---|---|---|---|---|
| 20261001 | 149.60 | 17.44 | 17.6 | news-clip layout, the studio inset changes camera |
| 20261001 | 192.16 | 4.76 | 15.2 | news-clip layout, inset changes camera |
| 20261002 | 1017.68 | 18.88 | 1.8 | still picture (full-screen map) |
| 20261002 | 1035.40 | 15.88 | 1.7 | still picture (same map) |
| 20261012 | 790.40 | 6.04 | 11.9 | news-clip layout, inset changes camera |
| 20261012 | 957.96 | 4.16 | 11.2 | news-clip layout, inset changes camera |
| 20261012 | 967.52 | 38.32 | 12.8 | news-clip layout, inset changes camera |
| 20261020 | 155.76 | 3.44 | 0.2 | still picture (chat screenshot) |
| 20261020 | 157.72 | 5.16 | 0.2 | still picture (same screenshot) |
| 20261020 | 159.20 | 1.24 | 0.2 | still picture (same screenshot) |
| 20261020 | 780.08 | 9.00 | 14.4 | news-clip layout, inset changes camera |
| 20261112 | 481.20 | 0.72 | 0.4 | still picture (photo) |
| 20261117 | 492.72 | 2.48 | 10.7 | still picture (photo; only the headline banner changes) |
| 20261118 | 340.68 | 23.52 | 17.1 | news-clip layout, inset changes camera |
| 20261118 | 347.08 | 4.96 | 14.1 | news-clip layout, inset changes camera |
| 20261120 | 686.60 | 0.56 | 6.0 | **jump cut**: same shot (field interview) |
| 20261120 | 687.60 | 1.60 | 12.7 | **jump cut**: same shot |

- 7 cuts sit under a still picture. The picture does not move, so the cut cannot be seen.
- 8 are camera changes inside the small studio inset of the news-clip layout. The big window
  stays and the inset switches angle, so the whole-frame difference stays small.
- 2 are true jump cuts. Both are on 20261120 and were already known.
- Above 20, one cut is a **punch-in**: 20261120 tl 681.92, jump 1.48 s, diff 27.7. It is the
  same field camera, zoomed tighter, and the frame difference counts it as a camera change.

**20261110 (68 of 82 cuts uncovered) is a reader blind spot, not a different style.**

- 39 of its 68 uncovered cuts sit under `CutDeck_Hold_*.png` frame holds on V2. The holds are
  1920x1080 stills of social-media posts, shown as a slideshow at timeline 717.76–758.00 and
  796.96–806.80, and the audio is cut underneath them.
- `hks_gold.output_cut` builds the picture from footage clips only, so it sees the V1 main shot
  under the holds and calls the cuts uncovered. The frames of the export at tl 727 and 730 show
  the stills.
- Only 20261110 uses holds (a survey of the non-footage clips in all 11 bodies).
- The other 29 uncovered cuts are all camera changes, inside the 15–38 range of the other
  episodes.

**Verdict: holds, with three cuts to confirm, all on 20261120.** There are 294 uncovered cuts
that are not frame holds:

- 291 are on a camera change or under a still picture. 239 of them count by threshold alone.
- 2 are the micro same-shot cuts.
- 1 is the punch-in.

The rule as written is too narrow. It also has to allow:

- a camera change inside the studio inset;
- a cut under a still picture;
- possibly a punch-in.

## Rule 2: lengths

Rule: YT 15–20 min, FB exactly 179.96 s, 1-min exactly 59.96 s.

| episode | YT total | YT body (after hook) | body keeps s | FB | 1-min | export YT | export FB | export 1M |
|---|---|---|---|---|---|---|---|---|
| 20261001 | 1082.44 (18.0 min) | 1059.64 (17.7 min) | 1051.72 | 179.96 | 59.96 | 1082.44 | 179.96 | 59.96 |
| 20261002 | 1101.76 (18.4 min) | 1075.44 (17.9 min) | 1067.28 | 179.92 | 60.00 | 1101.76 | 179.92 | 60.00 |
| 20261003 | 1189.24 (19.8 min) | 1170.68 (19.5 min) | 1162.76 | 177.08 | 63.04 | 1189.24 | 177.08 | 63.04 |
| 20261012 | 1142.88 (19.0 min) | 1116.72 (18.6 min) | 1108.80 | 178.56 | 59.96 | 1142.88 | 178.56 | 59.96 |
| 20261020 | 1011.40 (16.9 min) | 984.48 (16.4 min) | 976.56 | 179.56 | 59.96 | 1011.40 | 179.56 | 59.96 |
| 20261109 | 1097.68 (18.3 min) | 1071.48 (17.9 min) | 1063.32 | 179.96 | 59.44 | 1097.68 | 179.96 | 59.44 |
| 20261110 | 1065.52 (17.8 min) | 1044.04 (17.4 min) | 1036.24 | 168.28 | 59.96 | 1065.52 | 168.28 | 59.96 |
| 20261112 | 1146.80 (19.1 min) | 1125.36 (18.8 min) | 1117.44 | 177.20 | 57.60 | 1146.80 | 177.20 | 57.60 |
| 20261117 | 1159.12 (19.3 min) | 1134.80 (18.9 min) | 1126.88 | 179.96 | 59.96 | 1159.12 | 179.96 | 59.96 |
| 20261118 | 1126.12 (18.8 min) | 1101.56 (18.4 min) | 1093.64 | 179.96 | 56.92 | 1126.12 | 179.96 | 56.92 |
| 20261120 | 1095.80 (18.3 min) | 1069.96 (17.8 min) | 1061.80 | 179.96 | 59.96 | 1095.80 | 179.96 | 59.96 |

- **YT:** total 16.9–19.8 min and body 16.4–19.5 min, all inside 15–20 min.
- **FB:** exactly 179.96 s on 5 of 11. All 11 are at most 179.96 (168.28–179.96).
  20261118 first exported 180.52 s (D1, D2) and re-exported 179.96 (D3). That looks like a
  ceiling of 3:00, not a fixed length.
- **1-min:** exactly 59.96 s on 6 of 11. The range is 56.92–63.04, and 2 are over 59.96
  (60.00 and 63.04).
- The reader and the exported files agree on every length.

**Verdict:** YT **holds**. FB and 1-min **fail** as exact lengths. FB fits "3:00 at most" on
11 of 11. The 1-min fits "about a minute" (±3.1 s).

## Rule 3: bumpers and sponsors dropped

Checkable now: inside the TV part, a run of 10 s or more with the clock off is a bumper, ad or
graphic candidate. The TV part starts at the first clock-on second and ends with the last
clock-on run of 30 s or more. Kept = YT keeps (audio) and YT covers (picture).

**Sponsors are not checked yet.** They are studio talk with the clock on, and need step 2.7.

| episode | file | TV part (s) | clock-on after it (s) | dips ≥10 s | dip seconds | kept audio in dips (s) | cover picture in dips (s) | kept before first clock (s) |
|---|---|---|---|---|---|---|---|---|
| 20261001 | hks youtube 011069 full | 21–1983 | 0 | 5 | 431 | 80.76 | 21.28 | 0.00 |
| 20261002 | hks youtube 021069 full | 23–2429 | 0 | 2 | 37 | 0.00 | 0.00 | 0.00 |
| 20261003 | hks facebook 051069 full | 21–2406 | 0 | 2 | 138 | 0.00 | 0.00 | 0.00 |
| 20261012 | hks youtube 121069 full | 28–2883 | 0 | 2 | 38 | 0.00 | 0.00 | 0.00 |
| 20261020 | hks facebook 201069 full | 22–2746 | 0 | 2 | 135 | 0.00 | 0.00 | 0.00 |
| 20261109 | hks facebook 091169 full | 20–2199 | 0 | 2 | 107 | 0.00 | 0.00 | 0.00 |
| 20261110 | hks facebook 101169 full | 22–3197 | 0 | 2 | 108 | 0.00 | 0.00 | 0.00 |
| 20261112 | files (2)–(5) | no clock | | | | | | |
| 20261112 | facebook 121169 (1) | 20–2409 | 0 | 2 | 124 | 0.00 | 0.00 | 0.00 |
| 20261117 | hks facebook 171169 full | 23–2481 | 0 | 2 | 123 | 0.00 | 0.00 | 0.00 |
| 20261118 | hks facebook 181169 full | 21–2628 | 0 | 2 | 123 | 0.00 | 0.00 | 0.00 |
| 20261120 | hks facebook 201169 full | 22–2820 | 0 | 2 | 120 | 0.00 | 0.00 | 0.00 |

What the dips are (frames at 30 % and 70 % of each dip):

| episode | dips (source s) | frames show | kept |
|---|---|---|---|
| 20261003, 1020, 1109, 1110, 1112, 1117, 1118, 1120 | two per episode, 46–72 s each | **TV commercials** (router, food, detergent, snack ads) | 0 |
| 20261002, 20261012 | two per episode, 18–19 s | the โหนกระแส bumper sting | 0 |
| 20261001 | 838–855, 1704–1723 | bumper sting | 0 |
| 20261001 | 257–558, 1320–1378, 1483–1519 | full-screen flood-map graphics; the station hides the clock | 80.76 audio, 21.28 picture |

- On 20261120 the two dips (819–876, 2006–2069) match the user's drops 824.56–877.20 and
  2004.88–2069.32 within 6 s.
- No episode keeps a second of a bumper or an ad.
- No episode keeps anything before the first clock-on second (the opening title).
- The kept clock-off picture on 20261001 is news content, not a bumper.
- Two side facts:
  - The feeds named `HKS Youtube …` (1001, 1002, 1012) carry a short sting at each break. The
    `HKS Facebook …` feeds carry about a minute of real ads.
  - The ads differ between episodes, so step 2.2's "match against reference clips" finds the
    stings and the opening but not the ads. A clock dip finds both, plus clock-free graphics.

**Verdict: holds for bumpers and ad breaks** (0 kept seconds in 22 bumper/ad dips on 11
episodes). **Sponsors: not checkable yet.**

## Rule 4: blur wherever the clock shows

Each episode's YT body is sampled every second, all 11 episodes.

- **Picture:** the topmost enabled footage clip or frame hold.
- **Zoomed:** a framing wider than the episode's main shot, which pushes the clock off screen.
- **Clock on screen:** the clock is on at that source second and the framing is the main shot.
  For a frame hold, the clock test runs on the PNG itself.
- **Blurred:** a clip with `AE.ADBE Gaussian Blur 2` (always an `Adjustment Layer 1920x1080`)
  spans the time on the picture's track or above.
- **Export column:** seconds of the body where the clock test fires on the finished YT export.
  This is the end-to-end check: an unblurred clock would show here.

| episode | body s | clock on screen s | blurred | unblurred | zoomed (clock pushed off) | blur without clock | unknown/none | export: clock seen s |
|---|---|---|---|---|---|---|---|---|
| 20261001 | 1060 | 315 | 315 (100 %) | 0 | 30 | 116 | 5 | 0 |
| 20261002 | 1075 | 431 | 431 (100 %) | 0 | 165 | 16 | 5 | 0 |
| 20261003 | 1171 | 414 | 414 (100 %) | 0 | 61 | 3 | 5 | 0 |
| 20261012 | 1117 | 488 | 488 (100 %) | 0 | 93 | 106 | 5 | 0 |
| 20261020 | 984 | 525 | 525 (100 %) | 0 | 6 | 1 | 5 | 0 |
| 20261109 | 1071 | 341 | 341 (100 %) | 0 | 104 | 30 | 5 | 0 |
| 20261110 | 1044 | 725 | 725 (100 %) | 0 | 29 | 0 | 5 | 0 |
| 20261112 | 1125 | 541 | 541 (100 %) | 0 | 2 | 123 | 5 | 0 |
| 20261117 | 1135 | 395 | 395 (100 %) | 0 | 18 | 18 | 5 | 0 |
| 20261118 | 1102 | 694 | 694 (100 %) | 0 | 21 | 21 | 5 | 0 |
| 20261120 | 1070 | 694 | 694 (100 %) | 0 | 153 | 45 | 5 | 0 |

The 5 "none" seconds per episode are the end logo. There are no unblurred ranges.

Blur without a clock (timeline seconds):

| episode | s | ranges | what it is |
|---|---|---|---|
| 1001, 1002, 1003, 1012, 1020, 1109, 1118, 1120 | 1–93 | over zoomed inserts (e.g. 20261120: 253–291, 645–656) | 20261120: the logo/credit blur on V9 over the insert's own watermark (user, workflow Step 5). The other seven: inferred to be the same, not checked. |
| 20261001 | 57 | 68–125 | full-screen flood maps in the TV part, no clock in the source. At tl 90 the export and the model's source frame match and the export's top-left is blurred. The long blur run continues over them. |
| 20261001 | 29 | 276–305 | unclear: at tl 290 the export shows a different framing of the map than the model's source frame (reader finding 2) |
| 20261012 | 13 | 253–266 | a zoomed news-window insert (chat screenshot) that the reader reads as unzoomed (reader finding 2). The zoom pushes the clock off, so this is blur over a zoomed insert. |
| 20261112 | 123 | 562–685 | file (2), which has no clock at all; at tl 600 the export matches the model and shows the top-left corner blurred anyway |
| 20261117 | 18 | 323–335, 366–372 | as 20261012: at tl 330 the export shows a zoomed chat that the reader reads as unzoomed |

Frame checks:

- 20261120 at tl 36.3 (clock on, blurred): the export shows a smeared box where the clock is.
- 20261001 at tl 90: the source has no clock, and the export's top-left is blurred.

**Model against export.** I compared the export frame with the model's source frame every 10 s
of all 11 bodies.

- 1,118 samples, median difference 3.3.
- 26 samples (2.3 %) differ by 30 or more. Their frames show two cases:
  - a news-window insert zoomed in the export while the reader sees no zoom (20261012, 1020,
    1109, 1117, 1118 and others);
  - a different picture or framing than the model's (20261001 tl 248/298, 1109 tl 831/841,
    1112 tl 66/486, 1118 tl 1120). Not explained.
- So the model columns above are right to within a few percent. The verdict rests on the export
  column.

**Verdict: holds.**

- 0 clock seconds in any of the 11 exports. This is the end-to-end check.
- In the model, 5,563 clock-on seconds in 11 bodies are 100 % blurred. A few percent of these
  are really zoomed inserts (see above).
- The blur also covers some clock-free picture: logo boxes over inserts, and the run continuing
  over clock-free graphics (20261001) or a clock-free file (20261112). Blurring exactly where the
  clock shows would blur less than the user does.

## Reader findings (hks_gold, hks_clock)

Found in step 0.3; findings 1 and 2 were closed in step 0.5 (2026-11-21), see the end of each.

1. **`hks_gold.output_cut` ignores frame holds.**
   - `pictures` holds footage clips only, so a `CutDeck_Hold_*.png` over a cut is invisible to
     it.
   - Effect: 20261110 shows 68 uncovered cuts instead of 29, and its `covers` list leaves the
     holds out.
   - Fix when wanted: treat a `CutDeck_Hold_*` still as a covering picture.
   - **Fixed (0.5):** a `CutDeck_Hold_*` still, or a footage clip with Premiere's Frame Hold, is a
     covering picture. 20261110 now shows 29 uncovered of 82 (`test_20261110_frame_holds_cover_their_cuts`).
2. **Zooms (and some pictures) the reader does not see.**
   - In 26 of 1,118 samples the export frame is not the model's picture (rule 4, "Model against
     export").
   - Example: at 20261117 tl 330 the export shows a zoomed chat screenshot. The topmost footage
     clip there (V4, 322.96–335.28, normal speed) reads as Motion 150 % centred, with no
     keyframes and no Transform effect.
   - Example: at 20261012 tl 261 the V3 clip has no Motion component in `effects` at all, yet the
     export shows it zoomed.
   - **Cause found (0.5): Premiere's Frame Hold.** Both example clips (20261117 V4, 20261012 V3)
     are frame-hold clips (`<FrameHold>` on the clip, the held source time in `FrameHoldStart`):
     they show one frozen frame, here a zoomed chat screenshot from earlier in the broadcast,
     not the moving footage the model sampled. The reader now returns `frame_hold`, and the
     audit samples the held frame. Re-run on all 11 (1,190 samples): **26 → 3** differ by 30 or
     more. The 3 left are all the same ending stack, listed with their cause:

     | episode | tl | cause |
     |---|---|---|
     | 20261003 | 1184 | footage slowed to 0.24× (0.68 s of source over 2.84 s) under `LAYER_ZOOM`, an adjustment layer with a Transform effect (`AE.ADBE Geometry2`) |
     | 20261109 (holdout) | 1091 | the same: 0.40× (1.24 s over 3.08 s) under `LAYER_ZOOM` |
     | 20261118 (holdout) | 1120 | the same: 0.41× (1.16 s over 2.84 s) under `LAYER_ZOOM` |

     The reader models neither clip speed nor the Transform effect, so a slowed clip anywhere is
     sampled at the wrong source time. Not checked: whether slowed clips occur elsewhere in the
     11 episodes without showing up in the 10 s samples.
   - Effect: it only touches the zoomed/clock split of rule 4 and `_framing` in `hks_gold`
     (a zoomed insert missed this way would make a cut look uncovered). The export check still
     shows no clock. Rule 1's source/export difference agrees on all 294 cuts.
3. **`hks_clock`:** nothing wrong found.
   - Positive and negative controls pass on a 1080p re-encode.
   - The clock-free stretches checked by eye (1001 flood maps, the 1112 files (2)–(5), the ad
     breaks) really have no clock.

## Questions for the user

1. **Jump cuts (rule 1):**
   - On 20261120 two tiny same-shot cuts remain (tl 686.60 cuts 0.56 s, tl 687.60 cuts 1.6 s,
     field interview). Fine as they are, or a slip?
   - Is a **punch-in** (same camera, tighter framing, 20261120 tl 681.92) allowed like a camera
     change?
2. **Allowed uncovered cuts (rule 1):** the past episodes also cut, uncovered:
   - when the **studio inset** of the news-clip layout changes camera (8 cuts);
   - under a **still picture** such as a chat screenshot, a map or a photo (7 cuts).

   Should the rule allow both?
3. **Frame holds as covers:** 20261110 covers 39 cuts with a slideshow of CutDeck frame holds.
   Is that a cover kind drafts may use, or a one-off?
4. **FB length:** is 179.96 s a **ceiling** (3:00 at most) rather than an exact length? Past FB
   cuts run 168.28–179.96, and 20261118 was re-exported from 180.52 to 179.96.
5. **1-min length:** past cuts run 56.92–63.04 s. Is "about a minute" right, or is 59.96 s a
   hard target that 20261002 (60.00) and 20261003 (63.04) missed?
6. **Blur extent:** you also blur picture without a clock: 20261001's flood maps, and all of
   20261112 file (2), which has no clock. Should the automatic blur follow the clock exactly,
   or cover the whole TV-part run as you do now?
7. **Breaks:** in the `HKS Facebook …` feeds each break is about a minute of real TV ads, not
   only the bumper. The ads change per episode, so reference matching (plan 2.2) can't find
   them; a clock-off run can. Is "drop every clock-off run in the TV part, except news
   graphics" the right rule? On 20261001 three such runs were flood-map graphics you kept.
