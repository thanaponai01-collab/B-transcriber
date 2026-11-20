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
   project; 9 still have their footage (20261112 has none). Some sources are `HKS Youtube … Full`
   rather than `HKS Facebook …`; whether those carry the TV clock is unknown → step 0.2.
3. Timeline building is mostly proven in `PREMIERE_FACTS.md`:
   - placing clips: `createOverwriteItemAction`
   - moving one item to another track, video only: `createCloneTrackItemAction`
   - head trim: `createSetInPointAction`
   - copying a sequence: `createCloneAction`
   - adding effects: `VideoFilterFactory` + `createAppendComponentAction`
   - Motion writes: the `set_transform_field` command

   **Unproven:** blur limited to an area, audio levels, nesting a sequence, removing a track's items.
   → Phase 1.
4. Content cuts ("told twice", off-topic, side sections) need a language model. **User decision:**
   local model (Ollama, as `takes.py` supports) or an external API. The transcripts are broadcast
   content about real people. Until decided, Phase 4 ships without content cuts.

## Phase 0: Measure first
- [ ] **0.1** Fix `prproj_reader.parse_source_text` crashing on some text layers (16 in 20261120).
  → verify: a test built from one failing blob passes; `read_project` on the 20261120 snapshot
  runs unpatched.
- [ ] **0.2** Gold reader `cutdeck/hks_gold.py`. For one day folder it returns:
  - the `Edit` drops, the `1 YOUTUBE D1` kept source ranges and cover clips, the FB / 1-min ranges;
  - durations, and whether the TV clock is present in the footage.

  → verify on 20261120:
  - drops 0–22.68, 824.56–877.20, 2004.88–2069.32, 3947.00–4407.48, 4428.24–end (±0.05 s);
  - YT keeps 1065.2 s of footage in 155 cuts, 133 of them covered.

  Then it runs on all 10 other folders, with a table saying which are usable.
- [ ] **0.3** Rule audit across ≥3 past episodes:
  - no jump cuts: an uncovered cut is only allowed on a camera change;
  - YT 15–20 min, FB = 179.96 s, 1-min = 59.96 s;
  - sponsors and bumpers dropped;
  - blur present wherever the clock shows.

  → verify: a report table. **Any rule that fails elsewhere goes back to the user before it is built on.**
- [ ] **0.4** Scorer: a proposed keep/drop list vs gold. It reports:
  - seconds agreement;
  - boundary hits within 0.5 s;
  - precision per cut class (<0.6 s, 0.6–3 s, 3–15 s, ≥15 s);
  - jump-cut count;
  - length in range.

  → verify: gold vs itself = 100 %; "keep everything" gives the expected baseline numbers.

## Phase 1: Timeline-building spike ⚑ (riskiest; decides what Phases 3–6 can promise)
On a copied project, one probe per item. Each probe reads its result back, exports one frame,
and adds a `PREMIERE_FACTS.md` row.
- [ ] **1a** A source range, video only, on V2 at a given time (as a cover) → verify: read-back
  start/end/In within one frame, and V1 audio unchanged.
- [ ] **1b** A blur limited to an area (top-left clock box; a logo box). Try two ways:
  - an adjustment layer with Crop + Gaussian Blur, as the template's `Blur` items are built;
  - cloning the template's `BLUR TIME YT` / `Blur LOGO` items.

  → verify: an exported frame is blurred only inside the box.
- [ ] **1c** Audio clip level (Volume) at -33 / -24 / -12 dB → verify: read-back value, and
  measured loudness changes by the expected amount.
- [ ] **1d** Nest a sequence into another, duplicate a sequence, remove one track's items
  (the reel and the 3-min reel) → verify: read-back clip names and durations.
- [ ] **1e** Motion scale/position on a placed clip (insert zoom 271–405 %) → verify: read-back
  + frame.

**Outcome A** (all work): drafts are built as real sequences in Premiere.
**Outcome B** (gaps): drafts are markers + cut lists, plus the user's manual steps for the gaps.
The FCP7 XML route is the fallback only after its own Premiere-import check, which is still unproven.

## Phase 2: Episode analysis (offline, no Premiere) → `episode.json` + markers
- [ ] **2.1** Word transcript of the footage (existing engine) → verify: 20261120 matches the saved
  `full.words.json` (33,708 words, ±1 %).
- [ ] **2.2** Fixed graphics finder: opening title, break bumpers, end credits, matched against
  reference clips cut once from a past episode (audio fingerprint) → verify on 20261120:
  - opening 0–22.68;
  - the bumper parts of 824.56–877.20 and 2004.88–2069.32;
  - credits 4428.24–end, each within 0.5 s;
  - the same on ≥3 gold episodes.
- [ ] **2.3** TV clock presence per second, top-left. This drives the blur and the start of the
  social part; no OCR is needed, and break gaps are only the user's markers.
  → verify: present to 2815 s and absent from 2825 s on 20261120; matches gold blur ranges.
- [ ] **2.4** Picture layout per second: studio / news-clip window / full-frame footage / bumper.
  `topic_layout` calls full-frame CCTV "studio" today. → verify on labelled frames, including the
  44 s full-frame CCTV cover (source 583.92–627.96) as footage.
- [ ] **2.5** Camera-change times in studio picture (the only legal uncovered cut points) →
  verify: the 20 angle-change cuts of 20261120 all detected.
- [ ] **2.6** Host vs guest turns (`topic_speakers`) → verify: the host prompt cuts of story 1
  (266.04–298.80, 312.60–321.40) fall in host turns.
- [ ] **2.7** Sponsor candidates (transcript + position) → verify: both 20261120 sponsors flagged
  (≈824.56–860, 3947.00–4407.48), with false positives counted on the gold set.
- [ ] **2.8** ⚑ Write the findings as markers on the `Footage` sequence (`add_markers`) → verify:
  the user sees them in Premiere.

## Phase 3: Rough cut
- [ ] **3.1** Drop list = opening + bumpers + credits + sponsors the user approved. Applied with
  `apply_cuts` on a copy. → verify: keepers match the 20261120 `Edit` within 0.5 s per boundary,
  then on ≥3 gold episodes.

## Phase 4: Long-form story-cut draft (the 2 h step; the user approves)
- [ ] **4.1** Tighten (stumbles, pauses, false starts) **only where a cover is possible**: news-clip
  or footage picture, or a listener shot. In studio picture, cut only on camera changes (2.5).
  → verify: precision on gold <0.6 s and 0.6–3 s cuts; jump cuts = 0.
- [ ] **4.2** Host prompts, clarifications and opinions cut. A host connector is kept only where
  two guest pieces don't join. Viewer comments are always cut. → verify against gold host cuts.
- [ ] **4.3** Covers: B-roll from the same story (same moment first), else a static listener shot.
  Film damage goes on all B-roll; news-window clips are zoomed to fill the width (box detection).
  → verify: every non-camera-change cut is covered; the zoom fills the width (frame check).
- [ ] **4.4** Content cuts (retellings, off-topic, side sections such as backstory and legal
  analysis), ranked until the length lands at 15–20 min. **Blocked on the decision in Assumption 4.**
  → verify on gold: the dropped side sections match the user's (20261120: 34:56–41:09, 47:00–49:48).
- [ ] **4.5** Story opening: the guest's first story sentence, or the host's summary if the guest
  is slow → verify on gold story starts.

Interim slice, no model needed: the user marks the keep ranges per story; 4.1–4.3 and Phase 5 do
the rest.

## Phase 5: Finishing (mechanical, needs Phase 1 outcome A)
- [ ] **5.1** Blur track exactly where the clock is visible (2.3), plus the logo/credit blur boxes
  the user confirms → verify: same audit as 0.3 (0 missing, 0 extra).
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
  - 1080x1080, exactly 179.96 s;
  - built from the long-form pieces (climax, one side, aggressive last line) with the same hook;
  - B-roll filled, banner B-roll fitted, square logo, no end logo.

  → verify: length, and the pieces are a subset of YT.
- [ ] **6.2** 1-min square, exactly 59.96 s, nested into the reel frame; 3-min reel = the FB
  duplicate without the square logo, nested → verify: lengths, and the frame layer is on top.
- [x] **6.3** Export (done).

## Phase 7: Blocked on the user's answers
- Title-card text (~4 cards) and the reel headline, drafted for approval and filled into the
  After Effects template through the AE connection → **need:** where the template is, and which
  layers change.
- Live notes during the 2 h broadcast (Step 0) → **need:** what the notes contain.
- Thumbnails and upload: out of scope (the user does them).

## Order and why
1. 0.1 → 0.2 → 0.3 → 0.4: everything after is measured against the gold set.
2. Phase 1 next to Phase 2: the spike decides the output form; the analysis is useful either way
   (markers).
3. Phase 3 → 5.1 / 5.2 / 5.5: mechanical, big time savings, low judgment.
4. Phase 4: the biggest win and the hardest; it starts with the interim slice.
5. Phase 6, then Phase 7 as answers arrive.

## Decisions needed from the user
1. Content cuts: local model or external API (Assumption 4).
2. Where the AE title-card template is, and what changes per episode.
3. What the live notes contain.
