# HKS (โหนกระแส) automation: build plan

Written 2026-11-20 from the workflow recorded in [HONEKASAE_WORKFLOW.md](HONEKASAE_WORKFLOW.md).
Supersedes the slice list in [DESIGN_TOPIC_CUT.md](DESIGN_TOPIC_CUT.md); its findings stay valid.

**Goal:** after the footage arrives, the user reviews and approves drafts instead of cutting by
hand. Today one episode is ~4.5 h of editing after a ~2 h live; the long-form story cut alone is ~2 h.

**Rule for every step:** it ends with a check that passes, the tests stay green, and nothing
edits the user's day project. Live Premiere work runs on a **copied project** or a **copy of a
sequence**. ⚑ = needs a panel reload or the user's go-ahead.

## Already done
- Export: `python -m cutdeck.honekasae_export "<day folder>"` queues YT / FB / REEL 3M /
  REEL 1M in Media Encoder with the next D number and starts the queue (PR #105, live-proven).
- Pieces to reuse: transcription with word times (`faster_whisper`, `cutdeck/words.py`),
  silence/filler rules (`cutdeck/rules.py`), select-only LLM keep/cut (`cutdeck/takes.py`),
  studio-vs-clip frame classifier (`cutdeck/topic_layout.py`), host-vs-guest voice
  (`cutdeck/topic_speakers.py`), cuts on a sequence copy (`apply_cuts`), markers
  (`add_markers`), offline `.prproj` reader (`cutdeck/prproj_reader.py`).
- Evidence from episode 20261120 (project snapshots per save, word transcript, cut audit):
  `test_projects/hks_20261120/` (gitignored).

## Assumptions (check before relying on them)
1. The rules hold beyond one episode. All of them come from 20261120 → checked in step 0.3.
2. Gold set: 10 past day folders (`G:\Me\Works\2026xxxx - โหนกระแส`, 20261001 → 20261118) have a
   project and footage (checked in 0.2). 20261112's footage is split into 5 files; 20261003 names
   its outputs `D2`. Only 20261120 has an `Edit` sequence. Every source, `HKS Youtube … Full`
   included, carries the TV clock for its first 35–50 min.
3. Timeline building is mostly proven in `PREMIERE_FACTS.md`:
   - placing clips: `createOverwriteItemAction`
   - moving one item to another track, video only: `createCloneTrackItemAction`
   - head trim: `createSetInPointAction`
   - copying a sequence: `createCloneAction`
   - adding effects: `VideoFilterFactory` + `createAppendComponentAction`
   - Motion writes (scale, position): the `set_transform_field` command
   - removing items of one media type, leaving a gap: `createRemoveItemsAction(sel, false, type)`
   - an adjustment layer: imported from a seed project (`Project.importFiles`); there is no
     create call

   **Unproven:** Crop parameter writes (the blur box), audio levels, nesting a sequence, and
   **building at scale**: the recorded failures all came at hundreds of operations (a compound on
   an open sequence, a clone returning `undefined`, a Premiere crash). → Phase 1.
4. Judging by meaning needs a language model. It is needed for more than content cuts:
   - story units (2.9). Three timing rules failed on the 290969 episode; only picking by meaning
     worked (`DESIGN_TOPIC_CUT.md`);
   - sponsor candidates (2.7), host connectors (4.2), content cuts (4.4), story openings (4.5),
     hook ranking (5.4).

   **User decision**, three routes:
   - a local model (Ollama, as `takes.py` supports);
   - an external API;
   - the agent in a Claude Code session, which is how the 31 topic starts of 290969 were picked.

   The transcripts are broadcast content about real people. Until decided, these steps wait and
   the interim slice of Phase 4 carries the work.

## Phase 0: Measure first
- [x] **0.1** Fix `prproj_reader.parse_source_text` crashing on some text layers (16 in 20261120).
  → verify: a test built from one failing blob passes; `read_project` on the 20261120 snapshot
  runs unpatched. **Done:** the layers are a second format (u64 length + UTF-16 JSON); all 288
  across the 13 snapshots parse.
- [x] **0.2** Gold reader `cutdeck/hks_gold.py` (+ `cutdeck/hks_clock.py`). For one day folder it returns:
  - the `Edit` drops, the YT kept source ranges and cover clips, the FB / 1-min ranges;
  - durations, and whether the TV clock is present in the footage.

  How it reads a finished cut (all measured, see the module docstrings):
  - kept footage comes from the **audio**, not V1 (the main picture moves between V1 and V2);
  - show end = the last non-footage clip (the pool of unused footage sits after it);
  - hook end = the `Transition Complex 14` SFX;
  - a cut is **uncovered** when the picture on both sides is the main shot in sync with its audio,
    at the same framing (a zoomed insert of the same footage counts as a cover);
  - TV clock = four colon dots bright with a dark outline ring (no OCR).

  → verify on 20261120:
  - drops 0–22.68, 824.56–877.20, 2004.88–2069.32, 3947.00–4407.48, 4428.24–end (±0.05 s): **exact**;
  - the 18:12 save (`p9`): 159 cuts, 135 covered. The old "155 / 133" skipped four 3-frame
    jumps (`min_jump_frames=4` reproduces 155) and counted a main shot on V3 as a cover;
  - TV clock: present to 2815 s, absent from 2825 s; 0 false positives in 163 clock-free samples.

  Runs on all 11 folders with no problems: `python -m cutdeck.hks_gold --all G:\Me\Works`.
- [x] **0.3** Rule audit across all 11 past episodes → [HKS_RULE_AUDIT.md](HKS_RULE_AUDIT.md)
  (`python -m cutdeck.hks_audit --all G:\Me\Works`). Verdicts:
  - no jump cuts: **holds**, but wider than written: cuts on an inset camera change and under a
    still also occur; 3 cuts on 20261120 to confirm (two micro cuts, one punch-in);
  - YT 15–20 min: **holds** (16.9–19.8 min). FB = 179.96 s and 1-min = 59.96 s: **fail** as exact
    lengths (FB ≤ 179.96 on all 11; 1-min 56.92–63.04);
  - bumpers and ad breaks dropped: **holds** (0 kept seconds in 22 dips). Sponsors: not checkable
    before 2.7. The FB feeds carry real TV ads that change per episode, so 2.2 fingerprints won't
    find them;
  - blur wherever the clock shows: **holds** (no clock visible in any of the 11 exports).

  **Waiting on the user's answers**, per step (questions in the audit report):

  | question | blocks |
  |---|---|
  | 1–3: same-shot cuts, punch-in, inset and still cuts, holds as covers | 4.1, 4.3 |
  | 4: FB length. Likely a target of 179.96 s that is never exceeded (workflow log: "always 2:59:24"); **confirm** | 6.1 |
  | 5: 1-min length | 6.2 (the 1-min cut only) |
  | 6: blur extent | 5.1 |
  | 7: drop every clock-off run | 2.2, 3.1 |

  Nothing else waits on them: Phase 1, 2.1, 2.3–2.6, 5.2, 5.5 and the reels of 6.2 can start.
  (2.5 can detect inset changes and stills now; whether a cut there is legal waits on question 2.)
  Reader gaps found (→ 0.5, closed): `hks_gold` did not count `CutDeck_Hold_*.png` stills as
  covers (20261110), and misread some pictures (20261117 @ 330, 20261012 @ 261).
- [x] **0.4** Scorer `cutdeck/hks_score.py`: a proposed keep list vs the gold body keeps, in
  source time per file. It reports:
  - seconds agreement, keep precision and recall;
  - boundary hits within 0.5 s;
  - precision and recall per cut class (<0.6 s, 0.6–3 s, 3–15 s, ≥15 s);
  - jump-cut count;
  - length in range.

  → verify: gold vs itself = 100 % on 20261120, 20261117, 20261001. "Keep everything" matched the
  numbers predicted before the run (agreement 25.7 / 24.9 / 26.4 %, recall 100 %, boundaries 0).
- [x] **0.5** Close the reader gaps of 0.3:
  - count a `CutDeck_Hold_*` still as a covering picture → verify: 20261110 shows 29 uncovered
    cuts, not 68;
  - find why some zooms are not read (20261117 @ 330, 20261012 @ 261) and explain the 26 of
    1,118 samples where the export differs from the model → verify: each is fixed or listed with
    its cause.

  **Done:** 20261110 reads 29 uncovered of 82. The "missed zooms" were Premiere **Frame Hold**
  clips (one frozen frame, here a zoomed chat screenshot): the reader returns `frame_hold`, and
  `hks_gold` and the audit treat a held clip as a still. Re-run on all 11: 37 → 3 of 1,190
  samples differ (the 26 of 1,118 came from a first script that sampled differently).
  The 3 are the closing stack (slowed footage under a `LAYER_ZOOM` Transform),
  listed with their cause in [HKS_RULE_AUDIT.md](HKS_RULE_AUDIT.md), reader finding 2.
  Nine cuts under a held frame moved to covered (20261001 25 → 23, 20261002 25 → 24, 20261003
  30 → 29, 20261112 35 → 32, 20261117 18 → 16): 285 uncovered in all, 270 on a camera change.
  For 4.3: a held frame of the footage is a cover kind the user uses in 9 of 11 episodes.
- [x] **0.6** Holdout. Every threshold so far was tuned on 20261120. Keep 20261002, 20261109 and
  20261118 out of all tuning from here on; a step that says "on the gold set" tunes on the other
  eight and reports the holdout score once, at the end. → verify: `hks_score` and `hks_audit`
  take the holdout list and report it separately. **Done:** the list is `hks_gold.HOLDOUT`.
  - `hks_audit --all` and `hks_score --all --baseline …` cover the eight tuning episodes; with
    `--holdout` the three get their own tables, never mixed in. A single holdout folder is
    refused without the flag.
  - Gold against itself is 100 % on all eight and on all three.
  - `hks_score --all` takes the two built-in baselines only: a proposal file is still one day's.
  - Not blind before today: step 0.3 looked at all 11 episodes, and the frame-hold fix of 0.5
    was found on tuning episodes and then counted on all 11. The holdout is clean for tuning
    from here on. `hks_gold --all` still lists all 11 (it reads, it does not tune).

## Phase 1: Timeline-building spike ⚑ (riskiest; decides what Phases 3–6 can promise)
On a copied project, one probe per unknown. Each probe reads its result back, exports one frame,
and adds a `PREMIERE_FACTS.md` row. Already proven and not probed again: removing one track's
items, Motion scale and position, an adjustment layer with an appended effect.
- [x] **1a** A source range, video only, on V2 at a given time (as a cover), then Motion scale
  and position on that fresh clip (insert zoom 271–405 %) → verify: read-back start/end/In within
  one frame, V1 audio unchanged, and an exported frame shows the zoom. **Done (live 2026-11-21,
  probe `hks1a`):** source 600–604 landed at 100.00–104.00, In 600.00, 300 % at 0.45/0.40 read
  back; the exported frame matches that zoom (diff 1.2 vs 47.6 unzoomed). Catch: audio index -1
  puts the audio on A1 over the dialogue, so the audio goes to a new track and is removed there
  (A1–A6 unchanged).
- [x] **1b** A blur limited to an area (top-left clock box; a logo box). Try two ways:
  - an adjustment layer with Gaussian Blur and a Crop write (Crop writes are OPEN in
    `PREMIERE_FACTS.md`), as the template's `Blur` items are built;
  - cloning the template's `BLUR TIME YT` / `Blur LOGO` items.

  → verify: an exported frame is blurred only inside the box. **Done, both routes work (probe
  `hks1b`):** the clone keeps the template's effect mask (only the clock box changed); a fresh
  adjustment layer + Gaussian Blur + Motion crop blurs only the crop box. The YT clock blur is an
  effect mask, which no API can draw, so a new box shape means cloning a template item; a
  rectangle can use the crop route.
- [x] **1c** Audio clip level (Volume) at -33 / -24 / -12 dB → verify: read-back value, and
  measured loudness changes by the expected amount. **Done (probe `hks1c`):** Level is linear,
  dB = 20·log10(v) + 15; renders measure -12.00 / -24.00 / -33.00 dB exactly.
- [x] **1d** Nest a sequence into another, and duplicate a sequence (the reel and the 3-min
  reel) → verify: read-back clip names and durations. **Done (probe `hks1d`):** the FB copy reads
  125 / 65 items and 179.96 s like the original; the square's project item placed into a reel copy
  lands as a nested clip "3 SQUARE SELECT D1", 0–59.96, and renders.
- [x] **1e** Replay at scale, after 1a–1c. Rebuild the finished `1 YOUTUBE D1` of 20261120 on a
  copy, with the sequence closed while it is built:
  - the keeps and covers (about 160 cuts) from `hks_gold`;
  - the blur layers, film damage and 22 music pieces from `prproj_reader` (`hks_gold` does not
    return them), each only if its probe (1b, 1c) passed.

  → verify: every item the build placed reads back within one frame of the saved project, and
  the build runs twice without a failed action or a crash.

  **Done (live 2026-11-21, `python -m cutdeck.hks_build … --run --save`, panel `build_sequence`):**
  - 370 items on a cleared copy, three runs. No run had a refused action or a crash (17, 33 and
    22 s). Run 1 ran on panel code loaded before the project guard existed, so runs 2 and 3 are
    the two runs that count.
  - The copy is never opened: after a build, the active sequence is still the one that was
    active before.
  - Read-back: 344 video and 238 audio items, 0 off by more than a frame.
  - The saved project, diffed offline with `--compare`, gives 0 differences in timing, Motion
    and Level against the original on all three runs, and the original reads unchanged. A
    smoke build compared as the full list gives 364, so the diff does catch differences.
  - Exported frame at 50 s (`run_probe hks1e`): it matches the original outside the clock box
    (mean difference 0.11 of 255). Inside, both are blurred, but the crop route is a
    hard-edged rectangle that reaches a little lower than the template's feathered mask.
    For 5.1, clone a template blur item (route 1) where the look must match.
  - The whole list comes from `prproj_reader`, keeps and covers included, not from `hks_gold`.
    The reader gives the placed clips themselves, with the track, the Motion and the source
    file, which is what a replay needs. `hks_gold` gives source ranges only.
  - Not replayed (`skipped` in the output), with the step each one touches:
    - speed-changed clips (6) and keyframed Motion: 5.4, the hook and closing stack;
    - film damage's Opacity component (83). It reads as a plain 100 %; the reader does not
      decode a blend mode, so whether the look matches is unknown: 4.3 and 5.4;
    - the 3 V9 blur boxes, whose box was never measured: 5.1;
    - graphics, AE comps, SFX and the end logo: 5.4, 5.5 and Phase 7.

    Blurriness is a fixed 60, because the reader returns no Gaussian Blur params.

**Outcome: A**, so drafts are built as real sequences. Each piece not replayed above gets its
own probe in the step named next to it.

**Outcome A** (all work, 1e included): drafts are built as real sequences in Premiere.
**Outcome B** (gaps): drafts are markers + cut lists, plus the user's manual steps for the gaps.
The FCP7 XML route is the fallback only after its own Premiere-import check, which is still unproven.

## Phase 2: Episode analysis (offline, no Premiere) → `episode.json` + markers
- [ ] **2.1** Word transcript of the footage (existing engine), for **all 11 episodes** (about
  12 min each). With the gold cuts this gives the words under every one of the 1,502 cuts, so
  Phase 4 is scored per cut class on every episode. → verify: 20261120 matches the saved
  `full.words.json` (33,708 words, ±1 %); each of the other 10 has words across its whole length.
- [ ] **2.2** Break and fixed-graphics finder. Two signals, because neither covers everything:
  - a clock-off run of 10 s or more inside the TV part: bumpers, the real TV ads of the Facebook
    feeds (they change per episode, so reference clips cannot find them) and clock-free graphics.
    A run is a candidate, not a drop: on 20261001 three such runs were flood maps the user kept
    (audit question 7);
  - reference clips cut once from a past episode (audio fingerprint): the opening title, the
    end credits and the bumper sting. The clock cannot find the credits, which sit in the
    clock-free social part.

  The clock dips matched the user's drops only within 6 s, so the fingerprint or a silence or
  scene edge has to place the exact boundary.
  → verify on 20261120, the only episode with an `Edit` sequence, each within 0.5 s:
  - opening 0–22.68;
  - the bumper parts of 824.56–877.20 and 2004.88–2069.32;
  - credits 4428.24–end.

  → verify on the other gold episodes, one-sided: no second of a proposed drop is kept in the YT
  cut, and the 22 bumper and ad dips of the audit are all covered (the three flood-map dips of
  20261001 are not drops).
- [ ] **2.3** TV clock presence per second, top-left. This drives the blur and the start of the
  social part; no OCR is needed, and break gaps are only the user's markers.
  → verify: present to 2815 s and absent from 2825 s on 20261120; every clock-on second shown at
  the main framing is inside a gold blur range (the gold blur is wider than the clock, see 5.1).
- [ ] **2.4** Picture layout per second: studio / news-clip window / full-frame footage / bumper.
  `topic_layout` calls full-frame CCTV "studio" today. → verify on labelled frames, including the
  44 s full-frame CCTV cover (source 583.92–627.96) as footage.
- [ ] **2.5** Legal uncovered cut points: camera changes in studio picture, camera changes inside
  the studio inset of the news-clip layout, and still pictures (the last two pending audit
  question 2). Whole-frame difference misses the inset changes (11–17, below the threshold of
  20), so the inset is measured on its own box. → verify:
  - recall: of the 270 camera-change cuts and the 13 inset and still cuts of the audit, the
    share detected;
  - precision: on a hand-labelled 10 min of 20261120, the share of detections that are real.
- [ ] **2.6** Host vs guest turns (`topic_speakers`) → verify: the host prompt cuts of story 1
  (266.04–298.80, 312.60–321.40) fall in host turns, and a hand-labelled 10 min gives host
  precision and recall (a detector that calls everything host must fail).
- [ ] **2.7** Sponsor candidates (transcript + position; needs the model, Assumption 4). The
  second sponsor sits in the social part, where the clock gives nothing. → verify: both 20261120
  sponsors flagged (≈824.56–860, 3947.00–4407.48). The other episodes have no sponsor labels:
  count there the flagged seconds that the user kept in the YT cut (false positives).
- [ ] **2.8** ⚑ Write the findings as markers on the `Footage` sequence (`add_markers`) → verify:
  the user sees them in Premiere.
- [ ] **2.9** Story units, picked by meaning (Assumption 4), then snapped to a legal cut point
  (2.5). 4.3 ("same story") and the interim slice need them. Two levels:
  - topic starts (a host question opens one);
  - stories: consecutive topics about the same incident. There is no gold for this grouping
    yet; on 20261120 the user confirms it once from the section table in the workflow log.

  → verify: the share of the 32 reviewed starts of 290969
  (`tests/data/topic_cut_starts_hks290969.json`) hit within 1.5 s is at least the 24 that the
  first hand picks reached, and the same share on the label-colour boundaries of 20261120
  (workflow log, Step 2).

## Phase 3: Rough cut
- [ ] **3.1** Drop list = opening + bumpers and ads + credits (2.2) + sponsors the user approved
  (2.7). Applied with `apply_cuts` on a copy. → verify: keepers match the 20261120 `Edit` within
  0.5 s per boundary. On the other gold episodes, which have no `Edit` sequence: no dropped
  second is kept in the YT cut.

## Phase 4: Long-form story-cut draft (the 2 h step; the user approves)
- [ ] **4.1** Tighten (stumbles, pauses, false starts) **only where a cover is possible**: news-clip
  or footage picture, or a listener shot. In studio picture, cut only on camera changes (2.5).
  → verify: precision on gold <0.6 s and 0.6–3 s cuts; jump cuts = 0.
- [ ] **4.2** Host prompts, clarifications and opinions cut. A host connector is kept only where
  two guest pieces don't join. Viewer comments are always cut. → verify against gold host cuts.
- [ ] **4.3** Covers: B-roll from the same story (same moment first), else a static listener shot.
  Film damage goes on all B-roll; news-window clips are zoomed to fill the width (box detection).
  The cover candidates come from a finder: news-clip and footage picture of the same story
  (2.4 + 2.9), and listener shots. **Open:** no step says who is on screen (2.4 gives the
  layout, 2.6 the host's voice), so listener shots come from the user's `Backup` pool until one
  does.
  → verify: every non-camera-change cut is covered; the zoom fills the width (frame check); the
  finder's candidates include the source of the covers the user chose (recall on gold covers).
- [ ] **4.4** Content cuts (retellings, off-topic, side sections such as backstory and legal
  analysis), ranked until the length lands at 15–20 min. **Blocked on the decision in Assumption 4.**
  → verify on gold: the dropped side sections match the user's (20261120: 34:56–41:09, 47:00–49:48).
- [ ] **4.5** Story opening: the guest's first story sentence, or the host's summary if the guest
  is slow → verify on gold story starts.

Interim slice, no model needed: the user marks the keep ranges per story; 4.1–4.3 and Phase 5 do
the rest.

## Phase 5: Finishing (mechanical, needs Phase 1 outcome A)
Every step here takes a finished long form as its input, whoever cut it. It is built and
checked on the user's hand cut first, before Phase 4 exists.
- [ ] **5.1** Blur track wherever the clock is visible (2.3), plus the logo/credit blur boxes
  the user confirms. The user blurs more than that today (a whole run over clock-free maps on
  20261001, a clock-free file on 20261112); the extent waits on audit question 6. → verify: the
  export check of 0.3 (0 clock seconds in the export); "0 extra" only if the answer is "follow
  the clock exactly".
- [ ] **5.2** Music bed `[BGM]Where Everything Began.wav`:
  - looped with 3 s overlaps;
  - -24 dB under the hook, -33 dB under the body, -12 dB at the end.

  → verify: read-back levels, and the loop covers the full length.
- [ ] **5.3** Bleeps on swear words (word list + transcript) → verify: the swear at 1693.00 is found;
  precision on gold bleeps.
- [ ] **5.4** Hook template:
  - title cards;
  - a swoosh at each card change;
  - film damage, the adjustment layer and the transition into story 1.

  Soundbites are ranked (climax / most violent or emotional / "what!?"), and the user picks.
  → verify: same structure as the 18:32 save.
- [ ] **5.5** Ending: goodbye → sting → `CG_END LOGO` (YT only) → verify.

## Phase 6: Versions
- [ ] **6.1** FB:
  - 1080x1080, target 179.96 s and never 180 s or more (past cuts run 168.28–179.96; audit
    question 4 to confirm);
  - built from the long-form pieces (climax, one side, aggressive last line) with the same hook;
  - B-roll filled, banner B-roll fitted, square logo, no end logo.

  → verify: length, and the pieces are a subset of YT.
- [ ] **6.2** Two parts:
  - the 1-min square cut. Length waits on audit question 5 (past cuts run 56.92–63.04 s, 6 of
    11 at 59.96);
  - the reels, with no judgment and no open question: the 1-min square nested into the reel
    frame; 3-min reel = the FB duplicate without the square logo, nested. Built first on the
    user's own FB and 1-min cuts.

  → verify: lengths, and the frame layer is on top.
- [x] **6.3** Export (done).

## Phase 7: Blocked on the user's answers
- Title-card text (~4 cards) and the reel headline, drafted for approval and filled into the
  After Effects template through the AE connection → **need:** where the template is, and which
  layers change.
- Live notes during the 2 h broadcast (Step 0) → **need:** what the notes contain.
- Thumbnails and upload: out of scope (the user does them).

## In the workflow log, not planned yet
- Step 1: copy the day folder from the template, name the project, import the master.
- The Essential Sound **Dialogue** preset on the footage audio (no proven API for it).

## Order and why
1. 0.1 → 0.6 (done): everything after is measured against the gold set.
2. Phase 1 next to Phase 2 (2.1–2.6 on all 11 episodes): the spike decides the output form; the
   analysis is useful either way (markers).
3. Phase 3, then the mechanical finishing on the user's hand cut: 5.1 / 5.2 / 5.5 and the reels
   of 6.2. None of it waits for Phase 4. 3.1 waits on question 7 and on approved sponsors; 5.1
   on question 6.
4. Phase 4: the biggest win (the ~2 h step) and the hardest; it starts with the interim slice.
5. 5.3 / 5.4, 6.1 and the 1-min cut (FB ~50 min, hook ~20 min, 1-min ~10 min of the user's time
   today), then Phase 7 as answers arrive.

## Decisions needed from the user
1. Which model route judges by meaning: local, external API, or the agent in a session
   (Assumption 4). It gates 2.7, 2.9, 4.2, 4.4, 4.5 and 5.4.
2. The seven rule questions in [HKS_RULE_AUDIT.md](HKS_RULE_AUDIT.md) (4 is likely answered;
   confirm).
3. Where the AE title-card template is, and what changes per episode.
4. What the live notes contain.
