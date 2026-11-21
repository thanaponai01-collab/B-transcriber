# How to edit a 1RaceClub Short: principles and rules

The working memory for editing the user's F1 Shorts (TikTok, YouTube Shorts, Reels), learned from the user on
2026-11-21 (the Ferrari, Russell/Antonelli, Max-vs-everyone and Turn 14 Shorts). The evidence, step by step, is in
[1RACECLUB_WORKFLOW.md](1RACECLUB_WORKFLOW.md). Read this file before editing a Short.

**How to read it.** A **principle** is the reason, and it carries over to any footage. A **rule** is how the
principle is applied today, and it can change. Values (109%, −12 dB, 740 px) are examples, not presets
(user: "not copy everything I do… understand why"). Status: **confirmed** = the user said so;
**seen** = read from the user's own timeline; **guess** = inferred, still to confirm.

## 0. The one principle: watch time

**Judge every second by whether it keeps the viewer watching longer.** Anything that only delays the next real
moment goes. *(confirmed, 19:45: "look at the principle of making the audience watch longer")*
Most rules below are this principle applied to one case.

## 1. Pick the story

| Principle | Rules today | Status |
|---|---|---|
| One self-contained moment that needs no context, with a setup, a peak and a payoff | pick it while cutting the long video; 20–45 s so far | seen |
| Controversy is a top pick: something people will argue about | team orders, a radio row, a driver told "no", one driver clashing with everyone | confirmed |
| Verify from the footage which incident each line is about before cutting it | the agent took the 17:20 moment as "the Alpine incident"; the real one was at the start of the session | confirmed (user's cut) |

## 2. Open

| Principle | Rules today | Status |
|---|---|---|
| The first 1–2 s must stop the scroll; the opener can be anything that keeps people watching | the peak moved to the front (Ferrari, Max's contact with Russell, Hamilton at T14); or the real source moment itself (the Russell radio) | confirmed |
| A title says the story in a few words, for sound-off viewers | yellow hook title over the hook only, ending **on a cut** | confirmed (colour, end on cut) |

## 3. The speech

| Principle | Rules today | Status |
|---|---|---|
| Every beat is a whole sentence; never cut mid-word | edges in real pauses, set from the audio envelope (10 ms), not from ASR word times (~0.1 s off) | confirmed |
| Say each point once | cut a repeated explanation; **cut a repeat at the repeated words** (start the next piece after "รัสเซลบอก"), don't drop the content | confirmed |
| Don't announce or list what's coming: show it | the "with Norris once, with Russell once, Alpine early on" line felt too long to hold, so cut straight to each actual problem | confirmed |
| End where the context of the story closes in the user's own telling | not at a later payoff; a closing joke is a good last line | confirmed |

## 4. The picture

| Principle | Rules today | Status |
|---|---|---|
| The face carries the take; F1 pictures carry the facts | face on top, F1 picture below, with the **chin above the seam at ~740 px** (feed bottom-anchored, filling 743–1920); face-cam y is reset per Short (0.257 / 0.273) | confirmed |
| Face only when it's the user's opinion or taste, or when nothing on screen is about the story | full-frame face (y 0.5) on jokes and reactions ("ยุบหนอพองหนอ ใจเย็น", "ถอยดีกว่า ไปยูเทิร์นดีกว่า", the MVP line) | confirmed |
| A held still per spoken line, showing exactly what's being said | **frame holds from the synced live feed**, a new hold per line; moving F1 video **at most 3 s**, only where motion is the point | confirmed (copyright + "use that footage") |
| Frame each hold on what proves the line, not the centre | shift the window to the evidence (two cars, the glowing wheel, the TURN label); scale by the **source's real size** (109% for 1080p = 163.5% for the 1280x720 feed) | confirmed ("check the frame") |
| Label who is who when a still shows several cars | 3-letter codes (RUS / ANT) on the still | seen |

## 5. Cropped assets (radio boxes, tower rows)

| Principle | Rules today | Status |
|---|---|---|
| Blow up the piece of broadcast graphic that proves the line | radio caption box cropped (e.g. L83 T43 R5 B36) and enlarged ~333%; a tower row cropped and enlarged | confirmed |
| Crop **only the part that's needed** | one tower row (e.g. "8 HAM +1.506"), not the whole table; table crops on the left | confirmed |
| All cropped assets on **one layer** | V5 | confirmed |
| Keep assets in the **safe zone of every platform** | union of TikTok / Shorts / Reels UI on 1080x1920: keep inside **x 60–890, y 250–1440** (top bar, bottom caption and music bar, right action buttons; Shorts has the widest right column) | confirmed (values are the agent's) |
| A radio box arrives as a hit the eye follows | **Glitch transition** (Film Impact `AE.AE_Impact_Glitch`, 9 frames) on the box's head, starting on the same frame as the F1 radio notification sound | seen |

## 6. Text

| Principle | Rules today | Status |
|---|---|---|
| One colour per text role | **yellow** (255,234,0) = hook title; **white** = subtitles | confirmed |
| Text must stay editable | a Premiere **Text layer** (Graphic), never a PNG; the agent copies the user's own Text layer and the user retypes the words (the API can't write text) | confirmed |
| Text ends on a cut | trim the title to the cut it belongs to; no frames hanging past it | confirmed |
| Translate English radio into natural Thai, one short phrase at a time, on screen exactly while spoken | Prompt-Medium 100, white, black stroke 8, just below the seam | seen (Russell Short) |
| Channel spellings of names | จอร์จ, คิมิ | seen |

## 7. Sound

| Principle | Rules today | Status |
|---|---|---|
| A sound marks each new reason to keep watching, under the voice | Dramatic-Vine boom (−12 dB) at the start of each new incident, **~3 frames ahead** of the line | seen |
| Announce a radio | F1 Radio Notification (−9 dB) on each radio caption; the real radio boosted (+9 dB) when it plays | seen |
| A meme sound colours a reaction | auughhh (−27 dB), fahhh (−51 dB): low on purpose, still audible | confirmed |
| Set SFX levels by ear against the voice, not by a fixed dB | a file mastered too loud goes very low | confirmed |

## 8. Brand and copyright

| Principle | Rules today | Status |
|---|---|---|
| **No F1 logos anywhere visible** | the F1 / F1 TV bug, the F1 REPLAY tag, the F1 mark on the tower: crop them out, or remove them from the hold (smooth fill from the surroundings), or blur **smoothly** (feathered, no hard box) | confirmed |
| Sponsors are fine | TAG Heuer on the name badge, liveries, track ads stay | confirmed |
| Broadcast video kept to a minimum | holds, moving F1 ≤ 3 s | confirmed |

## 9. Timeline conventions

| Rule | Status |
|---|---|
| Layers: V1 YT stream layout (on, under the face), V2 face cam (rotation 90), V3 me-with-data (off), V4 F1 hold, V5 cropped assets, V6 title text; A1 voice, A2–A6 off (duplicate and silent streams, cam, data), A7 SFX | seen |
| **Copy the rough cut and work from there** (all layers and 6 audio tracks come along), don't rebuild from items | confirmed |
| All Shorts of an episode live in one 9:16 timeline, each parked after the last, exported by In/Out over that Short only | confirmed |
| Zero gaps | confirmed |
| The user exports and saves; the agent never runs an export, not even to check | confirmed |
| Check every frame before handing over (composited offline from the source files when not rendering) | confirmed |
| Export name `YYYYMMDD - TT <topic>.mp4`, 1080x1920 30 fps | seen |

## 10. Agent checklist for a Short

1. Transcribe the rough cut. Pick one story; verify every incident in the synced feed.
2. Choose pieces: whole sentences, edges in pauses, no repeats, no announcing, an opener for watch time, end where the story closes.
3. `cut_copy` the rough cut to just those pieces; reorder with clone + lift (never a backward `move`); `settings_from` a 9:16 sequence (`create_sequence` from the 9:16 preset if none exists).
4. One hold per line from the synced feed (PNG frames today), framed on the evidence, F1 logos removed; face-only on opinion lines.
5. Crops on V5, only the needed part, inside the safe zone; a glitch and a radio sound on radio boxes.
6. Copy the user's Text layer for the title (`steps: clone` with `tracks`), then `trim` it to end on a cut.
7. SFX on A7.
8. Read back: every still ends on its cut. Stills under ~120 frames land one frame short, so pad those by one frame.
9. Composite every piece's frame offline: framing, safe zone, no F1 logo. Hand over unsaved and unexported.

## 11. Gaps: what the user hasn't covered yet (notes and questions)

- **Length.** Shorts so far run 20–45 s. Is there a target, or a cap per platform (Shorts allows up to 3 min)?
- **Subtitles for the user's own Thai speech.** None so far, only translated radio. Does a sound-off viewer need them, and in which style?
- **Title wording.** Who writes it, how many words, and should it match the YouTube title? The agent can't type into a Text layer; the user retypes.
- **Hook title length.** The user's ran 4.5 s; the agent's ended on the first face cut (4.83 s). Is the rule "until the first cut after ~4 s"?
- **Feed graphics outside the safe zone.** Lap-time boxes, the TURN label and the bottom of the tower inside a 163.5% hold can sit under the platform UI. Crop them, or accept them as background?
- **Transitions.** Hard cuts everywhere except the glitch on radio boxes: is that the rule?
- **Loudness.** Voice measured −18 to −21 dB mean; no LUFS target set for Shorts.
- **Music bed.** None seen in Shorts: never, or not yet?
- **Ending.** No end card, call to action or loop seen: deliberate?
- **Cover frame / thumbnail** for Shorts: not covered.
- **Frame Hold vs PNG still.** The user uses Premiere Frame Holds on the feed; the agent places PNG frames, because the API can't make a Frame Hold. Same on screen, but is it fine on the timeline?
- **Feed resolution.** The 1280x720 feed upscaled to 163.5% looks soft. Is a 1080p feed recording possible?
- **Driver labels** (RUS/ANT) seen once: are they needed on every multi-car still?
- **How many Shorts per episode,** and how to rank candidates beyond "controversy".
- **Caption, hashtags and upload** per platform: not covered.
- **Safe-zone values** are the agent's own union of the platforms; please confirm or correct them.
