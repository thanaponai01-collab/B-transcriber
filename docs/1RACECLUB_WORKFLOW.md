# 1RaceClub workflow log

Started 2026-11-21. The agent watches the user's Premiere saves (Ctrl+S and Auto-Save), diffs
the timeline with `cutdeck/prproj_reader.py`, logs each step here, and asks the rule behind
each judgment call. Same method as [HONEKASAE_WORKFLOW.md](HONEKASAE_WORKFLOW.md).

**Goal (user, 2026-11-21):** teach the agent *how to edit*, meaning the reasons behind each
choice, so it can make its own decisions when the footage, story or format changes. Values
(109%, −12 dB, 0.2) are only today's example of a principle; they are not presets to replay.
The **Editing principles** section below is the main output; the episode log is the evidence.

## Editing principles (why)

Status: **confirmed** = the user said so; **guess** = inferred from the timeline, needs the user.

### The channel
- **What the viewer comes for:** the user's live reaction to an F1 session. The face and voice
  are the product; F1 footage is context. *(guess)*

### Long reaction video
1. **Keep the moments worth knowing and the hot spots: action, something happening, the
   climax.** Cut everything that isn't one of those (waiting, repeats, setup, off-topic).
   *(confirmed: "pick one that's worth knowing, and the hot spots like action, something
   happened, climax")* Evidence: 80 min → 15 min; cuts heaviest in slow stretches (~40–55%),
   lighter during the action (~27%); whole blocks dropped (pre-show, a 10.7 min gap, post-show).
   Still to learn from the transcript: what "worth knowing" looks like in the user's words.
2. **Chronological, no hook at the start: the session itself is the story arc; the title
   and thumbnail do the hooking.** *(confirmed: "no HL, just plain cutting"; reason is a guess)*
3. **F1 footage is there to give a sense of the moment, as pictures, not as video.** Reason:
   **copyright** (confirmed). Posterize Time 0.2 turns the broadcast into a still image that
   changes every 5 s. That's a **shortcut**: the honest goal is "a still picture of each
   highlight", and capturing a still by hand for every HL took too long. Small + blended for
   the same reason. *(confirmed)*
   - **Also a rate limit** *(confirmed)*: when highlights come close together, posterize
     guarantees the picture changes **at most once every ~5 s**, so it never turns into a
     rapid stream of pictures (which would read as video again).
   - **For the agent:** the goal is *one clear still per highlight, no running broadcast
     video, and never pictures changing faster than ~every 5 s*. Posterize gets both for
     free; picking the frames myself is allowed ("if you want to pick it yourself that's up
     to you") but must keep that minimum gap, e.g. merge highlights that are close together
     under one picture.
4. **Cut method: delete pieces and leave gaps, close them in batches.** Keeps the timeline
   readable against the source while reviewing. *(guess)*

### Short
5. **The first 1–2 s must stop the scroll before anything is explained.** Two ways seen:
   (a) move the peak to the front, then play the build-up (Ferrari: the "oh no" reaction);
   (b) open on the strongest *source* moment itself when the story starts with it (Russell:
   the real team radio plays first, nothing moved). Not a rule that the peak always goes
   first. **The opener can be anything; the principle is watch time: choose whatever will
   make people keep watching. (a) and (b) are examples, not a menu.** *(confirmed)*
6. **Prove the claim on screen, readable on a phone:** zoom into the timing tower so the
   viewer sees LEC/HAM in the drop zone in under 2 s. *(guess)*
7. **Title text on the hook = the story in a few words, for viewers with sound off.**
   *(guess)*
8. **Shorts frame layout** *(confirmed)*:
   - **With an image/video under me:** the top part (face cam) ends at **~740 px from the
     top**, and **my chin must sit above that line**. The image below fills the rest
     (740–1920). Today's file matches: F1 at 109%, bottom-anchored = 1177 px tall, so its top
     edge is at 1920 − 1177 = **743 px**.
   - **Only me on screen:** fill the visible Shorts frame with the face cam (the full-screen
     face beat at ~0:12.5 today).
   - Why (guess): face is the reaction, F1 is the cause; the face stays big and readable, and
     the chin above the seam keeps the face from being cut by the image.
   - The face-cam position is re-set per Short to put *this* chin above the line (y 0.257 in
     Ferrari, 0.273 in Russell): the rule is the chin line, not a number. *(seen in both)*
   - The "picture changes at most every ~5 s" limit (principle 3) is a **long-video** rule.
     In a Short the still changes with each spoken line, every 1–2 s at the fast part.
     *(seen in both)*
9. **Shorts copyright limits:** F1 video **at most 3 s**; normally a **frame hold / captured
   still** stretched across the whole part where the user commentates on it. **Cut out every
   F1 logo** (F1 / F1 TV bugs in the corners: the 109% framing crops ~500 px off each side).
   *(confirmed)*
10. **What to show below is a story choice, not a fixed crop:** the timing tower, sector
   times, the onboard, whatever proves what the user is talking about at that moment. Crop
   and zoom it to follow the story. The agent decides this itself. *(confirmed: "as you want,
   following the story")*
11. **SFX mark emotional beats and never compete with the voice:** a boom on the hook and the
    payoff, a ticking clock for suspense before a reveal, a meme sound on a reaction. They sit
    well under the voice. *(guess)*
12. **Punch-in = point the viewer at one thing** (the full Q2 tower at that beat). *(guess)*
13. **Pick the Short while cutting the long video:** a self-contained ~20–25 s moment with
    setup, peak and payoff that needs no context. *(guess)*

14. **Controversy is a top Short pick.** A moment people will argue about (team orders, a
   radio row, a driver told "no") is worth a Short on its own, e.g. Russell on the Mercedes
   radio wanting to go after Antonelli and the team saying no. *(confirmed: user, 2026-11-21:
   "that's a controversial clip, put that in principle")*

---

Each log step: **Do** / **Input → output** / **Decisions** (the rule) / **Time** / **Automate?**

## Episode 20261121: After Qualifying

Project: `E:\Me\2.Tasks\20261121 - 2\4. PROJECTS\1. PREMIERE PRO\20260130 RENAME template_1.prproj`
(the template's name has not been renamed).

### Starting state (read 13:22 save)
- Footage `1. FOOTAGE\`: `2026-11-21 10-40-51.mp4`, `10-40-52.mp4`, `10-40-53-cam.mp4`,
  `10-55-45.mp4` (screen/OBS-style timestamps, one `-cam` file).
- Sequences: `2026-11-21 10-40-52` (source), `…_Synced` (4 V / 6 A tracks; V1 main clip
  0–80:35, source in 15:14.6), `…_Synced – CutDeck a0373642` (a CutDeck rough cut).
- So far: multicam/sync done and a CutDeck rough cut already made.

### Steps

#### Step 1 (13:26): rename the CutDeck rough cut to `YT editing`
- **Do:** renamed `…_Synced – CutDeck a0373642` (13,629 clips) to `YT editing`.
- **Input → output:** CutDeck rough cut → the working sequence for the long YouTube edit.
- **Decisions:** the CutDeck cut is the starting point, not the raw Synced sequence.
- **Automate?** automate: CutDeck could name its output `YT editing` directly.

#### Format (user, 13:28)
- **Live reaction video:** the user streams/records their reaction to the session live. The edit
  = pick the good highlights (HL) of the reaction and join them into one long YouTube video.
- Source: the ~80 min Synced recording; working sequence `YT editing` (CutDeck cut).
- _ask:_ what makes a moment an HL; target length; what gets dropped (dead air, waiting,
  ads/replays, chat reading?).

#### Step 2 (13:28–): picking highlights in `YT editing`
- **13:28 save:** sequence 37:57 → 37:21. Cut 38.9 s in 25 small pieces, all inside source
  15:16–16:43 (the first ~1.5 min of the recording). Pieces 0.3–2.8 s: trimming the opening
  tightly, gap by gap, not a big block drop.
- _ask:_ what is being removed in the opening (pre-session talk, setup, silences CutDeck kept?).
- **Track layout in `YT editing`:** 4 V / 6 A, each track 1,336 cut pieces. Live: V1, V4, A1.
  Disabled on every piece: V2, V3, A2–A6 (spare angles/audio from the sync).
- **13:30 save:** 130 pieces removed per track (1,336 → 1,206), 190 s of source in 123 ranges
  across src 16:44–24:44. Sequence end unchanged (37:21), so removed **without ripple**
  (gaps left; closing them later?). Pace: ~8 min of source reviewed in ~1 min of work.
- _ask:_ delete-then-close-gaps on purpose? What decides a piece goes (silence, off-topic,
  repeated reaction, waiting for the session)?
- **13:31 autosave:** 2 more pieces (3 s) at src 25:06–25:10, still no ripple.
- **13:33 save:** 149 pieces (4:44) cut in src 25:10–33:50, ~55% of that stretch (16:44–24:44 was ~40%).
- **Source of `YT editing`:** CutDeck job a0373642 = silence cut only (`preset: aggressive`,
  `asr: false`) of the Synced sequence. So every removal the user makes now is a
  content judgment (silences are already gone), which is exactly the rule to learn.
- **13:36 save:** 26 more pieces (33 s) in src 35:06–40:05, and **gaps closed**: length
  37:21 → 28:52 (−8:29 = all non-ripple removals since 13:30). Method confirmed:
  delete pieces leaving gaps, then close all gaps in one go.
- **13:43 autosave:** 212 pieces (5:08) cut in src 40:06–58:56 (~27% of that 19 min, lighter than earlier stretches); length 28:52 → 28:31 (most still as gaps).
- **13:44 save:** 5 pieces (10 s) at src 59:28–59:45.
- **13:45 save:** 7 pieces (9 s) at src 59:47–60:01.
- **13:50 autosave:** 113 pieces (3:33) cut in src 64:37–78:12. Kept footage now 20:05 with
  12:41 of open gaps. **New move:** a 25 s stretch, src 63:29.7–63:54.4 (9 pieces), was
  **copied** (it still plays in place at tl ~13:00) and parked at the end of the timeline
  (tl 32:25, after a 3:56 gap). Likely the hook for the cold open, to move to the start.
  _ask:_ what is that moment, and is "copy the best moment to the front" a fixed rule?
- Source 15:14–16:28 (before the first kept piece) and 39:35–50:14 (10.7 min, tl gap
  2:40–5:56) are gone entirely. _ask:_ what is in 39:35–50:14 (a break between sessions?).
- **13:56 save: first pass done.** 175 pieces (4:32) cut in src 78:51–95:32; everything after
  src 86:30 dropped (the last 9 min, likely post-session chat/outro). Gaps closed: main body
  tl 0:00–15:08 = 461 pieces from src 16:28–86:30, in source order. The copied 25 s hook
  (src 63:30–63:54) still parked at tl 22:34 after a 7:26 gap.
- **First-pass numbers:** 80:35 synced → 37:57 CutDeck silence cut → **15:08** after the
  content pass (~19% of the live kept). Pass took ~28 min (13:28–13:56) for 80 min of source.

#### User's own summary (13:57)
- "Done. No HL, just plain cutting here, and just pick a good scene for live action."
- **Rule:** the long video has **no highlight/hook cold open**. It is a plain chronological
  cut of the live reaction: drop what is not good, keep the rest in order.
- The parked 25 s (src 63:30–63:54) is a **good scene picked for a Short** (user: "just put
  what I want to do the short video there"). Parked at the end of `YT editing`, not part of
  the long video; it does not get the F1-layer effects. Rule: while cutting, copy Short
  candidates to the end of the timeline.

### Episode summary: rules learned so far
| Step | What | How | Automate? |
|---|---|---|---|
| 1 | Sync 4 recordings | `_Synced` sequence; only V1/V4/A1 live, others disabled | manual today |
| 2 | Silence cut | CutDeck `aggressive`, no ASR, output renamed `YT editing` | automate (name output) |
| 3 | Content pass | delete bad pieces leaving gaps, close gaps in batches; chronological; drop pre-show start, a 10.7 min middle block, the post-show end | assist: needs transcript to learn the rule |
| 4 | Pick Short scene | copy one ~25 s good moment to the end of the timeline, edited later as a Short | assist (suggest candidates) |
| 6 | F1 live layer | F1 footage over main, whole video: Posterize Time 0.2, Screen, Opacity 80% | automate (fixed values) |
| 5 | Result | 80:35 live → 15:08 long video (~19%), ~28 min of editing | |

#### Step 6 (~14:05): stylised footage layer (user)
- **Do:** footage from source on the timeline with **Posterize Time, Frame Rate 0.2**
  (one new frame every 5 s, so a near-still image that steps), **Opacity blend mode Screen**,
  **Opacity 80%**.
- Screen at 80% = the footage is laid over the layer below as a light, see-through look
  (blacks drop out).
- **Answers (user):** the main (stream layout, V1 `10-40-52.mp4`) is underneath; the F1 live footage (V4 `10-55-45.mp4`) goes on
  top, blended into the small screen in the timing-screen area of the layout. **Whole
  video, same values every episode** (Posterize Time 0.2, Screen, 80%).
- **Automate?** **automate.** Fixed values every episode: a Premiere effect preset, or a CutDeck
  step that adds the F1 layer over the full length with these settings.
- **Checked in the 14:02 save:** V4 (`10-55-45.mp4`, 470 pieces, follows every V1 cut).
  **461 pieces** have Opacity 80, Blend Mode set, Posterize Time Frame Rate **0.2**, plus
  Motion **scale 40%**, position (0.489, 0.756) of frame, **crop top 10%** (the small-screen
  placement). The other **9 pieces = the parked 25 s scene** at the end: scale/position
  only, no opacity/posterize/crop. New empty track V5 added.
- File fact (one sample, not yet proven): Opacity's Blend Mode params store 22
  (ParameterID 2) and 10 (ParameterID 3) when the user chose Screen.
- V5 empty: not used (user).

#### Step 7 (by 14:12): export and upload (seen on a screenshot)
- YouTube Studio upload in progress: title **"Ferrari ออก Q2 ทั้งคู่ | F1 Las Vegas GP 2026
  Qualifying Reaction"**, saved as private, at the Initial check (copyright check done, ~18 min left).
- Title pattern: Thai hook on the session's story | F1 <GP> <year> <Session> Reaction.
- Export: `5. EXPORTS\YT q las vegas.mp4` written 14:06: 15:07.9, 1080p30 H.264 ~16 Mbps, AAC 381 kbps (1.8 GB). Length = the main body exactly, so the parked Short was left out (In/Out). Exported ~3 min after the F1-layer step (14:02 save), so no titles, subtitles or music pass for this format.
- _ask:_ export preset name; thumbnail; who writes the title.

#### Step 8 (14:15–): the Short (from the parked 25 s, src 63:30–63:54)
- **14:14 save:** duplicated `YT editing` as **`TT editing`** (TT = TikTok?). Exact copy so far:
  470 pieces per track, 16:9 1920×1080 frame, the parked scene still at tl 22:34.
- **14:14:32 save:** `TT editing` sequence settings changed to **1080×1920** (vertical 9:16).
- **14:15 save:** on the 9 Short-scene pieces only (V4, F1 footage): Motion **scale 109%**,
  anchor bottom-centre, position bottom-centre of the 1080×1920 frame. So the F1 picture
  (≈2093×1177 at 109%) fills the **bottom part** of the vertical frame, edge to edge
  (sides cropped ~500 px each). No Posterize/Screen on these, so it's a clean picture.
- **14:15:28 save:** V2 = the **face cam** (`10-40-53-cam.mp4`, disabled in the long video) is
  **enabled on the 9 Short pieces** and moved up: position y 0.50 → **0.257** (scale unchanged).
  Layout taking shape: **face cam on top, F1 footage across the bottom** (stacked 9:16).
- **14:16 save: hook + longer ending.** Short is now 23.7 s, 11 pieces:
  - **Hook:** the scene's last 1.7 s (src 63:52.4–63:54.1, the punchline/peak) **moved to the
    front**, then the scene plays from its start (63:29.7) to 63:52.0.
  - **Ending extended:** 2 pieces from src 64:05–64:10 (4 s) added after it (beyond the
    25 s originally parked; 63:54–64:05 skipped).
  - **Rule (Shorts):** open on the peak moment (≈1–2 s), then play the build-up in order.
    Unlike the long video, which has no hook.
- **14:16–14:17 (save + screenshot): zoomed leaderboard on the hook.** A copy of the hook's F1
  piece put on **V5** (same 1.7 s), then, via the **CutDeck panel Transform tab**: scale
  **226%**, crop top **50%**, crop bottom being set, position moved, so only the broadcast's
  **timing tower** shows, big, over the F1 picture: P10–P16 ANT, LEC, HAM, HUL, SAI, BOR, ALB
  = the proof of the story (both Ferraris out in Q2, the video's title).
  - **Rule (Shorts hook):** peak reaction + a zoomed crop of the broadcast graphic that proves
    the story. Face cam top (smiling/shocked), F1 bottom.
  - Tool note: the user drives Motion/crop through the CutDeck Transform tab, not Effect Controls.
  - Final V5 values (14:17 save): scale 226%, crop L 5 / T 50 / R 81 / B 25 % (keeps the broadcast's x 5–19%, y 50–75% = lower half of the timing tower, P10+), anchor bottom-centre, position (2.10, 1.16)×frame.
- **14:19 save: trim to the Short + SFX.**
  - `TT editing` now holds **only the Short**: the 15-min main body deleted, 11 pieces left
    (tl 22:34.2–22:57.9, 23.7 s; not yet moved to 0:00). Live: V1 stream layout, V2 face cam,
    V4 F1, V5 tower zoom, A1 voice.
  - **SFX:** `Dramatic-Vine.m4a` on A7 under the hook (tl 22:34.2–22:37.2, 3 s, 2 audio
    effects, probably volume/fade).
  - New sequence **`ALL`** (9:16) = the user's **SFX library on a timeline**: 81 clips, 60 sounds
    from `E:\Me\SFX\Free SFX - @theanhcine\` (Vine BOOM, Bruh, Record Scratch, F1 Radio
    Notification, Whoosh, Riser, Drum Roll, Crickets, …). Sounds are picked from it by ear.
  - **Rule (Shorts):** a dramatic SFX hit on the hook.
- **14:20 (screenshot, no-change saves):** the `ALL` SFX sequence comes from importing
  `SFX_1.prproj` (bin `SFX_1.prproj › 1 Sequence › ALL`). Now browsing **Effects › Video
  Transitions › Animation** (Block / Flip / Fold Motion) with the pieces right after the hook
  selected (~tl 22:35.9–22:38), so a transition from the hook into the build-up is next.
- **14:21 save: punch-in.** One F1 piece (V4, tl 22:37.9–22:41.3, src 63:31.9–63:35.3): scale 109 → **155%**, crop top 13%, re-positioned (x 0.5 → 1.35), a zoom on one part of the broadcast for that beat. (No transition was added in the end.)
- **14:22 save: tighten.** Cut 2.8 s from the middle (src 63:38.0–63:40.9) and added a split at tl 22:49.0. Short now **20.9 s** (tl 22:34.2–22:55.1). In `ALL`, `auughhh.mp3` nudged (auditioning SFX).
- **14:23 save:** the whole Short **moved to tl 0:00** (now 0:00–0:20.9), ready for export. (`ALL`: Clock-Ticking nudged, still auditioning.)
- **14:24 (screenshot):** Short is 0:00–0:20.28. The 155% punch-in shows the **full Q2 timing tower** (GAS P1 … LEC, HAM in the drop zone) over the F1 picture. A **second SFX** (teal clip on A8, ~tl 0:08–0:13, likely `Clock-Ticking` from `ALL`) runs under the build-up. Still browsing Video Transitions › Animation (Pop Motion). Not exported yet.
- **14:24:32 save: SFX in the Short (from the file, corrects the screenshot guess).**
  | tl | SFX | level |
  |---|---|---|
  | 0:00.0–0:03.0 (A7) | Dramatic-Vine (hook) | −12 dB |
  | 0:03.7–0:05.9 (A8) | auughhh | −24 dB |
  | 0:13.8–0:17.0 (A7) | Clock-Ticking (tension) | −18 dB |
  | 0:15.6–0:18.6 (A8) | Dramatic-Vine again (payoff) | −12 dB |
  - **Rule:** SFX always turned well down under the voice, in 6 dB steps; Vine boom on the
    hook and the payoff, ticking clock for suspense before the reveal.
  - dB inferred from the file: Volume Level is stored linear with 0.1778 = 0 dB (the untouched
    channel volumes sit at 0.1778); one project, not yet proven against the Premiere UI.
- **14:25: exporting the Short** (user).
- **Export (14:24):** `5. EXPORTS\20261121 - TT fer q2.mp4`: **20.9 s, 1080×1920, 30 fps**,
  H.264 ~16 Mbps, AAC 381 kbps (43 MB). Name pattern `YYYYMMDD - TT <topic>.mp4`
  (the long video was `YT q las vegas.mp4`, no date).
- Contact sheet (every 2.5 s): hook = shocked face + tower P10–16 over HAM onboard →
  Q2 full tower (punch-in) → HAM onboard 273 km/h → **one full-screen face-cam beat (~12.5 s)**
  → tower again at the payoff with HAM 12th. Cuts made in ~10 min (14:14–14:24).

### Short summary: rules learned
| What | Rule |
|---|---|
| Pick | while cutting the long video, copy a ~25 s story moment to the timeline end |
| Sequence | duplicate `YT editing` → `TT editing`, set 1080×1920, delete the long body, move to 0:00 |
| Layout | face cam (V2 `-cam`) top at y≈0.26; F1 (V4) bottom, 109%, anchored bottom-centre, no posterize |
| Hook | the scene's peak 1.7 s moved to the front + zoomed timing-tower crop on V5 (226%) proving the story |
| Pace | tighten mid-scene, one punch-in (155%), ~21 s total |
| SFX | from the `ALL` library: Vine boom on hook + payoff (−12 dB), tension tick (−18), meme reaction (−24) |
| Title | hook text = the YouTube title's Thai part, Prompt-Medium 100, white + black stroke 8, on the hook beat only |
| Export | 1080×1920 30 fps H.264 ~16 Mbps, `YYYYMMDD - TT <topic>.mp4` |
- **14:30 save (after the first export): title on the hook.** V6 Graphic, tl 0:00–0:01.73
  (exactly the hook piece): **"Ferrari ออก Q2 ทั้งคู่"** = the YouTube title's Thai hook.
  **Prompt-Medium 100, white fill, black stroke 8**, left-aligned, no shadow, text scale 87.8%,
  position (0.122, 0.365)×frame (left, about a third down, over the face-cam/F1 seam).
  - **Rule:** the Short opens with the video's title hook as on-screen text for the hook beat.
  - Expect a re-export of `20261121 - TT fer q2.mp4`.
- **Re-export 14:30:** `20261121 - TT fer q2 2.mp4` (with the title; the first export is gone).
  Freeze check on the lower 1100 px: **still** from 1.7–11.3 s and 16.9–20.9 s (frame holds),
  moving only on the 1.7 s hook and 11.3–16.9 s, which includes the full-screen face beat.
  So the Short follows the "F1 ≤ 3 s, otherwise stills" rule; my earlier "~20 s of moving F1"
  was wrong (the reader does not see frame holds; the contact sheet showed different stills).
  - Reader gap: `prproj_reader` doesn't report frame hold / time remapping on a clip.

#### Assignment (15:08): transcribe the YT timeline, pick the Russell/Antonelli radio clip
- Transcript of the export (= `YT editing` tl 0:00–15:08): faster-whisper, 2,946 words in 64 s,
  `test_projects/1raceclub/20261121/yt_export.words.json` (+ `.lines.txt`). The English team
  radio itself is not in it (Thai model, broadcast audio under the voice); the user's Thai
  retelling of it is.
- **Pick (tl in `YT editing` = time in the export):**
  | tl | what (user's words, paraphrased) | source |
  |---|---|---|
  | 10:55.8–11:44.8 | **Setup:** George asks the team to let him out behind Kimi (ANT) for a tow, since Kimi has a penalty tomorrow anyway; doesn't want to be first out on the long straight. "Let's see if the team agrees" | V1 76:21–78:32, F1 60:59–63:10 (RUSSELL RADIO caption on F1 60:56–61:02) |
  | 11:44.8–11:48 | "Kimi has to pass", "give me the cane" (they won't do it) | |
  | 12:37.0–12:49 | **Payoff:** Kimi ends up at the back of the queue; George: "now I'm in trouble", has to tow others | V1 80:58 |
  | 13:13.3 | "if Kimi doesn't make it, why didn't you use Kimi to tow George?" | V1 82:05 |
  | 14:52.2–15:08 | **Punchline:** "you have to ask why George wasn't behind Kimi… did they have to swap?" | V1 84:55 |
- Short shape by the principles: hook = the question (14:52 "why wasn't George behind Kimi?")
  or the payoff (12:37), then the radio request (10:56–11:30) with the RUSSELL RADIO still,
  then the outcome.

#### Agent-built Short (15:30): `TT russell kimi (Claude)`
- Built by the agent from the principles via panel `build_sequence` (base `TT editing`, not saved),
  38 items, read-back **0 mismatches**. 27.8 s, 5 beats cut on word boundaries:
  hook 0:00 "why wasn't George ahead of Kimi" (export 900.30) → setup 0:02.65 George asks to go
  out behind Kimi (673.75–684.95) → suspense 0:13.85 "let's see what the team says" (690.00) →
  payoff 0:16.65 Kimi ends up last, George in trouble (757.10) → end 0:24.5 "did they have to
  swap?" (903.15).
- Layout: face-only vertical cam (`10-40-51`) full frame; 3 s stacked proof at 0:03.8: landscape
  cam top (y 0.257), F1 feed 62:15–62:18 at 109% right-aligned on the **RUSSELL RADIO caption
  "OTHERWISE, CAN I GO BEHIND KIMI? GIVEN THE SITUATION FOR TOMORROW"**, crop top 10% (F1 TV bug
  gone, F1 bug off-frame). Preview frame checked offline.
- SFX: Dramatic-Vine on hook and payoff (−12 dB), Clock-Ticking under the suspense (−18 dB).
- Not done / gaps: no title text (panel can't build a Graphic); F1 is a 3 s video, not a still
  (build_sequence can't place imported stills or frame holds); `10-40-52` brought all 4 audio
  streams: stream 2 duplicates the voice (same level), streams 3–4 are silent, so **A2–A4
  must be muted** (build_sequence has no per-clip disable). Not exported.

#### User feedback on the agent's Short (15:56) and v2
- **Feedback (confirmed rules):** (1) **zero gaps**, v1 had two 1-frame gaps from rounding each
  piece's in/out/at separately; (2) **watch the preview before handing over**; (3) **keep all
  three cam layers**: copy them into the new sequence and edit from there, don't rebuild with
  one cam. Layers: **V1 = YT** (stream layout `10-40-52`), **V2 = only me** (`10-40-53-cam`,
  recorded sideways; the project rotates it upright, `transpose=1` matches), **V3 = me with
  data** (`10-40-51`, never used, kept disabled). v1 wrongly used V3 as the face.
- **v2 `TT russell kimi v2 (Claude)`:** every piece on all three layers with each layer's own
  source time; positions counted in whole frames (gap check in the plan: none); V3 and A2–A6
  disabled at the end (new `build_sequence` option `disable_tracks`); V2 full-frame face, moved
  up (y 0.257) only during the 3 s F1 proof. Read-back 0 mismatches, 108 clips disabled.
  Preview rendered offline (ffmpeg, same layout + SFX), checked by contact sheet, black-frame
  scan (none) and a transcript of the preview (beats in order).
- **v2 checked by a real Premiere render (16:07): wrong.** The cam was sideways and letterboxed:
  the user's V2 clips carry **Motion › Rotation 90°**, which the build did not copy (the ffmpeg
  preview rotated it, so it hid the miss), and the clone kept `TT editing`'s In/Out (0–20.93),
  so an In/Out export cut the last 7 s. Lesson: preview = render it **in Premiere**, not a model
  of it; copy every Motion field of the layer being reused, rotation included.
- **v3 `TT russell kimi v3 (Claude)`:** V2 rotation 90 on all 18 pieces, In/Out set to 0–27.8
  (`build_sequence` `mark_whole`). Premiere render (BAS4, scratch folder): 27.8 s 1080×1920,
  upright full-frame face, stacked proof 3.8–6.8 s, no black frames, no silence gaps, voice once
  (mean −18.9 dB). Saved file: zero gaps on every track, V3 + A2–A6 disabled, V2 rotation 90.

#### Copy-then-cut from `YT editing` (user's ask, 16:15): v6 `TT russell kimi v6 (Claude)`
- User: "on YT editing the footage is already synced, just pull it from there". New route:
  `cut_copy` copies `YT editing` and cuts it to the kept moments (Rough Cut engine), so every
  synced layer, effect, rotation and disabled state comes along; then `build_sequence` `into`
  edits that copy: `TT editing`'s settings (9:16), hook forward (lift head block → clone hook
  into the hole → lift the original → move the end beat left), restyle (V2 on + 90°, moved up
  in the proof window; V3, V4 posterized F1, A2–A6 off), proof on V5, SFX on A7/A8, In/Out.
- v4/v5 rendered **black on the hook** (a block moved backward past other clips); v6 uses
  clone + lift and renders clean. Checks: Premiere render 27.77 s 1080×1920, no black, no
  silence, −18.9 dB; identical to v3 for 0–3.75 s (PSNR 99.7), near-identical after the proof;
  `YT editing` unchanged (4,700 clips). Proof window 4.33–7.30 s (one frame cut in a pause at
  export 678.40 to give it a clip edge).

#### User's own Russell Short (17:02, after deleting the agent's v1–v6)
- In `TT editing` the user pasted one contiguous stretch of `YT editing` (all 4 layers +
  6 audio, as copied: V2/V3 disabled, V4 posterized F1 on): tl 1:22.53–2:00.10 (37.6 s),
  = export 672.5–710.1 (src 77:34–78:50), words: "รัสเซลล์เลยเดี๋ยวนี่ครับ … ให้กูออกหลังคีมี
  ได้ไหม … มาดูว่าทีมจะเอายังไง … ออกมาสี่นาที … คิมมี่ต้องแซง … ขอไม้เรียว".
- Versus the agent's pick: starts 1.3 s earlier (keeps "Russell, right now"), keeps the full
  stretch through to "ขอไม้เรียว" (export 710) instead of jumping to the payoff at 757 and the
  question at 900. _ask:_ why this range (is the payoff/question not needed, or coming next?).
- **17:05–17:07 (user):** V2 face on for the whole chunk with the Short framing (rotation 90,
  y 0.273); V4 Posterize/Screen removed, first piece at 109% bottom-anchored; **V5 = the RUSSELL
  RADIO caption cropped to the box only** (F1 62:19.9, crop L83 T44 R4 B28) moved to the very
  start (1:22.53, 0.67 s); **A8 = the real team-radio audio from the F1 feed**, two pieces
  (feed 62:12.8–62:14.5 and 62:17.0–62:18.4, 3.1 s total) at 1:23.30–1:26.37, right after the
  caption.
  - **Principle (to confirm):** a radio controversy is proven with the driver's own voice:
    play the real radio audio (a few seconds, jump-cut to the key line, inside the ≤3 s-ish
    limit) under the cropped caption, then the user's reaction.
- Note: sequences `TT russell kimi v7/v8 (Claude)` appeared at 17:05 and v8 is being edited
  with imported PNG stills (`russell_kimi_s1_sphere.png`, `_s2_radio`, `_s3_tail`, `_s4_pole`,
  `_title`): made by **another agent session**, not this one.

#### v8 `TT russell kimi v8 (Claude)` (~16:55–17:15, user: "do short for me, about russell ask to be behind kimi")
- v1–v6 were deleted from the project between 16:45 and 16:52, with no reason on record. v6 was almost all face (one 3 s F1 shot),
  unlike the user's own Short (F1 stills under the face for most of it, title on the hook). So v8 was rebuilt by the principles.
- **Story found in the transcript (missed by v1–v6):** George asks to go out behind Kimi; Kimi ends up last in the queue,
  gets the tow and **takes P1, 1:33.893** (George P3). That's the peak, so it's the hook.
- **Beats (export s), 27.8 s, zero gaps:** hook "แต่ทันเฉยเลยครับ คิมมี่เอาที่หนึ่งไป" (879.97) → request "ให้กูออกหลังคีมีได้ไหม…ให้คีมีมาชกลมให้หน่อย"
  (673.75–677.98, 683.25–684.95) → "มาดูว่าทีมจะเอายังไง" (690.00) → "คีมิเป็นหางแถว…กูงานเข้าเลย" (757.10, 762.43)
  → "คิมมี่เข้าเส้นคนสุดท้าย…คนสุดท้ายมันได้เปรียบ" (874.17, 884.30) → "ทำไมไม่เป็นพี่จอร์จ…ต้องสลับกันหรือเปล่าวะ" (899.02–904.45).
- **Picture:** stacked (V2 face y .257 + still on V5) for hook / request / twist / payoff; face only for the suspense and the closing question.
  Stills = PNGs made from the F1 feed (`6. ASSETS\russell_kimi\`): Sphere "#12 KIMI ANTONELLI" (hook), RUSSELL RADIO
  "Otherwise, can I go behind Kimi?" enlarged (request), Kimi onboard + tower ANT 6 + "tight with the flag, Kimi" (twist),
  tower ANT P1 1:33.893 + lower third (payoff). F1 / F1 TV bugs cropped out; no moving F1 video at all.
- **Title** "จอร์จขอออก / หลังคิมิ" (the channel's own spelling in past titles: จอร์จ, คิมิ) as a PNG `russell_kimi_title2.png` (Prompt Medium 100, white, black stroke 8, rendered by Edge for correct Thai), V6, hook only.
- **SFX:** Dramatic-Vine hook + payoff (−12 dB), Clock-Ticking under the suspense (−18), auughhh on "กูงานเข้า" (−24).
- **Tool change:** `build_sequence` items take `import: true` (file imported into CutDeck › Frame Holds before any read; an import made
  after reading invalidated the read objects: "The script object is no longer valid"). **Premiere fact:** a placed still read back **one frame short** of the requested out
  for lengths 26–74 frames and 60/61 (the 120-frame pieces landed exact), which left a 1-frame gap at the end of each still window;
  fixed by laying a 61-frame tail that ends on the window edge.
- **Leftover:** `TT russell kimi v7 (Claude)` is broken (a failed build had already run the hook-move steps; the retry ran them twice);
  no API deletes a sequence, so the user deletes it.
- **Checks:** Premiere render 27.8 s 1080×1920 30 fps; all 834 frames' lower band match the planned still (0 off), no black frames;
  voice −18.4 dB, no dropouts. Not exported to `5. EXPORTS`, not saved (save: false).
- **17:11 save: user tightens the chunk** (37.6 → 29.6 s, tl 1:22.53–1:52.17, 16 pieces):
  - First piece extended back 3 s (src 77:34.8–77:37.8) and now **wordless for 3.7 s: it carries
    the real Russell radio (A8) under the caption**; the user's voice starts after it
    ("นี่ครับรัสเซลล์บอกเฮ้ยให้กูออกหลังคีมีได้ไหม…").
  - Cut 10.8 s in 3 ranges: the **second, repeated explanation** ("เพราะว่าพรุ่งนี้คีมีโดนอยู่แล้วน่ะ
    ให้คีมีมาชกลมให้หน่อย… อย่างน้อยคีมีก็ได้ทำเวลา… ผลประโยชน์"), "รับนักต่อรองเอ้ย", and a filler.
  - Kept the live play-by-play after it: "ออกมาสี่นาที… คิมมี่อยู่ข้างหน้าหรือเปล่าวะ… คิมมี่อยู่ข้างหลัง…
    คิมมี่ต้องแซง… ขอไม้เรียว".
  - **Principles (seen, to confirm):** (a) let the real radio play alone first, then react;
    (b) say the point once: cut the repeat of an explanation; (c) a Short can be one
    continuous live moment (no jump to a later payoff) when the moment itself has the
    tension and the ending ("ขอไม้เรียว").
- **17:13 autosave:** 3 frames trimmed near tl 1:46.9; the V2 piece at 1:46.13 set back to **full-frame face** (y 0.273 → 0.5): a face-only beat (the pause before "คิมมี่ต้องแซง"), like the full-screen beat in the Ferrari Short. _ask:_ what triggers face-only (nothing to prove on screen at that moment / the reaction is the point)?
- **Joins:** a Premiere-render transcript reads every beat in order. Two joins sit in running speech and may carry a sliver of the next word: 0:15.9 ("ทีนี้" after "งานเข้าเลย", <1 frame) and 0:18.4 (tail of "ครับ" before "คนสุดท้าย"). Not re-cut; left for the user's ear.
- **17:13–17:17 (user): F1 pictures follow each spoken line, almost all frame holds**
  (the reader's `frame_hold` shows them):
  | tl | F1 hold (feed) | framing | says |
  |---|---|---|---|
  | 1:22.53–1:31.83 | 62:12.2 (V4) + RUSSELL RADIO caption 62:19.9 (V5, crop to box, 191%) | 109% bottom + caption over it | radio plays, then "ให้กูออกหลังคีมีได้ไหม…" |
  | 1:35.13–1:43.83 | 62:56.8, 63:00.2 | 109% bottom | "ออกมาสี่นาที… พี่จอร์จออกมามีใครอยู่ข้างหน้าไหม" |
  | 1:43.83–1:44.90 | 65:03.2 (V5): two Mercedes together on track | 109% bottom | "คิมมี่อยู่ข้างหน้าหรือเปล่าวะ" |
  | 1:44.90–1:46.13 | 63:22.2 (V6): RUS alone, 234% zoom | punch-in | "คิมมี่อยู่ข้างหลัง" |
  | 1:46.13–1:48.3 | none | full-frame face | (pause) "คิมมี่ต้องแซง" |
  | 1:48.33–1:52.07 | 63:26.4 hold, 150%, crop top 11 | zoom on RUS on the straight + mini-map | "ขอไม้เรียว" |
  - **Principle (seen, to confirm):** each line gets the still that shows what is being said
    (who's ahead/behind, the radio, the mini-map), zoomed to that element; a new picture per
    line, held, never running broadcast video. Face-only when the line is pure reaction.
- **17:19 autosave: radio treatment + SFX.**
  - **F1 Radio Notification Sound** (A9, −3 dB) at the very start 1:22.53, then the real radio
    (A8) **boosted +9 dB** from 1:23.17 (broadcast radio is quiet under the commentary).
  - V6 text layers (placeholders "New Text Layer") at 1:23.17–1:28.17, timed to the radio
    pieces: likely the **Thai subtitle of the English radio line**. _ask._
  - Dramatic-Vine (−12 dB) on "คิมมี่อยู่ข้างหน้าหรือเปล่าวะ" (1:43.83) and on "ขอไม้เรียว" (1:48.33);
    "fahhhhhhhh" meme at −51 dB under "คิมมี่อยู่ข้างหลัง" (1:44.77), barely audible: being auditioned?
  - **Principles (seen):** announce a radio with the radio-notification sound, then play the
    radio loud and clear (+9 dB); subtitle it; booms on the two reveal lines.
- **17:22 save: radio subtitle (confirmed by the file).** Thai translation of "Otherwise, can I go
  behind Kimi? Given the situation for tomorrow", **cut into short phrases timed to the words**:
  "ไม่งั้น" (1:23.17–1:23.77) → "ขออยู่หลังคิมิได้ไหม" (→1:24.87) → "จากสถานการณ์" (→1:25.67) →
  "พรุ่งนี้" (→1:26.23). Style = the Short title style: **Prompt-Medium 100, white, black stroke 8**,
  centred, y 0.447 (≈858 px, i.e. **just below** the 740 px seam, top of the F1 picture; corrected 17:55 from the export, it was logged as "above").
  - **Principle:** translate the radio into natural Thai, 1 short phrase at a time, each on
    screen exactly while it is spoken; same type style as titles.
- **17:23 save: driver labels on the still.** "RUS" (V6) and "ANT" (V7) text over the two-Mercedes hold (1:43.83–1:44.90), on "คิมมี่อยู่ข้างหน้าหรือเปล่าวะ". **Principle (seen):** when a still shows several cars, label who is who with the 3-letter code so the viewer can follow the line.
- **17:24 save: hook title** "จอร์จขออยู่หลังคิมิ" (V7, 1:22.53–1:26.23 = the whole radio opening), **yellow** fill (255, 234, 0; Ferrari's was white), left-aligned, sitting just above the seam while the white radio subtitle sits just below it. Like "Ferrari ออก Q2 ทั้งคู่": the story in a few Thai words over the hook. Here the hook is the radio itself (not a later peak moved to the front).
- **Export 17:25:** `5. EXPORTS\20261121 - TT rus ant.mp4`, 29.5 s, 1080×1920, 30 fps.

### Agent's Russell Short vs the user's: what to change next time
| | agent (v6) | user |
|---|---|---|
| Source | 5 beats from across the video (hook from 15:00, payoff from 12:37) | one continuous live stretch (10:12–11:50), tightened |
| Opening | the user's later question moved to the front | the real radio itself: notification sound → Russell's voice (+9 dB) → Thai subtitle, title "จอร์จขออยู่หลังคิมิ" |
| Repeats | kept the explanation said twice | said once |
| F1 pictures | one 3 s video proof (caption in the corner) | a held still per spoken line, zoomed to what is said (caption box 191%, RUS alone 234%, mini-map 150%), driver labels |
| Face | stacked only during the proof | stacked under every still, full frame on pure-reaction beats |
| SFX | boom on hook/payoff, clock under suspense | radio notification, booms on the two reveal lines |

### Full read of `TT editing` (17:24 save, read 17:50) and how to edit a Short
Read with `prproj_reader` (every clip, Motion, frame hold, text, audio level) plus 1-fps contact
sheets of both exports. `TT editing` is the user's only Short timeline (others: `YT editing`,
the agent's v7/v8, the `ALL` SFX library). It holds **both Shorts**: Ferrari at 0:00–0:20.93,
Russell parked further down at 1:22.53–1:52.07. Both export with In/Out, so a new Short is
built after the last one on the same timeline, not by deleting the old one.

**Track roles (same in both Shorts):** V1 YT stream layout (on, hidden under V2), V2 face cam
(rotation 90°), V3 me-with-data (off), V4 F1 still under the face, V5 a second still or a
cropped broadcast graphic over V4, V6–V7 text (and a third still when needed), A1 voice,
A2–A6 off, A7–A9 SFX and the real radio audio.

**How to edit a Short (the procedure, statuses per line):**
| Step | What | Status |
|---|---|---|
| Pick | one self-contained moment, often a controversy; can be one continuous live stretch | confirmed (controversy) / seen |
| Open | **anything** that makes people keep watching longer (the peak moved forward, the real radio, or something else); never a fixed opener, judge each Short by what will hold *this* viewer | confirmed (user: the principle is watch time) |
| Tighten | cut a repeated explanation, fillers; say each point once | seen once |
| Picture per line | for each spoken line, a held F1 still of exactly what is said, zoomed to that element (tower, caption box, the two cars, the mini-map); the hold frame is chosen inside the piece, not its first frame | seen in both |
| Face-only | full-frame face when the line is pure reaction / nothing to show: Ferrari 0:11.3–0:14.8; Russell 1:31.8–1:35.1 (after the radio, explaining) and 1:46.1–1:48.3 (pause before "คิมมี่ต้องแซง") | confirmed: face = my opinion/taste, or nothing on screen is about the story |
| Moving F1 | ≤3 s and only where motion is the point (Ferrari hook 1.7 s) | confirmed |
| Text tiers | **yellow** hook title = the story in a few Thai words, above the seam; **white** subtitles in short phrases just below it; 3-letter driver labels on a still with several cars | confirmed (colours) |
| Radio | notification SFX → real radio boosted (+9) → Thai subtitle phrase by phrase | seen once |
| SFX | boom on reveal lines, tick under suspense, meme on a reaction; all under the voice | seen in both |
| End | where the context of that story closes in the user's own telling, not at a later payoff | confirmed |
| Export | In/Out on the Short, 1080×1920 30 fps, `YYYYMMDD - TT <topic>.mp4` | seen in both |

**New from this read:**
- Ferrari hook frame = the biggest **physical** reaction (both hands on head), not only the
  words: the hook beat is chosen by the face too. *(guess)*
- Russell's hook title is **yellow**, subtitles white: two text roles on screen at once
  need two colours. Ferrari had only the title, in white. *(guess; ask)*
- The two V4 pieces at 1:43.83–1:46.13 are moving video but fully covered by the V5/V6
  holds (RUS/ANT still, mini-map 234%), so the viewer sees stills only (checked on the export).
- `fahhhhhhhh-earrape.mp3` at −51 dB: an "earrape" file is mastered extremely loud, so a big
  cut may just bring it to a normal level. Not checked by ear.

**Not read (gaps):** transitions and audio fades, speed changes, the text layers' own
position/scale (only seen on the export), whether −12/−18/+9 dB match the Premiere UI.

**User's answers (17:58, confirmed):**
1. In/Out on the timeline covers **only the Short being exported** (now Russell). Opening on the
   **real radio** is a retention choice: the radio makes people stop and listen, so they watch
   longer. → Principle: open on the source moment that makes the viewer *want to hear what
   comes next*.
2. **Face-only = my opinion / my taste**, or when **nothing on screen is about the story**.
   The stills are for facts; the face carries the take.
3. **Yellow = hook title, white = subtitles.** A colour per text role (Ferrari's white title
   predates or breaks this; follow yellow for hook titles from now on).
4. The Short ends on "ขอไม้เรียว" because **that is where the context of that story ends**:
   end where the user's own telling of the moment closes, not at a later payoff.
5. The "fahhh" file is too loud, so it is turned down to −51 dB **on purpose; it is still
   audible**. → set SFX level by ear against the voice, not by a fixed dB.

#### v11 `TT russell kimi v11 (Claude)` (user feedback ~17:30: "crop good but needs improvement, audio gets cut mid-sentence")
- **Audio rule (confirmed by the feedback): every beat is a whole sentence, and each cut sits in a real pause.** Edges are
  placed from the audio envelope (10 ms), not from ASR word times, which ran ~0.1 s off (v8/v9 clipped "รัส" of รัสเซลล์).
  Beats touching in the source get a one-frame cut in the pause between them. 37.9 s (was 27.8).
- **Crop v2:** background dimmed (72%) under the enlarged proof graphic; radio caption 2.3x + George's P3 lower third; tower
  cut to header..ANTONELLI row; hook = Kimi on the Sphere filling the panel.
- Render checks: 1138/1138 frames match the plan, voice −18.7 dB, render transcript = whole sentences in order.
- v7 and v10 broken (failed builds), v8/v9 older drafts: user deletes them. Panel change committed as d998092.

### FP3 Short: `TT max vs everyone v2 (Claude)` (agent edits, user monitors, 18:30-19:10)
- User: "finish the short on this timeline, Max vs everyone he has trouble with: Alpine, Mercedes, McLaren".
  Source: the FP3 stream rough cut `2026-11-21 07-07-37_Synced — CutDeck 17e4f3f9` (silence cut only, no transcript),
  transcribed whole, then each rough-cut clip in the candidate windows transcribed on its own to place edges.
- The user's own summary line was the spine: "มีปัญหากับเพื่อนทุกคนแล้วตอนนี้ กับนอริสก็ทีหนึ่ง กับรัสเซลก็ทีหนึ่ง ต้นๆเซสชันก็มีอัลไพน์" (rough cut 24:25).
- Beats (rough-cut s → Short): hook Mercedes contact "เกือบแปะกันแล้ว… แล้วแปะกันไปเลย / มีปัญหากันทุกคนวันนี้แม็ก"
  (1396.5–1406.1) → the list (1465.1–1474.1) → Alpine "ปิดประตูใส่… เจอกันในอินไซด์มั้ย… ใจเย็น" (1039.9–1041.9, 1048.8–1059.8)
  → McLaren "พ่นควันใส่นอริส… เวรกรรมมันตามทัน" (1164.1–1175.2) → Mercedes radios "ผลักกูเข้ากำแพง", "มึงเล่นเกม"
  (1516.8–1564.7, 4 pieces) → end "Session นี้พี่แม็กเอา MVP ไป มีปัญหากันทุกคน" (1587.5–1590.9). 59.6 s, 27 pieces, every edge on a rough-cut clip edge (a VAD pause).
- Picture: V2 face (rotation 90; y .273 stacked under a still, .5 face-only), F1 holds on V4 (109%, anchor/position bottom),
  Max onboard as moving video only on the first 2.8 s; yellow title "แม็กมีเรื่อง / กับทุกคน" (V5 PNG, Prompt Medium 100, stroke) over the hook.
- **The F1 feed on V4 is not in step with the talk**: at each spoken incident the feed shows other cars, so stills were picked
  by who is named (Gasly/Colapinto Alpine, Norris box, Russell helmet/car, Max onboard), not as footage of the incident itself. _ask:_ is the feed offset, or did the user watch a different view?
- Tool changes: new driver command `create_sequence` (made `TT editing` 9:16 from the stock preset); `build_sequence` accepts an
  empty base; a fresh-clone build no longer clears items on tracks the base lacks (v1 lost all V4/V5 items that way).
- Checks: Premiere render 59.57 s 1080x1920 30 fps, no black frames, no silence ≥0.6 s, mean −21.3 dB; render transcript has every line whole and in order.
  Not saved (save: false), not exported to `5. EXPORTS`, no SFX. `TT max vs everyone (Claude)` (v1, stills missing) is junk for the user to delete.

#### User feedback on v2 (19:15) and v3 `TT max vs everyone v3 (Claude)`
- **Feedback (confirmed rules):** (1) storytelling good; (2) **don't repeat the same speech**: v2 said "มีปัญหากับทุกคน" three times
  (hook, list, end); (3) **use the live F1 footage already synced on the rough cut (V4)**: the real situation, not stills picked by who is named;
  (4) **copy the rough cut and work from there** (v2 rebuilt from items, so it had 4 audio tracks instead of the rough cut's 6).
- v3 route: `cut_copy` of the rough cut keeping only the 12 pieces (every layer, all 6 audio tracks, disabled states kept) → `build_sequence`
  `into` that copy: `settings_from` `TT editing` (9:16), reorder by steps (clone Alpine+McLaren past the end, lift, clone hook+list back
  to 0, lift, clone Alpine+McLaren into the hole, lift; no backward `move`), restyle per piece (V2 on, rotation 90, y .273 stacked /
  .5 face-only; V4 synced feed 109% bottom-anchored, off on face-only pieces), title PNG on V5, In/Out whole.
- Repeats cut: list starts at "กับนอริสก็ทีหนึ่ง…"; end trimmed inside its clip at a measured 50 ms dip to "Session นี้พี่แม็กเอา MVP ไปครับ";
  Russell's first radio ("ให้มึงเห็นวิดีโอ…") dropped, so "รัสเซลบอก" is said once. Face-only: "ไม่เอาครับ… ใจเย็น", "แตะมือกันข้างนอก", the end line.
- Checks: Premiere render 50.93 s 1080x1920, no black frames, no silence ≥0.6 s, −20.8 dB; per-piece transcript of the render in order, no repeated line.
  Not saved, not exported, no SFX. v1/v2 are junk for the user to delete.
- **19:20 user: the V4 sync was wrong** ("i give you the wrong live message on sync"); user re-synced the F1 feed and re-ran the
  rough cut (`CutDeck 94fd4bb9`, same voice mapping and same cut points). Now the feed matches the talk: RACE CONTROL "VERSTAPPEN,
  RUSSELL INCIDENT" on the hook, Gasly's Alpine beside Max on the Alpine beat, NORRIS RADIO "INSTANT KARMA, AMAZING!" on the McLaren beat.
- **v4 `TT max vs everyone v4 (Claude)`**: the v3 recipe on the new rough cut (6 audio, 5 video tracks, 50.93 s). Not rendered by the agent
  (user rule 19:16: the user exports, the agent never runs export_sequence); checked by read-back (0 clip mismatches), feed frames pulled
  from the source at each piece, and v3's voice transcript (same voice pieces). In reads unset (null), Out 50.93.
- **19:35 user: "dont forget to check the frame".** Composited each piece offline from the source files (cam rotated 90 and placed,
  feed with its Motion, title) since the agent no longer renders. Found: the re-synced feed is a new file `2.mp4` at **1280x720**, so
  the 109% built for 1920x1080 left it small with the seam at 1135 px; and the centred crop cut the evidence at the frame edges
  (RACE CONTROL "VERSTAPPEN, RUSSELL INCIDENT" banner top right, NORRIS RADIO "INSTANT KARMA, AMAZING!" far right, the Mercedes
  contact far left). Fix on v4 (restyle into, 19 feed clips): 163.5% (= the user's 109% of a 1080p frame, seam ~740 px), and per-clip
  framing toward the evidence: banner clip right, overhead clip at 109% so both cars and the banner fit, Norris radio clips right,
  contact clip left. **Principle (seen): frame each feed clip on what proves the line (caption, banner, the two cars), not the centre;
  and scale by the source's real size, not a fixed %.**
- **19:20 v4 lost.** Premiere restarted (RecoveryProjects at 19:17–19:18, panel reconnects) and reopened without v4, which was built after
  the 19:10 save and never saved. Rebuilt: the first `cut_copy` failed "razor filler on audio track 2 is not one frame long" (left
  `TT max vs everyone v4 (Claude) (FAILED)`); the identical retry passed, so it's the intermittent native-cut razor. v4 rebuilt in one build
  with the per-clip framing; the hook banner clip needed source-x centre 740 to show the full RACE CONTROL line. In 0, Out 50.93.
  Lesson: an unsaved agent build is lost if Premiere restarts. The agent doesn't save (`save: false`); tell the user to save once it looks right.

#### User's own cut of the Max Short (19:33 save, In/Out 92.7–135.1 in `TT max vs everyone v4 (Claude)`, 42.4 s, 17 pieces)
Parked after the agent's v4 in the same sequence; read with prproj_reader, each piece transcribed from source.
| user s | words (rough-cut s) | picture | vs agent v4 |
|---|---|---|---|
| 0–7.8 | hook "เกือบแปะกันแล้ว… แล้วแปะกันไปเลย / มีปัญหากันทุกคนนะวันนี้แม็ก" (1396.5–1406.1) | holds: Russell onboard with the Red Bull alongside (183.5%, crop top 11, framed on the RB), overhead | same words; holds not video; own Text title 0–4.5 s (not the PNG over 8 s) |
| — | list "กับนอริสก็ทีหนึ่ง… อัลไพน์" | | **dropped** |
| 7.8–14.1 | "แล้วพี่แม็กจะ…เข้าไปที่อินไซด์ / อืม ไม่ปล่อยแน่นอน ฮ่าฮ่า / หัวจะปวดเลยวะ" (**rough cut 150–156, session start**) | holds from `1.mp4` (feed of the session start): Max onboard with the Alpine ahead, Max with Colapinto behind | **the agent's Alpine beat (17:20) was the wrong incident**; the real Alpine one is at the start ("ต้นๆเซสชันก็มีอัลไพน์") |
| 14.1–17.4 | "ยุบหนอพองหนอ พี่แม็กใจเย็นพี่ ใจเย็น เวลามีอีกเยอะ" (1056.4–1059.8) | face only | kept as the reaction |
| 17.4–27.1 | McLaren from "ไปแล้ว โอ้โห" (1165.5) → "พ่นควันใส่นอริส" → "นอริสบอก… เวรกรรมมันตามทัน" | hold: Norris onboard + NORRIS RADIO "INSTANT KARMA, AMAZING!" box cropped (L83 T43 R5 B36) at 333.5% on V5 | dropped "แม็คลาเรนเล่นซัดกัน" |
| 27.1–34.7 | "ถูกันทีเลย" → "แตะมือกันข้างนอก" (face only) → "แม็กบอก ผลักกูเข้ากำแพง" | holds: Max onboard, the two cars side by side; VERSTAPPEN RADIO box "HE'S JUST PUSHED ME INTO THE BARRIER" enlarged | same words |
| 34.7–40.4 | **"รัสเซลบอกให้มึงเห็นวิดีโอ… ตัดหน้ากู"** (1557.7) → "สนุกใช่ปะหล่ะ มึงเล่นเกม" **from 1562.8, inside the clip** | Russell helmet hold + RUSSELL RADIO box "DID YOU SEE THE REPLAY OF VERSTAPPEN?", then moving onboard with the box "AFFIRM… CUT ACROSS THE FRONT OF YOU / HA HA… FUN AND GAMES EH" | agent dropped the first radio to avoid repeating "รัสเซลบอก"; the user kept both radios and cut the **repeated words only** |
| 40.4–42.4 | "Session นี้พี่แม็กเอา MVP ไปครับ" | face only | same |
**Principles (seen):** (1) "use the synced footage" = pick **frame holds** from it, one per line, framed on the evidence; the radio caption box cropped and enlarged (the Russell Short recipe), moving video only where the radio plays; (2) a repeat is cut at the repeated words, not by dropping the content; (3) verify which incident a line is about from the footage before cutting (the session-start Alpine moment); (4) **the list line went (confirmed, user 19:40):** naming the rivals in a row ("กับนอริสก็ทีหนึ่ง กับรัสเซลก็ทีหนึ่ง… อัลไพน์") is telling, and it felt too long to hold the viewer; cut straight to the actual problems Max had instead. **The principle underneath (user 19:45: think principle, not rules that change easily): every second must keep the viewer watching longer.** A line that only delays the next real moment (an announcement, a list, a repeat) is where they swipe away, so it goes. "Don't announce" and "cut repeats" are just today's cases of it. _ask:_ what does the Text title say?
- **User flags on the agent's title (19:50):** (1) the title must be **editable text** (a Premiere Text/Graphic layer), not a PNG;
  (2) the title PNG ran **one frame past the cut** (frames 0–246, the shot changes at 245 = 00:00:08:05; the user saw it at 08:06).
  Cause: the plan asked one extra frame for every still ("Premiere lays a still one frame short", seen for 26–74-frame stills), but this
  246-frame PNG landed full length. Lesson: don't pad stills blindly; read back each still's end against the cut and fix it.
- **19:46 save: user refines the Short (In/Out unchanged 92.7–135.1). SFX on A7, levels as dB vs Premiere's 0 dB (0.1778):**
  | Short s | SFX | level | sits on |
  |---|---|---|---|
  | 2.27 | Dramatic-Vine | −12 dB | "แล้วแปะกันไปเลย" (the contact), 3 frames before the piece |
  | 7.37, 10.87 | auughhh | −27 dB | Max with the Alpine: "…เข้าไปที่อินไซด์", "ไม่ปล่อยแน่นอน ฮ่าฮ่า" |
  | 17.33 | Dramatic-Vine | −12 dB | start of the McLaren incident, 3 frames before |
  | 20.5 | F1 Radio Notification | −9 dB | NORRIS RADIO caption appears (6 frames before it) |
  | 27.0 | Dramatic-Vine | −12 dB | "ถูกันทีเลย" (Russell contact), 3 frames before |
  | 32.0, 34.73, 38.43 | F1 Radio Notification | −9 dB | each radio caption: VERSTAPPEN "pushed me into the barrier", RUSSELL "did you see the replay", RUSSELL "fun and games" |
  Also: the last Russell piece's moving feed became a **frame hold** (1558.67); its caption box moved from V6 to V5. Now every feed picture is a hold.
  **Principles (seen, the watch-time idea):** a boom marks the start of each new incident (a new reason to keep watching), landing a few
  frames ahead of the line; the radio sound announces each radio caption so the eye goes to the box; a meme sound, low, colours Max
  being stubborn; holds everywhere, so motion never pulls attention from the caption.
- **Radio caption effect (user 19:50 "you see effect i add on radio?"):** a **Glitch transition** (`AE.AE_Impact_Glitch`, Film Impact),
  9 frames (0.3 s), at the head of each enlarged radio caption box on V5: 20.7 s (NORRIS), 32.0 s (VERSTAPPEN), 34.73 s and 38.43 s (RUSSELL).
  Starts on the same frame as the F1 Radio Notification SFX, so the box glitches in as the radio sound plays: it reads as a radio
  "coming in". **Principle (seen):** a caption that's evidence enters with a sound and a visual hit together, so the eye jumps to it.
  `prproj_reader` now lists each track's `transitions` (name, match name, start/end, which side of the edit).

### Agent's own Short #2: "Turn 14 lock-ups" (19:55, in `TT max vs everyone v4 (Claude)` at 140.00–160.37, parked after the user's cut)
User: "copy my text layer for the title and try to create a Short, pick one". Story picked for watch time: one self-contained moment
with a payoff, from the FP3 rough cut (rough-cut s):
| Short s | words | picture |
|---|---|---|
| 0–4.8 | hook: "ล้อล็อกว่ะ / พยายามจะเลี้ยวรถเข้าไปแต่ / ถ้าเลี้ยวเข้าไปน่าจะกำแพงครับ" (1202.33–1207.17) | holds: Hamilton onboard locking into T14 (HAMILTON 44), turning in, the ZOOX wall |
| 4.8–6.8 | "ถอยดีกว่า! ไปยูเทิร์นดีกว่า" (1207.17–1209.10) | face only (his joke); auughhh −27 dB |
| 6.8–9.8 | "แล้วล้อล็อกไปครับ รัสเซล โค้งห้า" (1177.17–1180.20) | hold: Russell onboard |
| 9.8–15.0 | "โอ้โห แล้วล้อล็อกกันเพียบเลย / แทรกอุณหภูมิมันเย็นขึ้นหรือยังไงวะ" (1186.50–1191.70) | holds: Leclerc's tyre smoke at T14, Leclerc's car at T14; boom −12 dB 3 frames ahead |
| 15.0–16.7 | "แทรกสิบเจ็ดองศาตอนนี้" | face (nothing on screen shows it) |
| 16.7–20.4 | "ใครยังไม่ล็อกบ้าง / โค้งนี้มาไม่ถึงเวกัสนะ โค้งสิบสี่" (1193.37–1197.07) | hold: Hamilton at T15, then face for the closing joke |
- Dropped "โค้งสิบสี่จุดเช็คอินจริงจริง" (1212.3): it repeats "โค้งสิบสี่" right after; the Short ends on the joke instead.
- Title: the user's own Text layer (V6, 92.7 s) cloned to 140.0 with the new step option `tracks` (clone only V6); its words are still
  the Max title for the user to retype. Proposed: "โค้ง 14 ล็อกทั้งสนาม".
- Holds are imported PNG frames of `2.mp4` at 163.5% (not Premiere Frame Holds), framed per frame (offline composite checked).
- **Premiere fact again:** stills of 40–98 frames landed one frame short (the 246-frame title landed exact; 120 exact in v8): pad a
  still by one frame only when it's under ~120 frames, then read back. Re-laid, they end on their cuts.
- In/Out left at the user's 92.7–135.1 (the agent no longer sets marks on a shared Short timeline). Not saved, not exported.
