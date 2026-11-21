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
5. **First 1–2 s = the outcome/peak (here the "oh no" reaction to both Ferraris out), then
   how it happened.** A short has to stop the scroll before it explains; the long video
   can wait for the story. *(guess; the move is confirmed by the timeline)*
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
