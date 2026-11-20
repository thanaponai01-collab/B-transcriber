# Honekasae (โหนกระแส) workflow log

Started 2026-11-20. The user does the job by hand and reports each step; we record it here,
then work out together which steps can become a repeatable workflow and, later, automation.

Related existing work: [DESIGN_TOPIC_CUT.md](DESIGN_TOPIC_CUT.md) (topic cut of the live feed:
layout classifier, host-question topics, studio-cut snapping; partly built in
`cutdeck/topic_layout.py`).

## How each step is recorded
- **Do:** what the user did, in their words.
- **Input → output:** files, apps, where they live.
- **Decisions:** what the user judged by eye/ear and how (the rule behind it).
- **Time:** roughly how long it took.
- **Automate?** manual / assist / automate, what we already have that covers it, open questions.

## Steps

### Step 0: Watch the live (user)
- The user **watches the live broadcast (~2 hours) and takes notes**, then waits for the
  footage file and starts editing. _ask: what goes in the notes (story list, timestamps, hook
  moments, title-card ideas)?_
- **Scope (user):**
  - **Thumbnails stay manual** for now (user does them).
  - **Upload is out of scope:** we stop at export, the user uploads.
  - `3 SQUARE SELECT D1` is the **1-minute** version (next step after FB).

### Step 1: Open Premiere, import the Project Manager master (2026-11-20)
- **Do:** open Premiere, import the already-corrected Project Manager project into the
  day's project.
- **Input → output:**
  - Day folder `G:\Me\Works\20261120 - โหนกระแส\` (standard template tree: `1. FOOTAGE` …
    `8. THUMBNAIL`). Project `4. PROJECTS\1. PREMIERE PRO\20261120 - โหนกระแส.prproj`;
    older templates kept in `zOLD`.
  - Master (Project Manager output): `G:\Me\1.All Pr&Ae\3-AnyMind\Project โหนกระแส\1 Assets\
    Project_Horn Kra Sae\PROJECT MANAGER\PROJECT MNG 20230808 - รวมโหนกระแส` (174 of the clip
    uses in the project point here). Music from `...\AnyMind Music Library\Dramatic`.
    An older copy sits at `E:\Me\work\Project_Horn Kra Sae\PROJECT MANAGER\`.
  - What came in (read from the saved .prproj at 15:36):
    - Empty output sequences, one per platform: `1 YOUTUBE D1`, `2 FACEBOOK D1`,
      `3 SQUARE SELECT D1`, `4 REEL SIZE D1`, `5 REEL 1-3 SIZE D1`. **Each appears twice**
      (template's own and the imported master's).
    - Pattern sequences `Plattern_YT SIZE` (132 clips) and `Plattern_FB SIZE` (123): a library
      of the show's building blocks laid on a timeline. Intro (FT VIDEO_EX, SFX_โหนกระแส),
      quote cards (black tone + vignette + zoom + film damage + glitch + invert flash +
      Thai text graphic), insert/people frames, red-blue-black lower-third box with a headline
      Graphic, end logo, blur-logo masks, BGM beds, the โหนหลังกระแส sub-brand
      (thumbnail, lower thirds, end title/endscreen), AnyMind logos.
    - Bins: 01 Footage … 08 Dynamic Links, PR_2023 Plattern โหนกระแส [FOR WFH], โหนหลังกระแส.
  - Already started: `1 YOUTUBE D1` holds 4 After Effects linked comps (Comp 02–05,
    0–21.9 s) from `2. AFTER EFFECT\Untitled Project.aep`. `1. FOOTAGE\20 nov\` has 3
    screenshots (13:03, 13:18, 13:44).
- **Decisions:** _ask:_ what "corrected" means in the master (relinked? cleaned?).
- **Time:** _ask._
- **Automate?** **automate.** Copying the day folder from the template, naming the project
  `YYYYMMDD - โหนกระแส`, and importing the master are mechanical. Could become one script.
  Watch out: the duplicated output sequences.
- **Tooling note:** `cutdeck/prproj_reader.py` crashes on 16 text layers in this project
  (`parse_source_text` struct.error, on track V13/V14 graphics). Worked around for this read;
  needs a fix before the reader can be relied on for this show.

### Step 2: Get the footage, rough-cut it, start thumbnails (2026-11-20, ~15:38–16:01)
Read from the saved .prproj at 16:01 plus file times. Not yet confirmed by the user.
- **Footage:** `1. FOOTAGE\HKS Facebook 201169 Full.mp4`: 74:08, 1280x720, 25 fps, AAC 48k
  stereo, 3.4 GB. Copied in 15:38–15:39; the file's creation tag is 14:52 local.
  Naming: `HKS Facebook <DDMMYY in Buddhist Era> Full.mp4`.
- **Sequences built:**
  - `Footage`: the whole file.
  - `Edit`: the file split into pieces. **Drops are left on V1, keepers moved to V2.**
    Dropped (source time, with the frame we saw):
    | from–to | length | what it is |
    |---|---|---|
    | 0–22.68 | 23 s | show opening title |
    | 824.56–877.20 | 53 s | VTR insert (phone chat) + โหนกระแส break bumper |
    | 2004.88–2069.32 | 64 s | break bumper |
    | 3947.00–4407.48 | 7:40 | studio talk with products on the desk: sponsor/advertorial? _ask_ |
    | 4428.24–end | 20 s | end credits (Dee Kuen Dee Won logo) |
    Keepers have further cuts at 266.04, 803.56, 935.96, 1714.72, 1924.80, 2096.12, 2469.20,
    2820.20, 2988.16, 3726.56, 3888.84: topic boundaries? _ask_
  - `1 YOUTUBE D1`: AE intro comps (0–21.92) then keepers from 26.76, source order kept,
    with **gaps** at 828.64–895.68 (67 s), 2023.36–2102.00 (79 s), 2852.88–2958.68 (106 s):
    slots for something? _ask_
  - `Backup`: two short pieces (source 255.56 and 755.56). _ask_
- **Thumbnails:** `PSD-REEL\20261120 - YT Thumbnail.jpg` (15:45) and `- FB Thumbnail.jpg`
  (15:47), exported from `Thumbnail\20260515-โหนกระแส-News-Thumbnail.psd`; the Reel PSD and
  `1.png` were saved at 15:47.
- **User answers (2026-11-20):**
  - 65:47–73:27 is a **sponsor segment: always cut.** 13:45–14:37 (phone-chat clip + bumper)
    is **sponsor too.**
  - **Clip label colours = topic boundaries.** A new topic starts where the host asks a
    question.
  - `Backup` = **B-roll pool for inserts**: while watching, the user pulls usable shots
    (the scene, a person doing nothing) to cover cuts later.
- **Label colours read from the project** (Premiere label index, default name in brackets;
  Brown (14) looks like the default/unlabelled colour):
  | source | label |
  |---|---|
  | 0:23–4:26 | Brown (opening talk, not labelled) |
  | 4:26–13:24 | Iris (1) |
  | 13:24–13:45, 14:37–15:36 | Brown |
  | 15:36–28:35 | Blue (9) |
  | 28:35–32:05 | Iris (1) |
  | 32:05–33:25 | Caribbean (2) |
  | 34:29–34:56 | Brown |
  | 34:56–41:09 | Iris (1) |
  | 41:09–47:00 | Teal (10) |
  | 47:00–49:48 | Cerulean (4) |
  | 49:48–62:07 | Mango (7) |
  | 62:07–64:49 | Magenta (11) |
  | 64:49–65:47 | Cerulean (4) |
  | 73:27–73:48 | Magenta (11) (goodbye) |
  **User: the colours themselves mean nothing.** Only the boundaries matter; colours just
  alternate so neighbouring topics look different.
- **User: the 3 gaps in `1 YOUTUBE D1` mark where the live went to a break.** The live
  usually has 3 breaks. The gaps are not the same length as what was cut:
  | YouTube gap | length | source cut at that point |
  |---|---|---|
  | 828.64–895.68 | 67.0 s | 824.56–877.20 sponsor + bumper (52.6 s) |
  | 2023.36–2102.00 | 78.6 s | 2004.88–2069.32 bumper (64.4 s) |
  | 2852.88–2958.68 | 105.8 s | none: source is continuous at 2820.20 |
  **User: a gap is only a visual marker** for the user to see where each break is; it is not
  filled. Break 3 = where the **"social part"** starts: the online-only part of the live,
  spotted because the **TV clock (top-left) is gone**.
- **Checked on the footage:** the top-left clock shows wall time (e.g. `12:35:26` at 30 s).
  - It is visible through 2815 s (`13:32:13`) and gone from 2825 s to the end. The user's
    cut at 2820.20 is that edge, so everything after ~47:00 is social-only.
  - Breaks 1 and 2 show as **clock jumps**: at 800 s → 878 s the video advances 78 s but the
    clock advances 5:46 (`12:48:16` → `12:54:02`). At 2000 s → 2075 s it is 75 s vs 7:09
    (`13:12:44` → `13:19:53`). The TV ad break was removed from the feed and a bumper
    put in its place.
  - So **OCR of the clock finds all 3 breaks**: break = jump of the clock against video time;
    the social part = clock gone. No guessing.
- **User: the social part is treated the same as the TV part.** `1 YOUTUBE D1` is the
  **long-form** cut: every main story, in order, minus opening title, bumpers, sponsors and end
  credits, with a gap at each break.
- **So the long-form build rule is:** AE intro + (footage − opening − sponsors − bumpers −
  credits), in source order, with a visual gap at each of the 3 breaks. Everything except
  "which parts are sponsor" can already be decided by a machine.
- **Also found:** the footage audio has an Essential Sound **Dialogue** preset applied
  (clarity, restoration settings). This is another fixed step.
- **Automate?**
  - Finding drops: **automate.** Opening title, bumpers and end credits are fixed graphics,
    so we can match them against reference clips (audio or picture fingerprint). Sponsor
    segments are a judgment call: suggest them, the user confirms.
  - Topic splits: **assist**, using the topic-cut design (DESIGN_TOPIC_CUT.md).
  - Laying out the YouTube sequence: **automate** once the gap rule is known.
  - Thumbnail: **assist** (headline text, face frame), later.

### Step 3: Build the long form in `1 YOUTUBE D1` (the longest step, in progress)
- **AE intro (user):** the 4 linked comps at 0–21.92 are **~4 title cards that tell the
  episode's main stories**, made in `2. AFTER EFFECT\Untitled Project.aep` before the footage
  came in.
- **Method seen in the saves (16:13 → 16:18):**
  1. A **pool**: the whole rough cut (all keepers, plus the 7:40 sponsor) is pasted far down
     the same timeline (started at 45:31, pushed to 54:29 as the front grows).
  2. The user picks a piece from the pool and places it at the front, after the title cards.
     First one: source 4:26–13:24 (the first labelled topic, 537.5 s, whole, not trimmed yet)
     at 0:35.36. That leaves a **13.4 s gap** after the cards (21.92–35.36). _ask_
  3. In the pool, the used piece's video is **lifted to V2**, apparently to mark it "used".
     _confirm_
  4. Skipped so far: the brown opening talk (0:23–4:26).
- **User answers:** lifting a pool piece to V2 = "picked for cutting". Order = **story
  flow**, mostly show order but sometimes mixed. The gap after the title cards is just
  unfinished work. **Trims happen right away**, piece by piece. Opening talk is dropped: "get
  to the topic as quick as I can, not much background story."
- **Trims on story 1 (save 16:23)**, source time; text from our faster-whisper run on
  260–395 s:
  | removed | length | what was said | why (our reading) |
  |---|---|---|---|
  | 266.04–298.80 | 32.8 s | host: "เอาเข้าเรื่องนี้เลย… ลองเล่าสิ", back-and-forth fixing the date (19th, 4 am), "คุณไปงานอะไร" | warm-up and clarifying chatter; start where the guest's story starts ("เจ้าของเต็นท์รถ…") |
  | 312.60–321.40 | 8.8 s | host checks a name: "เสี่ยเล็ก… เต็นท์มังกร… อ๋อ โอเค" | side clarification interrupting the story |
  | 350.80–387.92 | 37.1 s | repeats "I had problems with อ้อ, but we cleared it", host follow-ups, "โอเค ต่อเลยครับ" | repeat of what was just said + host digression |
  | 388.80–389.24 | 0.4 s | stumble inside "หลังจาก-ที่" | micro-tighten a stumble |
  - Also a split at 310.28 with nothing removed (marker for later?). _ask_
  - **Cutaway:** a 1.88 s shot from source 314.68–316.56 is on V2 at 78.56–80.44, over the
    jump cut left by the 37 s removal. Picture covered, audio continuous.
  - Result so far: the first 123 s of story 1 became 44 s (79 s removed, 64%).
- **User rule for the story opening:** host clarifying is cut by default, so the piece goes
  straight into the guest's story. **Exception:** if the guest's opening is too long and slow
  to reach the point, the user keeps (or uses) the **host's summary** of the story as the
  entry instead, then cuts to the guest where it gets going.
  Entry = whichever reaches the story fastest: the guest's first story sentence, or a host
  line that sums it up.
- **User rules for cuts (2026-11-20):**
  - **No jump cuts in this show.** A cut in the main picture only goes where a thought or
    story ends, or where the director already switched angle. (The 310.28 split is one of
    those.)
  - **Cut aggressively only under a cover:** B-roll on top, or a "made" scene such as a static
    shot of someone listening while the speaker's audio runs on.
  - **Target length:** the long form lands around **15–20 min**, a bit over is fine. There is
    no fixed time per story.
- **Save 16:38 shows the cover technique at scale** (story 1, timeline 0:35–5:19):
  - Timeline 95.60–121.44: a **25.8 s cover** on V2 (source 419.68–445.52: the news-clip
    layout with CCTV of the incident, guest in a small window). Under it the audio is cut
    into **10 pieces**, gaps 0.1–1.2 s: stumbles, pauses, repeats.
  - Timeline 123.68–167.72: a **44 s cover** on V2 (source 583.92–627.96, full-frame CCTV
    with name tags). Under it **12 pieces**, including a jump from 443.24 to 548.84 (105.6 s
    dropped) and 576.04 → 603.08 (27 s dropped).
  - Timeline 78.56: the 1.88 s cutaway is the **host listening** (static person), covering
    the 37 s cut.
  - Outside covers the cuts are few and long (e.g. 167.72–226.28 is near-continuous).
  - Story 1 now: source 266.04–803.56 (537.5 s) → timeline 35.36–318.96 (283.6 s), **47%
    removed**.
- **User answers (cover + content):**
  - **Cover source:** a clip **from the same story** in this footage, often the same moment
    they are talking about. Only footage from the episode itself, nothing from outside. If the
    story has no B-roll, use a **static scene of a person** (listening, not talking) from the
    episode.
  - **The 1:46 drop (source 443–549) was off-topic.** Rule: **each point is told once.**
    No repeated telling of the same part of the story; keep it concise.
- **Save 17:08 (30 min after 16:38):**
  - **Story 1 done:** source 266.04–803.56 (9:00) → timeline 35.36–244.44 (**3:29, 61%
    cut**). The tail 773.60–803.56 was dropped, along with the brown link pieces around break 1
    (803.56–824.56, 877.20–935.96). No break gap was left between story 1 and story 2.
  - **Story 2 half done:** source 935.96–1327.88 (6:32) → 244.44–409.52 (**2:45, 58%
    cut**). The rest (1340.96–2004.88) is pasted in untrimmed after it, waiting. Its pool
    copies were lifted to V2.
  - New covers on V2: 11 in total, from 4.7 s to 39.6 s. Most are the same-moment clip. The
    one at 218.48 is **source 755.56, the shot saved in `Backup`**, which confirms Backup is
    the cover pool.
  - Pace: 16:18 → 17:08 (50 min) covered source 4:26 → 22:08, about **2.8 min of work per
    minute of source**. The whole episode has ~64 min of keepable source, so roughly
    **3 hours** for the long-form cut.
- **Audit of every cut so far (save 17:08, story 1 + first half of story 2, 78 cuts)** against
  the full transcript (faster-whisper, word timings,
  `scratchpad/hks/full.words.json`, report in `cuts_report.txt`):
  | size | count | under a cover | typical content |
  |---|---|---|---|
  | < 0.6 s | 30 | 30 | broken syllables, stumbles, breaths |
  | 0.6–3 s | 21 | 21 | pauses, "ครับ", false starts |
  | 3–15 s | 19 | 16 | host clarifying/prompting ("แล้วยังไงครับ", "เพราะอะไร", "เดี๋ยวก่อนนะ"), name checks, a short retelling |
  | ≥ 15 s | 8 | 8 | see below |
  - **The 3 uncovered cuts are all at a camera angle change** (checked frames: close-up →
    two-shot at 312.60/321.40; clip layout → wide at 692.04/696.60; wide → close-up at
    697.68/702.84). **0 jump cuts:** the rule holds on all 78.
  - The ≥ 15 s cuts, by reason:
    - **Retelling:** 350.80 (37 s, "had problems with อ้อ but cleared it" again), 576.04
      (27 s, narrating the CCTV wai again), 1065.40 (60 s, "เดี๋ยวก่อนนะ รอบแรกนี้ตบก่อน",
      the first slap told again).
    - **Off-topic:** 443.24 (106 s, guest's feelings: "บางทีก็ท้อ… ทำไมเราชี้แจงไม่ได้").
    - **Host commentary:** 1020.36 (28 s, host on the other person's character, "น้ำเป็นคน
      เรียบร้อย น่ารัก").
    - **Host challenge:** 1286.28 (32 s, "why didn't you fight back / run away?").
    - **Host Q&A filler:** 1171.56 (17 s, "แล้วยังไงต่อ… ทุกคนพยายามดึงใช่ไหม").
    - **Story boundary:** 773.60–937.12 (164 s): end of story 1, break 1, the host reading
      a **viewer comment from YouTube** ("ได้ประโยชน์อะไรจากเรื่องคนสองคนทะเลาะกัน"), the
      lead-in to story 2.
  - Content reading: keep the **guest's first-person account of events, in order, once**.
    Cut the host's prompts, clarifications, opinions and challenges unless they carry the
    story (the opening-summary exception). Cut feelings and asides that do not move events,
    and viewer-comment reading.
- **User rules on the host and viewers:**
  - **Host reaction:** sometimes **added** for drama (a short visible/audible reaction).
  - **Host opinion inside the story:** cut.
  - **Viewer comments read on air:** **always cut.**
  - **Host connectors** ("แล้วยังไงต่อ", "then what?"): cut by default. **Kept or added only
    when two guest pieces don't join smoothly**, as a bridge.
- **Save 18:12: long form finished.**
  - Timeline: AE title cards (0–21.92), stories 35.36–1097.68, goodbye, end sting at
    1097.68–1100.52 (SFX_โหนกระแส + glitch + film damage + adjustment layers, the pattern
    from `Plattern_*`), `CG_END LOGO โหนกระแส.mp4` 1100.52–1105.52. **Total 18:25**, inside
    the 15–20 min target. Work time ~16:13 → 18:12, about **2 hours**.
  - Kept per labelled section (source → kept):
    | section | source | kept | |
    |---|---|---|---|
    | opening talk | 4:03 | 0 | dropped |
    | story 1 (Iris) | 8:58 | 3:29 | 39% |
    | sponsor 1 + links | 2:12 | 0 | dropped |
    | Blue | 12:59 | 4:17 | 33% |
    | Iris 2 | 3:30 | 1:49 | 52% |
    | Caribbean | 1:20 | 0:58 | 73% |
    | **Iris 3** (34:56–41:09) | 6:13 | **0** | guest's personal life: foundation, "ปากไม่ดี", police report. Dropped whole |
    | Teal | 5:51 | 2:59 | 51% |
    | **Cerulean 1** (47:00–49:48) | 2:48 | **0** | **legal analysis** (พี่แก้ว's legal view, news-page update). Dropped whole |
    | Mango (third party อ้อ on the phone/studio) | 12:18 | 2:04 | 17% |
    | Magenta | 2:42 | 1:12 | 45% |
    | Cerulean 2 | 0:58 | 0:43 | 73% |
    | sponsor 2 | 7:40 | 0 | dropped |
    | goodbye | 0:21 | 0:13 | |
    | **total** | | **17:45 of footage** | |
  - **155 cuts.** 133 are under a cover (V2, V3 or V5). Of the 22 uncovered cuts, 20 land on a
    **camera angle change** (frame difference 27–87). **2 are tiny same-shot cuts** (0.56 s
    and 1.6 s, at timeline 696.32/697.32): near-invisible micro jump cuts.
  - **Bleep:** `CENSORED SOUND EFFECT.mp4` on A2 at 491.72 (source 1693.00, a swear while
    the guest quotes the other person: "พี่เขาด่าผม…").
  - Covers also come from later in the same story (e.g. timeline 849–930 uses source
    3178–3282, the third party's segment).
- **User answers (after the long form):**
  - Whole sections such as backstory and legal analysis are dropped **to shorten as much as
    possible**. It is a length call, not a hard "never". Priority order: the incident itself
    first, side topics are the first to go.
  - **Swear words: mostly bleeped** (CENSORED SOUND EFFECT).
  - **End: same every episode** (goodbye → sting → `CG_END LOGO`). Can be a fixed template.
- **Pattern so far:** keep the guest's narrative. Cut host warm-up, clarifying questions,
  repeats and stumbles. Cover a visible jump cut with a short shot of the same scene.
- **Automate?** **assist.** The transcript can flag the cuttable parts: host turns that are
  questions or clarifications, repeated sentences, stumbles. CutDeck's filler/word-level cut
  already does the micro trims; cutaways can come from the `Backup` pool. Speaker
  diarization (host vs guest) is the missing piece.

### Step 4: Cold-open hook (save 18:32, ~20 min)
The 4 AE title cards (V7) now sit over a **25.9 s hook** built from soundbites, then a
transition into story 1. The 13 s gap after the cards is gone; the long form is now
**18:16** in total (end logo ends 1095.80).
- **Hook audio** (source → what is said), all from the **climax** of the main incident:
  | timeline | source | line |
  |---|---|---|
  | 0.00–2.92 | 1125.96 | "รอบ 2 ครับ" (the second hit) |
  | 2.92–4.72 | 1188.16 | "จนกระทั่งดอกสุดท้ายคือต่อย" |
  | 4.72–7.72 | 1223.00 | "นี่ตบอีกที อันนี้ต่อยครับ" |
  | 7.72–9.56 | 1228.20 | "ต่อยลงไปแล้วนะ ตรงนี้ผมหน้ามืดเลย" |
  | 9.56–22.80 | 1680.60 | "อันนี้แกบอก มึงมา… ผมก็วิ่ง", with a **bleep** at 21.96 |
  | 22.80–25.92 | 1390.08 | **button line:** "ถ้าผมไม่วิ่งเนี่ย ผมตายคาที่นะครับ" (after the cards end at 21.92, so it plays clean) |
  Source order is not kept: the lines are re-ordered to build up to the button line.
- **Hook picture:** CCTV / clip footage of the same moments on V2 (1124.96, 1220.76,
  1680.60…) under the title cards, plus an adjustment layer (V3, 0–25.92) and
  `FILM_DAMAGE2.mov` (V4, repeated every 4.72 s).
- **Hook sound design:** `Swoosh Transition 03` at each card change (0, 3.60, 8.88, 13.72,
  21.52). BGM `[BGM]Where Everything Began.wav` starts at 0 and runs to 59.28, so it carries
  into story 1. `Transition Complex 14` + glitch graphic (V9/V10, 25.80–26.32) mark the
  jump into the story.
- **User answers:**
  - **Title-card text:** the user writes it after watching the news. **Wants us to write it
    in future** (~4 cards that tell the episode's main story).
  - **Hook line choice:** the most violent or emotional moment if there is one. Otherwise
    lines from the climax or the lead-in to it, or a "what!?" moment: something shocking or
    bad.
  - **Music:** always the same (`[BGM]Where Everything Began.wav`).
- **Automate?**
  - **automate (draft for approval):** write the ~4 title-card texts from the transcript and
    the news, in the voice of the past cards (examples in `Plattern_*`: "เจอศพชายลอยใน
    แม่น้ำปิง สภาพหัวมีรู!", "ญาติพบพิรุธ สงสัยสาเหตุไม่ใช่การกระโดดน้ำตาย").
  - **assist:** pick hook candidates. Rule so far: short, punchy first-person lines from the
    climax (the violent moment, "I almost died"), ending on the strongest line. The
    transcript plus the cut already made can rank them.
  - **automate:** the template part (swooshes on card changes, film damage, adjustment layer,
    BGM bed, transition into the story) is the same shape each time.

### Step 5: Picture finishing rules (user, 2026-11-20) + what the timeline shows
- **User rules:**
  - Anything showing the **TV clock (top-left) is always blurred.**
  - **Inserts / B-roll always fill the width down to the banner.** If the clip is already
    full-frame that's fine. If it sits in the **small window** (news-clip layout), **zoom in**
    on it.
- **Read from the 18:32 save (`1 YOUTUBE D1`):**
  - **Base:** every V1 footage clip has Motion scale **150%**, centred: 1280x720 filling the
    sequence frame.
  - **Blur:** Gaussian Blur (Legacy) adjustment layers on **V8** in long runs (22.80–838.28,
    1034.24–1049.16). The blur mask/area is not parsed by our reader. Sampled every 0.5 s:
    **blur is on exactly where the visible picture comes from the TV part (source < 2820,
    clock present)**, never where the clock is absent. The places with a clock source and no
    blur are all where the clock is off-screen: under the title cards (0–22.5) and inside
    zoomed inserts (86–112, 344–353, 361–414, 900–921). Zooming in pushes the clock out of
    frame.
  - **Extra blur on V9** only over the inserts zoomed to 311% (253–291, 644–656). That clip
    seems to carry its own burned-in mark. _confirm_
  - **Insert zoom:** full-frame inserts stay at 150%. Small-window inserts are zoomed to
    **271–405%** with the position moved toward the window (e.g. 288% at (0.869, 0.754),
    311% at (0.78, 0.682), 272% at (0.846, 0.639)). Each source clip gets one setting,
    reused every time it appears.
  - **Film damage on covers:** `FILM_DAMAGE2.mov` on V7, chained in 4.72 s pieces over most
    covers (about 82% of cover time). _ask:_ always, or only some covers?
- **User answers:**
  - **Film damage goes on all B-roll.** (The ~18% without it in this save are gaps still to
    fill, or the static-person shots. _check on a future episode_)
  - **V9 blur hides the clip's own logo and video credit** (another source's watermark that
    the zoom crops awkwardly or leaves in view).
- **Automate?** **automate.**
  - Blur track = the time ranges where the visible picture is TV-part footage and the
    clock is on screen. Clock presence is already detectable (Step 2), so this is a
    computed overlay.
  - Insert zoom: the small window's rectangle can be detected once per clip (layout
    classifier + box detection). Scale/position = fill width to the banner.
  - Film-damage chain over covers: mechanical once the cover list exists.

### Long form: sound bed and graphics (from the 18:32 save)
- **BGM under the whole show:** `[BGM]Where Everything Began.wav` (~60 s) is looped
  end-to-end, alternating A5/A4 with **~3 s overlaps** (0–59, 56–116, 113–172, …,
  22 pieces to the end): a crossfaded loop bed. Levels and fades are not read by our reader.
- **SFX in the body:** only bleeps (2) and the end sting `SFX_โหนกระแส 1.wav`. No SFX at story
  changes.
- **No lower thirds or headline graphics in the long form** (the `Plattern_*` lower-third box
  and headline Graphic are not used here).
- **Break gaps:** gone in the finished cut. They were working markers only.

- **Audio levels (user):**
  - **Dialogue (V1/A1 footage):** a **compressor** already handles level and loudness (plus
    the Essential Sound Dialogue preset). No manual riding.
  - **Music:** **-33 dB** under the stories, **-24 dB** under the highlight/hook,
    **-12 dB** at the end.

- **Export (user): Media Encoder preset `BAS4`**
  (`C:\Users\thana\Documents\Adobe\Adobe Media Encoder\27.0\Presets\BAS4.epr`, saved
  2026-11-18; older BAS, BAS 1–3 kept). Read from the file: H.264, 1920x1080, square pixels,
  High profile level 5.2, VBR (target 15 / max 23.8 Mbps), keyframe every 72 frames, render
  at max depth; AAC 384 kbps 48 kHz stereo.
- **AE title cards (user): built from an AE template**; only the content changes.

- **Export folder (user):** `<day folder>\5. EXPORTS`, day folder = `G:\Me\Works\YYYYMMDD -
  โหนกระแส`. The naming discussion is deferred. Seen in `20261117 - โหนกระแส\5. EXPORTS`:
  `โหนกระแส 171169 YT D1.mp4` (2.3 GB), `… FB D1.mp4`, `… REEL 3M D1.mp4`,
  `… REEL 1M D1.mp4` (date = DDMMYY Buddhist Era), so **4 deliverables per episode**:
  YT, FB, Reel 3 min, Reel 1 min.
- **Past episodes on disk** (`G:\Me\Works\2026xxxx - โหนกระแส`: 1012, 1020, 1109, 1110, 1112,
  1117, 1118) each have a project and exports. This is a ready-made **gold set** for testing
  any automation against the user's real cuts.

### Still unknown for the long form
- Export file naming (deferred by the user); the upload (YouTube title, description, tags,
  thumbnail = `PSD-REEL\20261120 - YT Thumbnail.jpg`?).
- Where the AE title-card template lives, and which layers change per episode (text only, or
  also pictures?).

### Step 6: Facebook version `2 FACEBOOK D1` (save 19:27)
- **Length 3:00** (179.96 s), single story: the main incident only.
- **Frame:** square (sequence uses `LOGO_FOR SQUARE FRAME2.png` on V13 for the whole
  duration, a logo/frame overlay). Footage is mostly at **84.375%** (1280 → 1080, fit to
  width). Some pieces are at **150%** (fill height, cropped). The last piece is at 183%.
  _confirm frame size 1080x1080_
- **Structure:**
  1. **Same hook as YT** (0–25.92: same soundbites, title cards, swooshes, bleep).
  2. **Core incident, ~2.5 min, in order:** arrival and the wai → "พี่น้ำหันมาก็ใส่ผมเลย"
     (first slap) → "รอบ 2 / ครั้งที่ 3" → what was said → "ดอกสุดท้ายคือต่อย… ร่วงเลย" →
     "มึงมา… ผมก็วิ่ง" → escape ("ไม่คิดชีวิตเลย") → the guest's side ("ผมไม่ชอบคนจริต…
     เช็คเกียว") → the **third party (อ้อ)**'s account (bottle, chair, rocks thrown) → the
     guest's rebuttal as the ending: "มันคนละม้วน… ผมคนเดียวที่ลงพยานหลักฐาน".
  3. **End:** glitch + film damage + `SFX_โหนกระแส 1.wav` at 177.8. **No `CG_END LOGO`.**
     _confirm_
- **User rules (FB):**
  - Frame **1080x1080**.
  - Length **always 2:59:24** (2 min 59 s 24 frames at 25 fps = 179.96 s), i.e. **under
    3:00, never 3:00 or more**. This episode is exactly 179.96 s.
  - **Main story only.**
  - **Scale:** B-roll **fills the whole frame**. A B-roll that is a standalone shot **with its
    own banner** stays **fit to frame** (84.375%, whole picture visible).
  - **No end logo, always.**
- **User answers (FB):**
  - **Hook: always the same as YT.**
  - **Beat choice: the climax of the story.** Usually there's no room for both sides (this
    episode was an exception). **End on something strong and aggressive.**
  - **Source: copy from `1 YOUTUBE D1`**, then trim or re-order to fit 2:59:24. Confirms the
    36/46 shared pieces.
- **Built from the YT cut:** 46 picture pieces; **36 are identical pieces from the YT long form**,
  10 are new or re-trimmed. So the FB cut is a **selection from the finished long form**, not
  a fresh cut from the footage.
- **Same finishing:** film damage on covers, blur, BGM looped (A5–A7), bleeps.
- **Time:** ~18:32 → 19:27, under an hour (including this session's Q&A).
- **Automate?** **assist → automate.** Pick the incident's beats from the long-form cut
  (setup → violence → escape → each side's claim → strongest closing line), target 3:00,
  reuse the same hook, reframe to square with the logo frame. Our transcript + the YT cut
  already contain everything needed.

### Step 7: 1-minute version `3 SQUARE SELECT D1` → `4 REEL SIZE D1` (save 19:41)
- **User:** same as FB D1, trimmed to 1 min; it goes into `4 REEL SIZE D1` with the frame.
- **`3 SQUARE SELECT D1`:** 1080x1080, **59.96 s** (0:59:24, the same "just under" rule as
  FB). 16 picture pieces, all from the FB cut:
  1. Same hook (0–25.92).
  2. Climax only: "พี่น้ำหันมาก็ใส่ผมเลย" → "รอบ 2… ครั้งที่ 3" → "ต่อยเข้าหน้าผม จนผม
     ก็ร่วงเลย".
  3. Ends on the guest's side: "ผมเป็นคนไม่ชอบคนจริตแบบนี้… ลองเช็ค… การพูดแซว".
  - The third party's account and the escape are dropped. End sting as FB (no end logo).
- **`4 REEL SIZE D1`:** 1080x1920. V1 = `3 SQUARE SELECT D1` **nested** (whole, 0–59.96);
  V4 = **`PSD-REEL\1.png`**, a full-frame reel overlay exported from the Reel PSD at 15:47:
  - **top band:** the episode headline, `"น้ำ รพีภัทร" ใส่ "ซอง" เช็กเกลียว!!!` (white +
    red, heavy italic, quote marks around names);
  - **transparent middle** where the 1080x1080 square sits;
  - **bottom band:** host photo + โหนกระแส logo (fixed).
  So the only per-episode part of the reel frame is the **headline text**.
- **Automate?**
  - 1-min cut: **assist → automate.** Take the FB cut, keep hook + climax + one strong closing
    line, hit 59.96 s.
  - Reel: **automate.** Nest the square, lay the frame. Headline text: we draft, the user
    approves (same voice as the title cards). The PSD text swap could be scripted.

### Step 8: 3-minute reel `5 REEL 1-3 SIZE D1` (save 19:43)
- **User:** duplicate `2 FACEBOOK D1`, remove the logo, put it in the reel frame.
- **Seen:** `2 FACEBOOK D1 Copy 01` is identical to FB D1 except that **V13
  `LOGO_FOR SQUARE FRAME2.png` is removed** (124 vs 125 clips). `5 REEL 1-3 SIZE D1` (1080x1920)
  = the copy nested on V1 (0–179.96) + the same `1.png` reel frame on V11.
- The 1-min square has no square logo either: **the square logo is FB-only**, because the reel
  frame carries the logo.
- **Automate? automate.** Duplicate, drop the logo track, nest, add the frame. No judgment.

## Automation candidates (summary)

Episode 20261120 recorded end to end (≈15:20 → 19:45 editing, after the ~2 h live).

| # | Step | User time (this episode) | Can be | What it needs |
|---|---|---|---|---|
| 0 | Watch live, take notes | ~2 h | assist | live transcript + story list, hook lines, title-card text drafted during the live |
| 1 | Day folder + project + master import | minutes | **automate** | template copy, name `YYYYMMDD - โหนกระแส`, import master |
| 2 | Rough cut: drop opening, bumpers, sponsors, credits; break markers; topic splits | ~20 min | **automate** (sponsor = approve) | bumper/credit fingerprint, TV-clock OCR (breaks, social part), transcript for sponsors |
| 3 | Long-form story cut (15–20 min) | **~2 h** | **assist** (draft to approve) | transcript + host/guest diarization, layout classifier (studio vs clip), the cut rules below, cover from same story / Backup, length target |
| 4 | Hook (title cards + soundbites) | ~20 min | assist + template | rank climax lines, fixed sound design; title-card text drafted by us |
| 5 | Finishing: clock blur, insert zoom, film damage, logo blur, bleeps, music bed, levels, ending | inside 3 | **automate** (logo blur, bleeps = approve) | clock detection, window-box detection, swear list, BGM loop -24/-33/-12 dB |
| 6 | FB 1080², 2:59:24, climax only | ~50 min | assist → automate | beat selection from the YT cut, fill/fit rule, square logo |
| 7 | 1-min square + reel 1080x1920 | ~10 min | assist → automate | climax + strong closing line at 0:59:24; reel frame headline |
| 8 | 3-min reel | ~2 min | **automate** | duplicate FB, drop logo, nest, frame |
| – | Export BAS4 → `5. EXPORTS` | – | **automate** | naming (deferred) |
| – | Thumbnails, upload | – | manual (user) | out of scope for now |

**Cut rules for the long form (step 3):**
1. Get into each story fast: the guest's first story sentence, or the host's summary if the
   guest is slow.
2. Each point told once. Drop retellings, off-topic asides, backstory, legal analysis and
   feelings that don't move events (shorten as much as possible).
3. Cut host prompts, clarifications and opinions. Keep a host connector only to bridge pieces
   that don't join. Host reactions may be added for drama.
4. Viewer comments read on air: always cut. Sponsors: always cut.
5. No jump cuts: in studio picture cut only at a thought end or a camera change. Cut hard
   (stumbles, pauses, repeats) only under a cover.
6. Cover = B-roll from the same story (ideally the same moment, this episode only), else a
   static listener shot (`Backup`). Film damage on all B-roll.
7. Swear words bleeped. Same ending every episode.

**Gold set for testing:** past episode folders `G:\Me\Works\2026xxxx - โหนกระแส` (7 since
2026-10-12) with projects + exports.

**Export automation, first live run (2026-11-20 19:52):** new CutDeck driver command
`export_sequence`, run with `python -m cutdeck.premiere_cli export_sequence args.json` or the MCP
tool `premiere_export_sequence`. It exported the active `5 REEL 1-3 SIZE D1` with BAS4 to
`5. EXPORTS\TEST cutdeck REEL 3M.mp4` in **45 s**. The file matches the 17 Nov REEL 3M export
(1080x1920, 179.96 s, H.264 High ~15.7 Mbps; AAC is 381 kbps vs 317 because BAS4 is set to 384).
BAS4 has Match Source on, so one preset serves all four sizes.
**Queue to Media Encoder** (`"queue": "ame"`) also works: it adds the job to AME's queue (and
launches AME). The user presses Start; 58 s; output pixel-identical to the Premiere render.
The AME log shows the user's normal practice: on 18 Nov REEL 3M and FB went through AME with
BAS4 (NVENC, ~30 s each), named `โหนกระแส 181169 REEL 3M D3.mp4` / `… FB D3.mp4`. **User: D1/D2/D3 = revision
number** (re-export → next number). So the name is `โหนกระแส <DDMMYY BE> <YT|FB|REEL 3M|REEL 1M>
D<n>.mp4`. **User: start the AME queue automatically.** Done and live-proven 20:03: queue →
wait for AME's "queued" event → `startBatchEncode` → encoded with no clicks.
**YT In/Out works (20:08):** the user's In/Out on `1 YOUTUBE D1` (0–1095.8 s) is used, and the
pool after the end logo is left out. Exactly 1095.80 s, 1920x1080, ~3.5 min in AME.
**Real exports, episode 20261120 (20:14–20:21):** the user opened each sequence and the agent
checked its name + In/Out, then queued it to AME (auto-start):
`โหนกระแส 201169 YT D1.mp4` (1920x1080, 1095.80 s, 2.2 GB), `… FB D1.mp4` (1080x1080, 179.96 s),
`… REEL 3M D1.mp4` (1080x1920, 179.96 s), `… REEL 1M D1.mp4` (1080x1920, 59.96 s). All done by
20:20:44.
**One command (20:26):** `python -m cutdeck.honekasae_export "<day folder>" [--only YT FB "REEL 3M"
"REEL 1M"] [--dry-run]`. It finds each sequence by name (the one same-named copy with content;
refuses 0 or 2+), uses its In/Out, names the file with the next free D **per version**, and queues
it to AME with auto-start. Live: `--only "REEL 1M"` → `โหนกระแส 201169 REEL 1M D2.mp4`
(1080x1920, 59.96 s), picked out of the two sequences named `4 REEL SIZE D1`.
**Queue all, then start once (20:28, user request):** every version is added to AME with
`start: false`, and the last one starts the queue. Live: `--only "REEL 3M" "REEL 1M"` with
`4 REEL SIZE D1` open → REEL 3M (from the *non-active* `5 REEL 1-3 SIZE D1`) waited, REEL 1M
started the queue, and both encoded in one run (REEL 3M D2 at 20:28:36, REEL 1M D3 at 20:28:52). AME warns "Missing Font: Montserrat Bold" (no visible effect on this reel).
Still to do: export by In/Out
(the YT sequence keeps the pool after the end logo), exporting all four in one go, file naming.

**Open:** export file naming; AE title-card template (where, which layers change); what the
live notes contain.
