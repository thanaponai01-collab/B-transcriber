# Club Friday (CFD) workflow log

The evidence: what the user did, step by step, and the reason they gave.

Each step: **Do** / **Input → output** / **Decisions** (the rule) / **Time** / **Automate?**

## 2026-11-26 — workflow as the user described it (not yet watched)

1. **Do:** put all clips on one Premiere timeline, 1…N. **Input → output:** 5–10 finished episode
   videos → one long-form sequence. **Automate?** yes (place clips).
2. **Do:** in each clip, cut the opening and the ending. **Decisions:** keep the full story (CFD-1).
   **Automate?** yes, from the transcript; needs to learn what an opening/ending sounds like.
3. **Do:** pick the advice, normally one per host, put it on screen as text quoting their exact words.
   **Decisions:** CFD-2, CFD-3, CFD-4. **Automate?** propose picks from the transcript, user approves.
4. **Do:** pick 3 clips, make them vertical Shorts, add subtitles. **Automate?** yes (reframe,
   SubtitleDesk); the pick is the user's until we learn why.

## 2026-11-26 — answers on Shorts and clip structure (user's words)

- **Shorts:** 3 separate Shorts, one clip each. Pick by strongest story (drama or unique), and a caller
  line that catches and raises a question. One advice per Short, related to the story, near the end
  (CFD-5, CFD-R6…R9).
- **Clip structure:** highlight → topic/intro (intro or SFX) → body (host greets the caller) → outro.
  Sometimes the clip cuts straight to the body (CFD-R2).
- **Text style:** the user will show it on the timeline.

## 2026-11-26 — order, Shorts count, text style

- Clips go in file order 01…10; 3 Shorts is fixed now.
- Text: blue-green = host, pink = caller (highlight only, skip for now). The user showed the CFD 98
  timeline; what was read: [memory/host-quote-style.md](memory/host-quote-style.md),
  [memory/long-form-layout.md](memory/long-form-layout.md).
- Template holds cold open / intro / banners / transitions; agent does the mechanics only for now.
- Not every clip has two advices: one is fine; sometimes only encouragement or information, no advice (CFD-3).
- No advice in a clip (only encouragement or information) → no text (user: "No text then").
- Recorded every text graphic on the CFD 98 long form: [memory/cfd98-quotes.md](memory/cfd98-quotes.md).

## 2026-11-27 — CFD 99 trims (proposed by agent, user trims by hand)

- 10 clips already on `Editing` V1/A1 in order (R1). All 10 transcribed (the CTC word-timing model had
  to be exported on this machine first).
- Checked CFD 98 clips 1–2 against their transcripts: the user cut through the spoken **topic title**
  (after the intro "สวัสดีครับ" + sound) and started on the next line; cut the ending at the start of
  "ดูคลับ Friday จบแล้วนะคะ". Agent proposed CFD 99 cuts on that basis.
- While the agent was preparing them, the user trimmed clip 01 (src 22.56, agent had 22.23) and
  clip 06 (src 22.00: drops "กับพี่เจนะคะ ค่ะ", starts "ค่ะ พบกับแฟน…"), so a topic title running
  into the host's words is cut past the host's address too. Then: "ill trim it for you first".
- Seen on CFD 98, not yet a rule: many short pauses (0.3–1.4 s) also removed inside each clip. Ask.

## 2026-11-27 — CFD 99 host quotes

- Agent proposed 20 quotes (1–2 per clip) from the trimmed transcript; user: "keep all first then ill check on timeline".
- User put one styled quote Graphic on V3 and exported it as `6. ASSETS61111 - template.mogrt`; agent placed
  38 two-line graphics on V4 (each shown while the host says it, bottom line ≤ 18 characters so it clears the closing mark)
  via `place_text` (fixed the same day to write text into Premiere-made multi-layer templates).
- Open: speaker per quote and exact wording are from the transcript, not checked against audio.

## 2026-11-27 — CFD 99 Shorts and cold-open picks (agent's call; user: "dont ask me … more views")

Times are on the trimmed `Editing` (63:46).
- **Short 1, clip 01** (mistress orders food and asks for the husband as delivery man). Hook 1:50–2:05
  "ผู้หญิงคนนี้ก็จะสั่งกับข้าวบ่อยๆ โดยที่ระบุว่าให้แฟนเราไปส่ง"; advice at end 6:53 "รักเขาก็ได้ค่ะ แต่ไปรักไกลๆ…".
- **Short 2, clip 06** (husband hid HIV, now chats with other men). Hook 37:01–37:23 "ได้รับข่าวร้ายว่าเขาเป็นโรคติดต่อ … เขาเป็น HIV
  แต่เขาไม่ได้บอก"; advice 40:52 "คนเราพลาดได้ แต่ต้องมีสติมากพอ … อย่าพลาดเรื่องเดิมอีกนะคะ".
- **Short 3, clip 07** (said yes to husband having a child with another woman, thinking it was a joke). Hook 41:57–42:12
  "อยากมีลูก โดยการไปมีอะไรกับผู้หญิง ซึ่งเราคิดว่าเขาเล่นๆ เราก็เลยตอบตกลง"; advice 45:34 "โหมดเสียใจ พี่เข้าใจ แต่ต้องมีโหมดตั้งสติ".
- **Long-form cold open, clip 10** (8 months pregnant, left at 7 months after 17 years), about 19 s, caller then host:
  58:20–58:28 "หนูท้องตอนนี้ 8 เดือนค่ะ โดนแฟนทิ้งตอน 7 เดือนค่ะ"; 1:01:50–1:01:57 "ผู้หญิงคนนั้นก็เคยส่งข้อความมาหาเราว่า
  อยู่นิ่งๆ ให้สมกับที่โดนทิ้งหน่อย"; 1:02:05–1:02:10 host "พี่ว่าผู้หญิงคนนั้นก็ไม่ได้ดูมีความสุขหรอก ถ้ามีความสุขจริง
  ไม่มานั่งส่งข้อความหาหนูหรอก". A different clip from the Shorts so the long form doesn't repeat them.
- Runners-up: clip 10 as a Short (if it replaces one), clip 03 (conference call with the mistress).

## 2026-11-27 — CFD 99 `Shorts` sequence built (user: "create new sq call Shorts, put them there", "all in one", "just plain short, no other assets")

- New sequence `Shorts`, 1080x1920 at **50 fps** (CFD 98 Shorts exports are 1080x1920 50 fps; Premiere's stock 9:16 preset is
  30 fps, so a 50 fps copy of it was used). The 3 Shorts sit back to back with a gap: Short 1 at 0–57.3 s, Short 2 at
  62–124.1 s, Short 3 at 130–185.0 s. Footage and sound only, on V1/A1: no quote graphics, frame PNG or titles.
- Each Short is a cut from `Editing`: the caller's hook first, then the story in order, the host's advice last.
  Short 1 (clip 01): hook 115.1, setup 0–20.1, host reaction + crash 134.9–152.0, chat 224.4, advice 413.6–419.7.
  Short 2 (clip 06): hook 2220.0 + 2235.7, background 1938.2, not infected 2246.9, chats with men 2276.2 and 2328.3,
  advice 2449.9–2458.7. Short 3 (clip 07): hook 2517.7, 16 years 2459.8, trying for a child 2478.7, the twist 2541.5,
  stay or go 2566.7, "just wants a child" 2586.4, host 2671.1, advice 2734.6–2743.4 (Editing seconds).
- Not reframed (CFD-R7): the 16:9 picture sits at 100 % in the 9:16 frame, with empty space above and below and the
  outer hosts cut off at the sides. No subtitles (CFD-R8) and no advice text (CFD-R9) yet. Clip 07's V2 punch-in on
  `Editing` was not carried over (the plain source is on V1); Short 1 kept `Editing`'s V1/A1 clip effects (it was
  pasted), Shorts 2 and 3 were placed from the source files without them.

## 2026-11-27 — CFD 99 cold-open caller titles (pink)

- User built the cold open on `Editing` 0–16.06 (6 pieces of clip 06), marked it In/Out, put a pink sample title on V5
  (CFD 98 text) and asked: transcribe the marked span, put the text in the titles; host = blue, caller = pink.
- All 6 pieces are the caller → 5 pink titles on V5 (0–4.76, 4.76–8.22, 8.22–11.84, 11.84–14.52, 14.52–16.06),
  placed from `6. ASSETS\20261111 - template.mogrt` with `place_text` `styles` fill #FF37F3 / stroke #FFDEFD on all
  4 layers (the user's pink is a different layout, so it was matched on screen, not copied). Vector Motion scale 82;
  position (0.6556, 0.315) on the close-up, (0.6556, 0.145) on the wide shots so it clears the caller's head.
  User's sample title removed.
- Wording: the engine's text corrected by 3 other models (pathumma-large-v3, typhoon-large-v3, whisper-th-medium):
  กว่าเขา→ของเขา, เห็นคุย→แอบคุย, ในขณะที่เราก็รีบ→ทั้งๆ ที่เรากับลูก, เจ๊ข้อลูก→เจคลอดลูก (her name is เจ);
  dropped fillers นะคะ, อ่ะเนาะ, ปุ๊บ, อะค่ะ. Not checked by ear.

## 2026-11-27 — CFD 99 Short 1 subtitles

- User reframed Short 1 on `Shorts` (In/Out 0–59.16, recut into 16 pieces): V1 = whole 16:9 frame, V2 = copy punched in
  on the speaker (Motion scale 374 panned left/right on one person, 241–246 centred on wider moments), V5 = `guideline.png`
  (`F:\Me\1.All Pr&Ae\3-AnyMind\Project Atime\CFD SUBTITLE\`): 50% white with a clear safe window x 196–875, y 191–1347.
  Subtitle style: caption style **CFD SUBTITLE** (`CFD SUBTITLE.prtextstyle`, first in the caption Style list).
- Agent transcribed the marked span from clip 01's words, cross-checked with pathumma/typhoon large-v3
  (ปฏิเหตุ→อุบัติเหตุ, บอ กรัก→บอกรัก, +อีก after แชท; fillers dropped), 36 one-line cues (≤ ~24 chars fits the box),
  `CutDeck\Short 1.srt`, placed by `srt_subtitles` (style 1), first as 36 Graphics on V10.
- User: don't upgrade to Graphics, they recolour subtitles per speaker. Graphics removed; placed again with
  `upgrade: false` → 36 captions on caption track C3 (CFD SUBTITLE), inside the safe window. **Rule for CFD Shorts:
  subtitles stay captions.** Keep SRT times on the 30 fps grid too (e.g. 59.10 not 59.12) or edges slip a frame.
- Speaker words not checked by ear.

## 2026-11-27 — CFD 99 Shorts 2–3 subtitles (captions)

- User recoloured Short 1's captions per speaker (caller purple, host cyan) and re-timed some. **Never clear or
  upgrade captions the agent did not place** — the agent's clear step upgraded them; the user undid it in History.
- User: "text in the guide line, 2 lines is fine" → lines ≤ 19 characters (≈630 px of the 680 px window), 2 lines max.
- Shorts 2 (clip 06, 119.16–171.24) and 3 (clip 07, 215.62–270.38) transcribed from the clip words, cross-checked with
  pathumma/typhoon large-v3; 49 captions on a new caption track C4 (CFD SUBTITLE), `CutDeck\Shorts 2-3.srt`.
  Unsure: Short 3 230.5 "อยู่กับแฟนมา 16 ปี" (models disagree), Short 2 name "คิม"; "พี่อ้อย พี่ชอบ" (130.9–131.8) left out.
- 2-line captions: second line sits on the guide's bottom edge (~y 1320–1350); raise the track's captions by hand.
- Shorts 2–3 not reframed yet (user reframes).

## 2026-11-27 — CFD 99 Shorts 2–3 reframe, guide fit, export D1

- Guide fit: two-line captions touch the guide's bottom edge. The user's rule: "one line in the main", two lines only if
  too long, both inside the guide. The agent built `CutDeck\Shorts 2-3 one-line.srt` (75 cues ≤19 chars, not placed),
  but the user had already hand-edited C4 (49 → 46 captions, retimed), so they kept their edits and fixed C4 themselves.
- Reframe by the agent (Scale 374 per host, 241 close-up, faces matched to Short 1, Position **keyframes** for mid-clip
  switches, Short 3 on V1) → the user redid it: **V2 video-only copies cut at each switch, no keyframes**, faces centred
  (agent's were slightly left and high), several "who's in frame" picks changed. Short 3 moved to V2 copies.
  User: "on the key frame i dont want that, when i change i cut … if keyframe … if cut, so its complicated".
- "dont forget the guide layer": agent placed disabled `guideline.png` over Shorts 2–3; the user later rebuilt the upper
  tracks (gradient bars, sting, end card per Short).
- Export (user asked): BAS7, In/Out per Short incl. end card → `5. EXPORTS\Short1/2/3_ClubFriday EP.99 D1.mp4`
  (68.00 / 60.20 / 63.82 s, 1080x1920 50 fps). The first try with forward-slash paths exported nothing yet reported ok.
- Learned → memory: [shorts-layout](memory/shorts-layout.md), [shorts-reframe](memory/shorts-reframe.md),
  [shorts-captions](memory/shorts-captions.md), [shorts-export](memory/shorts-export.md); rules R7, R8, R10, R11.
