# 1RaceClub workflow log

Started 2026-11-21. The agent watches the user's Premiere saves (Ctrl+S and Auto-Save), diffs
the timeline with `cutdeck/prproj_reader.py`, logs each step here, and asks the rule behind
each judgment call. Same method as [the HKS workflow log](../hks/workflow-log.md).

**Goal (user, 2026-11-21):** teach the agent *how to edit*, meaning the reasons behind each
choice, so it can make its own decisions when the footage, story or format changes. Values
(109%, −12 dB, 0.2) are only today's example of a principle; they are not presets to replay.
The **Editing principles** are now in [principles.md](principles.md) (moved 2026-11-22); this log is the evidence.
**For Shorts, the consolidated principles and rules (and the open gaps) are in [shorts-rules.md](shorts-rules.md).**


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
- **User 20:05 on Short #2:** "better"; (1) the text must finish on a cut (the cloned title ran 140.0–144.5, the cut is 144.83);
  (2) "I want to see you cropping some part, like the radio and the table on the left". Fix: new build step `trim` (tail trim through
  `createSetOutPointAction`) ends the title at 144.83, where the last hook hold cuts to the face. Pictures re-picked after a 0.5 s scan:
  the 1186–1193 stretch is Hamilton locking at T14 again, so "แทรกอุณหภูมิเย็นขึ้น" now holds on his glowing front-right at T14
  (framed to keep the TURN 14 label) then the tyre smoke; **the timing tower is cropped (L4.5 T16 R81 B4) and enlarged 190% on the left
  (V5)** over "ใครยังไม่ล็อกบ้าง", with Hamilton's car framed to its right. No radio caption exists in this stretch, so no radio crop.
  Read-back: all 9 stills end on their cuts. The title trim isn't read back by the build: confirm after a save.
- **User 20:15:** (1) cropped assets go on **one layer** (V5, where the user also consolidated every radio box); (2) keep them in the
  **safe zone of every platform**; (3) the timetable on the left but **only the row that matters**, not the whole tower.
  Safe zone used (1080x1920, union of TikTok / YouTube Shorts / Reels UI: top bar, bottom caption + music bar, right action buttons;
  Shorts has the widest right column): keep assets within **x 60–890, y 250–1440**. The full tower (y 780–1867) sat under the
  caption area. Now: only "8 HAM +1.506 M" (crop L4.7 T42.08 R82.19 B54.86 of the 1280x720 feed), 310%, at x 70–591, y 800–868,
  top-left of the picture, over "ใครยังไม่ล็อกบ้าง" with Hamilton's car beside it. Read back on its cut.
  Note: the feed's own graphics (lap box, TURN label, F1 TV bug) inside a 163.5% hold can still fall outside the safe zone.
- **User 20:25: F1 logos are not allowed; sponsors are fine.** Remove the F1 / F1 TV / F1 REPLAY marks wherever they fall inside the
  visible window of a hold; if they can't be removed, blur them, but smoothly (no hard-edged box). Sponsor marks (TAG Heuer on the
  name badge, car liveries, track ads) stay. Done on the Turn 14 Short: the F1 TV logo (x 1066–1210, y 36–66 of the 1280x720 feed)
  sat inside the window of the two Hamilton wide holds (1190.5, 1193.1); filled from its surroundings (diffusion fill, feathered
  4 px edge) in the hold PNGs (`hold_*_clean.png`) and swapped in, ending on their cuts. The other holds' F1 marks fall outside
  their windows. Check every hold's visible window for F1 marks before building.

## Episode 20261122: Las Vegas GP Race (agent-cut long video)

Project `E:\Me\2.Tasks\20261122 - 3\…\20260130 RENAME template - Copy_1.prproj`, user's synced sequence `Editing`
(2:02:55, V1 layout / V2 cam off / V3 off / V4 race feed at 39% in the small screen, A1 voice, A2–A6 off).
User: "you go cut the video for me". Agent's order (content first, so the silence cut runs on 21 min, not 2 h):
1. Transcribed the voice file (11,419 words). Feed sync checked from frames: SAFETY CAR banner on "เซฟตี้" (tl 30:45), lap 50/50 at the flag.
2. `keep_words` on `Editing` → `YT editing (Claude)`: 59 moments, 20.9 min, chronological (start, every lead change and
   Red Bull battery "same picture" duel, Hadjar's P2 and broken wing, SC and pit stops, penalties, team radios, Russell's
   debris, Kimi's battery loss on the last lap, the finish, the post-race strategy summary, the closing line). Dropped the
   SC laps' chatter, the podium/ceremony (90–119 min) and repeats.
3. F1 layer on all V4 pieces: Posterize Time 0.2, Opacity 80, Blend Mode param [2] = 10 (param [1] stayed 18; a rendered
   frame shows the screen look, not yet checked in Effect Controls).
4. CutDeck silence cut (aggressive, no ASR) → `YT editing (Claude) — CutDeck cef3c7f3`: **16:41**, zero gaps on every
   track, V2/V3/A2–A6 disabled, transcript in source order. Not saved, not exported.
5. **User feedback:** "you miss some story there like contact of ferrari, dont miss those along the live" → principle 1a.
   v2 adds 23 beats by storyline (Ferrari pair from lap 1 to the contact and the 10 s each; Hamilton's penalty, pit
   radio and cleared investigation; Piastri from 17th; SC radios). `YT editing v2 (Claude) — CutDeck a590dad6`:
   **20:53**, 78 moments, zero gaps, F1 layer on all 520 pieces, transcript in source order.
   - Premiere crashed twice on this pass: once right after the F1 params on a 78-range keep_words copy of the 2 h
     sequence, once during the same keep_words. Fix that held: cut in two passes (cut_copy of 24 coarse blocks, then
     keep_words on that 50 min copy), and add_effect in batches of 10 with retries ("no clip starts at" was transient).
6. **User: "check again what you might miss and also the logo f1".** Second storyline pass added 18 beats (Kimi's
   passes and last-laps duel with Max, Hadjar's unsafe-release investigation and clearance, Russell going for two cars,
   the yellow flag before the crash, Max's SC radio, Gasly back to P3, Norris past Kimi and on the Alpine, Russell to
   P4, "anyone can win now", the podium recap). **Logo rule for the long video too:** the feed's F1 logo +
   "FIA Formula 1 World Championship" wordmark (top left, down to ~11.5% of the frame) and F1 TV (top right) are cut
   with Motion **crop top 12%** (the user's 10% left the wordmark's bottom edge; 12% keeps "LAP x/50").
   Final `YT editing v3 (Claude) — CutDeck 808f672d`: **23:10**, 96 moments, zero gaps, transcript in race order.
   - **Third Premiere crash, cause found:** hundreds of per-clip `set_param` calls in a row (crashed after ~380).
     Route that held: copy `Editing` with only the F1-only tail cut (V4 stays ONE clip), set Posterize/Opacity/Screen/
     crop on that one clip (5 calls), then cut_copy (coarse) → keep_words (fine) → silence cut; the cuts carry the
     effects onto all 595 pieces.
7. **User: "dont cut the sentence out like mid way, finish it"** (v3 had cuts inside words at 05:22, 05:50, 06:44,
   11:46, 17:16, 17:45, 20:10, 20:12) → principle 1b. Every v3 moment was extended back and forward to the nearest pause
   (gap >= 0.6 s, cap 25 s), giving 96 moments and 32.1 min of raw keep. `keep_words` on the stage-A copy then reported 0 cuts in
   sound (`YT editing v4 (Claude)`, 32:24). The silence cut (aggressive, speech protection on) took it to
   `YT editing v4 (Claude) — CutDeck e705c7bb`: **25:03**, 596 cuts. It has zero gaps, V2/V3/A2–A6 off, Posterize/Opacity/
   Screen/crop on all 629 V4 pieces, and frames (16:40 on the pre-silence copy, 20:00 on the final) matching the stream's lap with the logo gone.
   `timeline_transcript` flags 24 "sound" edges, each within 40 ms of quiet (no clipped word on the transcript; the
   worst one to listen to is 07:57 "ไซน์").
   - **Fourth Premiere crash:** apply_cuts of the silence cut on v4, in a session that had already built the base and
     run stage A and keep_words. Premiere just vanished (no Application Error event). Crash recovery kept all v4
     sequences. After a fresh launch and a user save, the same 596-cut apply ran in 18 s. **Rule:** ask the user to
     save before the silence cut, and run it in a fresh Premiere session.
8. **Workflow talk after v4** (user: "we duplicate it like 4 times... can it be only one base?"). Agreed order →
   principle 1c. Built `premiere_paste_attributes` for the last step and tested it on throwaway copies: 744 plain
   pieces took the source's Opacity/Screen, crop 12 and Posterize 0.2 in 24 s with no crash, and one Undo
   reverts it. Paste only onto unstyled pieces, because a piece that already has Posterize gets a second one. The
   full-live rough cut (2 h → several thousand cuts) has not been run yet; the test ran 738 cuts on a 44 min copy in 28 s.

### Agent's Short: "Hamilton pit call" (2026-11-22 17:10–18:00, `TT hamilton pit call v2 (Claude)`, 22.3 s)
User: "create me short ... for 1raceclub" from `YT editing v4 (Claude) — CutDeck e705c7bb`; the agent picked the story.
Controversy pick: Ferrari keeps Hamilton out under the Safety Car because of his 10 s penalty, then pits him anyway and he
drops to P14. Every beat verified on the synced feed (feed = voice − 1237.13 s): 10 SECOND TIME PENALTY banner, HAMILTON
RADIO boxes "WE ARE STAYING OUT", "EVERYONE'S COME IN! / WE HAVE A 10 SECOND PENALTY…", "IF I TURNED IN, WE WOULD'VE
CRASHED!", "…COMING OUT P15 OR P16 / THAT'S UNBELIEVABLE", tower "1 HAM 0" under the SC and "14 HAMILTON" after.
| Short s | words (v4 s) | picture |
|---|---|---|
| 0–2.5 | hook "ห๊ะ / ถ้าไม่งั้นบอกแล้วมึงเอากูเข้าพิตทำไมวะ" (658.07–660.57) | pit stop hold + radio box "P15 OR P16 / UNBELIEVABLE"; title |
| 2.5–9.77 | "แฮมิลตันเรดิโอ ทีมบอกสเตย์เอาท์… ทุกคนมันเข้าพิตแล้วเว้ย / เรามีสิบเพนัลตี้" (624.3–631.57) | onboard holds + "STAYING OUT", then "EVERYONE'S COME IN / 10 SECOND PENALTY" box |
| 9.77–14.43 | "โห ตัดแทรก / แต่แฮมิลตันบอก… กูเลี้ยวเข้าไปกูก็ชนแล้วเว้ย" (697.1–701.77) | replay with the penalty banner; side-by-side replay + "IF I TURNED IN" box |
| 14.43–22.3 | "เพราะถ้าเข้าพิตไปน่าจะออกมาที่สุดท้าย… สุดท้ายเข้าพิตเหมือนเดิม ออกมาที่สุดท้ายอยู่ดี / จะตลกให้" (647.77–655.63) | SC hold + tower rows "1 HAM 0 / VER 1 / RUS 1"; Hamilton car + "14 HAMILTON" row |
- Route: `create_sequence` `TT editing` (empty 9:16, for settings) → `cut_copy` of v4 (5 cuts, 2 s) → `build_sequence` into:
  reorder by clone/lift, V2 face on at y 0.235 (this episode's cam puts the chin above the seam there, not 0.273), PNG holds
  at 109% centred (F1 / F1 TV / REPLAY marks fall outside the window), radio boxes and tower rows on V5 inside x 60–890,
  y 250–1440; Dramatic-Vine −12 dB on the hook, the replay and the twist (3 frames ahead); F1 Radio Notification −9 dB
  on A8, starting with each box's Glitch (9 frames); Basic Title "แฮมิลตันเดือดทีม!" on V6, 200%, ends on the hook cut.
- v1 (`TT hamilton pit call (Claude)`) said "แฮมิลตันเรดิโอ" twice (hook + next piece): v2 starts the hook at "ห๊ะ".
  v1 is junk for the user to delete.
- Checks: read-back (every hold and crop ends on its cut, 669 frames), `timeline_transcript` 0 cuts in sound,
  Premiere frames at 9 points. Not saved, not exported. Title is white Basic Title (the API can't set colour or font):
  the user restyles it yellow / Prompt or retypes.

### Agent's Short: "Ferrari contact" (2026-11-22 18:10–18:40, `TT ferrari contact (Claude)`, 21.8 s)
User: "make another short from the same race ferrari hitting each other". Verified on the feed: Hamilton's #44 sideways under
a yellow flag (lap 38), the HAMILTON REPLAY inset with Leclerc's car alongside (feed 5869–5871 voice s), stewards' banners
"LECLERC, HAMILTON INCIDENT – TURN 7 – COLLISION – UNDER INVESTIGATION" (6118–6123) and "10 SECOND TIME PENALTY LECLERC –
CAUSING A COLLISION" (6246). Race order already opens on the contact, so no reorder.
| Short s | words (v4 s) | picture |
|---|---|---|
| 0–2.57 | "เอาละๆ เลอแคลร์ก็ไม่…" (1062.97) | #44 sideways at the aramco wall; title "เฟอร์รารี่ชนกันเอง!" |
| 2.57–6.4 | "เออ แปะกันนะ เฟอร์รารี่ / เรียบร้อย แปะกับ" | REPLAY inset (Hamilton onboard, Leclerc alongside) cropped 190% on V5 |
| 6.4–10.7 | "สองคัน / แปะกันนะ เลอแคลร์กับแฮมิลตัน" (–1073.67) | overhead of the corner + LEC/HAM name badges stacked (one PNG on V5) |
| 10.7–13.53 | "ในที่สุดก็แปะนะครับ โอ้โห" (1073.83–1076.67) | face only; auughhh −27 dB |
| 13.53–16.4 | "เลอแคลร์กับแฮมิลตันโดนสอบนะ / จังหวะแปะกัน" (1182.5–1185.37) | investigation banner text cropped 139% over the hold's own banner; boom |
| 16.4–21.8 | "เลอแคลร์โดนสิบวิ โอ้โห / เฟอร์รารี่สองคันโดนไปยี่สิบวิ" (1199.6–1205.0) | penalty banner text cropped 152%; boom |
- Lessons: a cropped banner at the hold's own size adds nothing, so crop only its text and enlarge it over the original. Avoid a hold
  whose bottom repeats the badges placed on V5. Stills of 77 and 86 frames landed one frame short this time (115+ exact),
  leaving a 1-frame sliver of the old feed piece: removed it and trimmed the hold out by one frame. Always read back.
- `timeline_transcript`: one edge 12 ms into sound at 19.0 s (between "โอ้โห" and "เฟอร์รารี่"), inherited from v4's own cut.
- Not saved, not exported. Title white Basic Title (user restyles it yellow / Prompt).

### Agent's Short: "Ferrari contact v2" (2026-11-22 18:40–19:00, `TT ferrari contact v2 (Claude)`, 30.4 s)
User: "i want the one that lec told team that tell HAM to not squezzing him in as well, and i want the action pic that they both
hit". Leclerc's radio is on the feed at voice 3283–3286 ("LECLERC RADIO 16: HE NEEDS TO BE CAREFUL WITH THIS SQUEEZING BECAUSE
IT'S NOT GOING TO END WELL"), streamer reading it at v4 510.87–519.5. Action picture: the live feed was on the blimp/Sphere at
the moment of contact and there is no full-screen replay before the stewards, so the only shot of the hit is the HAMILTON REPLAY
inset; 5869.6 has the other Ferrari sideways across Hamilton's nose. Hamilton's reply radio ("CAN YOU TELL HIM TO BACK THE ****
OFF", voice 3413–3420, v4 529.9–534.9) exists but was left out.
| Short s | words (v4 s) | picture |
|---|---|---|
| 0–2.57 | "เอาละๆ เลอแคลร์ก็ไม่…" (1062.97) | hit inset 5869.6 at 190% over the 5805 hold blurred 6 px and dimmed to 40%; title |
| 2.57–6.4 | "เออ แปะกันนะ เฟอร์รารี่ / เรียบร้อย แปะกับ" | #44 sideways (5805) |
| 6.4–10.7 | "สองคัน / แปะกันนะ เลอแคลร์กับแฮมิลตัน" | overhead 5803.5 + LEC/HAM badges |
| 10.7–13.53 | "ในที่สุดก็แปะนะครับ โอ้โห" | face only; auughhh |
| 13.53–19.03 | "…ระวังหน่อยนะ บีบกูเข้ากำแพง เดี๋ยวจะจบไม่สวย" (510.87–516.37) | hold 3284 + LECLERC RADIO box 200%; F1 radio SFX on the box's first frame |
| 19.03–22.17 | "มันจบไม่สวย… ไม่จบทั้งคู่" (516.37–519.5) | face only (the payoff of the radio) |
| 22.17–25.03 | investigation (1182.5–1185.37) | banner text 139%; boom |
| 25.03–30.43 | penalty (1199.6–1205.0) | banner text 152%; boom |
- Order: the radio was said before the contact in the race; it was moved after the hit, because the hook is the hit and the
  radio then reads as "he warned them". Reorder by clone/lift steps (8 steps).
- Hook: an inset on top of the sideways-car still read as a collage; a blurred, dimmed copy of the background still makes the
  inset the only thing to look at.
- Same one-frame-short stills again (77 and 86 frames): removed the slivers, trimmed out by one frame. Title asked 79 → landed 77.
- `timeline_transcript`: one edge 12 ms into sound at 27.6 s (inherited from v4, same as v1); one tail 5 ms at 19.0 s.
- Not saved, not exported.
- Revision (19:20–19:45), user: "First shot, it should be like Leclerc about to go into the inside. Then the second shot needs to
  be they hit each other", then "it should be the drone shot as i remember but its small". The contact IS on the live feed:
  the blimp/drone shot over the TAG Heuer corner, cars ~20 px. 5799.8 = the two Ferraris side by side (Leclerc inside);
  5800.0–5800.2 = one pitched sideways (the hit); yellow flag at 5801.0. Shot 1 (0–2.57) = crop 300×169 of 5799.8 at 300%,
  shot 2 (2.57–6.4) = crop of 5800.1 at 300%, both over the dimmed 5805 hold, glitch in on each. This replaces the #44
  sideways shot. (The onboard-replay frames 5868.93 / 5869.30 were tried first and swapped out.)
  Lesson: when the user remembers a shot, look for it at small scale in the wide shots before saying it isn't there.
  Placement via build_sequence into the live sequence (items only) overwrites cleanly. Stills placed exact length
  this time (116 → 116) while a 78 landed 77, so always read back.
- By the time of the revision the sequence ended at 856 (28.53 s): the tail "สองคันโดนไปยี่สิบวิ" (856–913) was gone on
  every track, with the 6246 holds trimmed to 856. The user confirmed they cut it: end on "เฟอร์รารี่", not on the 20 s total.
- Revision 2 (19:45–20:00), user: "first 1-3 secs is too static". Shot 1 is now a moving clip: the drone feed 5798.95–5800.05
  (1.1 s, 50 fps source), with a crop that pans to follow the pair (330×186, centre x 1010→893, y 818), slowed to 2.57 s and
  rendered to `drone_inside_slow_sq.mp4` (900×508, `setsar=1`), Motion Scale 83.33 at (90,790). It ends on the frame before
  the hit still (5800.1), so shot 1 runs straight into shot 2. Lesson: a hook of 2+ s on a still reads as static; when the
  source has motion, slow it down and track it instead of holding a frame.

### Agent's Short: "Russell hits the wall" (2026-11-22 19:30–20:10, `TT russell wall v3 (Claude)`, 14.4 s)
User: "make another short from the same race with RUSSELL hit the wall then max said something after that but i didnt mention".
Feed (voice s): Russell attacks Antonelli 6755.2, slides wide 6756.4, into the T-Mobile wall 6757.6; "George RUSSELL 63"
badge 6759.7+. VERSTAPPEN RADIO 6865–6872: "HA HA WELL DONE! MY GOD…" / "OK MAX, WELL HE IS STILL GOING". The streamer
did read it ("แม็กเรดิโอ" 6873.6, "แม็กบอกเว้ย สุดยอดไปเลย ไม่รู้พูดถึงอะไรครับ" 6880.9) but didn't know who it was about; the
team's reply, a lap after the crash, answers that. That stretch isn't in v4 (v4 skips 6795–6909), so the Short is cut from
`Editing` (the full synced timeline: Editing s = voice − 1759.367; same layers as v4).
| Short s | words | picture |
|---|---|---|
| 0–3.53 | "แล้วมาลึกเลยครับในอินไซน์ เอ้ย แล้วไปชนอะไรไม่รู้พี่จอร์จครับ" | crash clip, real time, feed 6755.3→ (crop 1306×980 under the F1 TV logo, 1080×810 at y 790) over a dimmed 6758.2; title "รัสเซลชนกำแพง!"; boom |
| 3.53–6.57 | "แล้วโอ้โห ชนกำแพง เหมือนไปชนเศษ" | 6759.1 in the wall + RUSSELL 63 badge 160% (the hold is from before the badge appears, so no duplicate) |
| 6.57–9.37 | "เศษฟร้อนวิงของฮาจาครับพี่จอร์จ" | 6762.7 |
| 9.37–14.37 | "แม็กเรดิโอ / แม็กบอกเว้ย สุดยอดไปเลย / ไม่รู้พูดถึงอะไรครับ" | dimmed Russell-in-the-wall background + the radio box at 240%: Max's line, then on "ไม่รู้พูดถึงอะไร" the box with the team's reply; F1 radio SFX |
- Edges: transcript word times were off by up to 0.4 s (a gate made 6880.2–6880.86 digital silence; "แล้ว" began 0.2 s
  before its word time). v1 and v2 had cuts into words; v3 has every edge set from a 20 ms RMS scan of the voice. Lesson:
  measure the audio at each edge before building, don't trust word starts.
- v1 `TT russell wall (Claude)` and v2 are junk for the user to delete.
- Crash clip rendered blank at frames 98–101 until re-encoded all-intra (PREMIERE_FACTS row).
- Not saved, not exported. Title white Basic Title (user restyles it).

#### v4 `TT russell wall v4 (Claude)`, 12.9 s (user: "ไปชนอะไรไม่รู้พี่จอร์จครับ i need that first … debris flicking up from George Russell car, I want that shot first")
- The debris is **~5 s before the wall hit**, not near it: feed (voice s) 6752.86–6753.10 sparks and a piece fly up off the
  Merc on the main straight (wide shot, the Red Bull to its right). I first searched 6753.6–6757.4 and missed it; the user
  said "rewind 5 seconds before George hit the wall". Lesson: when the streamer reacts late, scan wider before the incident.
| Short s | words | picture |
|---|---|---|
| 0–2.10 | "เอ้ย แล้วไปชนอะไรไม่รู้พี่จอร์จครับ" (6761.96–6764.07, RMS dips both ends) | debris slow-mo 2× from 6752.5, tracking crop 624×680 → 1080×1178 filling **the whole lower part** (y 742 = cam bottom → 1920; user asked for full bottom, not a box over the dim hold); title "รัสเซลชนอะไร?!"; boom |
| 2.10–5.10 | "แล้วโอ้โห ชนกำแพง เหมือนไปชนเศษ" | crash clip real time from 6756.7, so the wall hit lands on "ชน" (~2.9 s); glitch in |
| 5.10–7.90 | "เศษฟร้อนวิงของฮาจาครับพี่จอร์จ" | 6759.1 + RUSSELL 63 badge; glitch in |
| 7.90–12.90 | radio part as v3 | as v3; glitch in |
- "แล้วมาลึกเลยครับในอินไซน์" dropped so the hook opens on the question. Not saved, not exported.

#### v5 `TT russell wall v5 (Claude)`, 12.9 s: user feedback on v4 (21:00)
User: no "blackout" (dimmed blurred background under a box), the bottom part must be full footage; copy the text the
user placed over mine exactly (style and position); don't render clips, use the synced footage from the base the way the
user does (slip the synced feed to the moment); files the agent makes belong next to the .prproj, not elsewhere.
- Built as a copy of v4 (cut_copy with a cut past the end, [[387,388]], keeps every layer and the user's text clip).
- V4 = `Las Vegas GP 2026 Race.mp4` itself, six clips (In = voice − 1237.13), each framed by Motion to fill y 742–1920
  (cam bottom edge at 742): anchor at the feed point, position (0.5, 1331/1920), scale = fill, Crop Top keeps it off the cam.
  Debris 6752.5 at 50% via set_speed (32 frames placed, slowed to 63); wall 6756.7 at 120%; in-the-wall 6759.1 at 109%
  (the RUSSELL 63 badge comes up in the live feed, no crop still needed); radio 6865.8 / 6866.6 / 6870.2 at 160% framed
  on the VERSTAPPEN RADIO box (box live on screen 6864.5–6872+, reply text from ~6869).
- No stills, no mp4 renders, no dim layer; V5 and my V6 title removed. Glitches on V4 at 63/153/237.
- Title: the user's own Graphic (V7, 0–77, bold white, dark outline, sits just above the cam edge; it read
  "เฟอร์รารี่ชนกันเอง!") kept with all its settings; text changed to "รัสเซลชนอะไร?!" with edit_text. Graphic source text
  style isn't readable by the API, so copy the user's clip, don't rebuild from Basic Title.
- Audio, edges and SFX unchanged from v4. Not saved, not exported.
- **User's frame holds on v5 (21:09):** the user added CutDeck panel "Add Frame Hold" stills on V5
  (`PREMIERE PRO\CutDeck\CutDeck_Hold_*.png`, sequence-size PNG, transparent above the cam): debris freeze 36–63, wall
  freeze 105–237, and a disabled radio hold 237–387, then asked: "the Max radio part: just capture, cut that hold, then crop it".
  Done: their radio hold cut to 237–333, enabled, Motion-cropped to the box (x 530–925, y 1100–1465 in the PNG) at 200%,
  centred in the bottom part; a second hold captured at frame 375 (box with the team's reply, y to 1560), saved as
  `CutDeck_Hold_<ms>.png` in the same folder, placed 333–387 with the same crop. Live feed keeps moving underneath.
  Pattern: callouts = frame hold of the timeline + crop on the hold, not a PNG cut from the source file.
- **User (21:15): "remember the safe zone and the copyright rule: least video possible, that's why I captured holds."**
  Both were already in `shorts-rules.md` and v5 broke them: 5 s of live video behind the radio box, and the box at 200%
  reaching x 935 / y 1696. Fixed: radio background = one CutDeck hold (feed at 109%, aerial, no radio box, no logo;
  top 742 px transparent like the panel's holds) 237–387; boxes 190% / 150% centred at (475, 1091), inside x 60–890,
  y 250–1440 (checked on rendered frames). Visible moving F1 video now 0–36 + 63–105 = 2.6 s. Glitch moved to the radio
  box head (V5 237). The user also retitled their text "RUS ชนกำแพง" and trimmed it to 0–63; left alone.
- **User (21:17): "always keep the raw footage"**: I had removed the radio part's source clips and put the hold on V4.
  Restored: V4 = `Las Vegas GP 2026 Race.mp4` for all six parts (radio part at 109%, In 6865.8 / 6866.6 / 6870.2);
  background hold on V5 237–387; radio boxes moved to V6 (237–333, 333–387, crops and safe-zone framing kept, glitch on
  V6 237). Rule: the source stays; holds and crops sit on tracks above it.

### Agent's clean-up of the LV GP post-race rough cut (2026-11-24 23:30–00:00)
User: "clean up cut to the point, no sponsor, start with ต่อหลังเรซ; if not sure don't cut, keep it and list it"; then
"the things you spot or don't know, just mark it on the timeline you created". Source: `2026-11-24 21-10-00 (2)_Synced —
CutDeck 288308f0` (55:42), untouched. Result: `LV GP 2026 Post-race YT clean v2 (Claude)` (49:47), via `cut_words`.
- Cut (17): pre-show + sponsor (starts on the 2nd "มาต่อหลังเรซ", after the ขนมตรามือ read; the 1st one is in the pre-show
  chat), chat replies (ไก่ย่าง, กินข้าว, ไลฟ์กี่ชั่วโมง, greetings), searching for pictures/clips, deciding what to talk about
  next, words after the goodbye. No new cut lands in sound.
- Not cut, marked (11 markers named CHECK/DECIDE): chat replies I couldn't place, a name slip with no pause to cut in, and the
  whole post-race chat Q&A (6:46, incl. giveaway) — the user decides.
- Lesson: three first-try joins landed in sound (a mid-phrase name fix, a cut starting inside "ละกัน"); start/end the range
  one line wider at a real pause instead.

### LV GP post-race Shorts from `yt` (2026-11-25 evening, agent)
User: "first video Kimi, how Kimi lost the position; second Max with the plate strategy (first plate, second plate);
the state-of-charge bit goes in the Max video". Timeline `TT 20261124 Shorts (Claude)` in the 20261124 project: a copy
of the imported `TT russell wall v5 (Claude)` (for the 9:16 settings and the user's title Graphic), cleared.
- Kimi 0–44.07 s (9 pieces, hook "รอบสุดท้ายไปเผลอทำสิ่งผิดปกติ … ร่วงไปที่สี่", spot-the-difference, lift + brake,
  340→286, battery reset, "ออกจากโค้ง 16 มาไม่มีแบตเตอรี่"); title "ANT ร่วงไปที่ 4" 0–3.1.
- Max 60–137.5 s (14 pieces: hook "กูให้มึงแซง … เดี๋ยวกูแซงมึงรอบต่อไป", plate 1 with Russell, SoC (red = recharge,
  super clip ~300 m), tow + super clip + overtake mode, plate 2 lap 13); title "VER ยื่นพาน" 60–63.37.
- Layout: V2 cam rot 90 y 0.235 enabled; V4 = clone of V1 framed on the board (anchor on the evidence, scale = 1178/h,
  crop top at the seam). Kimi framed per scene; Max still on one default framing.
- Route: `cut_copy`/`keep_words` failed on yt ("razor filler on audio track 0 is not one frame long"), so pieces went in
  with `paste_from` per piece. Premiere crashed on the ~19th paste_from in a row (unsaved work lost); after that, a
  `save_project` after every paste and no crash in 23 more.
- **User feedback (same night):** "jerky between cuts" + "it's storytelling, not action; I don't understand it; use words
  to organize the story; Kimi needs context first (what, why)". Cause of the jerk: 16 one-frame flashes from other
  moments, because the pause padding around each piece crossed one of yt's own cuts. Fix: padding stops at yt's clip
  edges (0 one-frame clips after). Rebuilt on the copy `TT 20261124 Shorts v2 (Claude)` (user: "duplicate the
  sequence"): Kimi 0–69.7 s = what happened → before that (lap 49 "last try") → why (lift + brake, battery reset) →
  result (T16, no battery) → Mercedes didn't tell him; Max 90–172 s = the plan (ยื่นพาน) → where the battery charges →
  plate 1 → plate 2 → mind game. Chapter words are copies of the user's title Graphic, each ending on a cut
  (ก่อนหน้านั้น, ทำไม, ผลลัพธ์, แบตชาร์จตรงไหน, พานที่ 1, พานที่ 2, มายด์เกม; agent's wording, to confirm).
