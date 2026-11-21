# Topic Cut (design, partly built)

Decided with the user 2026-09-30.

## Goal
Turn a finished live-news program feed (host + guests, director already switching cameras)
into one Premiere clip per topic, cut only at scene changes (no jump cuts), with markers.

## Decisions
- Source: single finished program feed. Scene changes are visible cuts in the picture.
- Topic = host question + guest answer(s), until the next host question.
- Host vs guest: add speaker diarization (`token.speaker_id` is reserved and unused today).
  The user marks which voice is the host once per show.
- Snap: in-point to the scene change at or before the host's first word; out-point to the
  first scene change after the last guest word. No scene change near: extend to the next one,
  never cut mid-shot.
- Overlapping speech: keep it, put a marker on it (low ASR confidence or two speakers at once).
- Output: new sequence, one clip per topic, original untouched (same path as Rough Cut).
- Notes: topic list + a short summary of each guest answer, as a markdown file and/or
  Premiere markers (user wants markers at least).

## Slices (each needs its own check before building)
1. Scene detector: ffmpeg `select=gt(scene,T)` -> list of cut times. Check: on a real clip,
   detected cuts match the user's hand-marked cuts; tune T against news graphics/tickers.
2. Diarization: speaker turns, host chosen by the user. Check: turns on a gold clip.
3. Topic builder: turns -> topics (host question opens one). Check: same topics the user
   listed by hand for one real episode.
4. Snapper: topics + scene cuts -> clip in/out. Check: no output edge falls inside a shot.
5. Overlap flags + markers/notes writer.
6. Panel button + helper job, reusing the Rough Cut native path.

## Open
- Need one real episode (video + the user's hand-made topic list) as the gold set.
- Scene threshold and snap tolerance: tune on that episode.

## Update 2026-09-30: findings on the real episode
Episode: `HKS Facebook 290969 Full.mp4` (96.6 min, 1280x720, 25 fps), project
`E:\Me\7.test folder\Copied_20260929 - โหนกระแส\20260929 - โหนกระแส.prproj`, sequence
"topic cutting" = the user's rough draft of topic cuts (38 cut points, timeline = source time).
It is a draft, not exact ground truth.

- Plain whole-frame scene detection (ffmpeg scene>0.15) found 710 changes (7/min); only 10 of
  38 draft cuts fall within 0.5 s of one. Frames show why: the picture has three layouts.
  1. full studio shots (hard camera cuts = real scene changes),
  2. news-clip layout (clip full frame, host in a small window, headline ticker; camera
     switches happen inside the small window and are invisible to whole-frame detection),
  3. bumpers/ads/logo cards (overlays trigger false changes).
- User: a topic starts at the host's question in the studio (with or without a clip).
- So: classify layout (studio / clip / bumper); snap a topic start only to a hard camera cut
  in a full studio shot; never cut inside a clip layout (move to its edge); switches inside the
  small window are not boundaries.

## Revised slices
1. Layout classifier (studio / clip / bumper). Check: frames at the 38 draft cuts and a
   hand-labelled sample are classified correctly.
2. Diarization + host voice (as before).
3. Host-question topic builder.
4. Snapper to studio hard cuts. Check: no cut lands inside a clip layout.
5. Markers/notes; 6. Panel button (as before).

## Update 2026-09-30 (later): built, and where the topic builder is stuck
Built and tested: `cutdeck/topic_layout.py` (clip vs studio, 93.6% on 193 hand labels; misses full-screen
footage), `cutdeck/topic_speakers.py` (host vs other; host 90-150 s 100%, guest-alone 7% host).
Transcribed the episode with the existing engine: `output/live_news/hks.db` (job 1, 2622 cues,
~12 min on the 3070); audio `output/live_news/hks_full.wav`. Host turns: 409 (30% of speech).

Topic builder is NOT built. Three timing rules from host turns were tried against the user's
draft ("topic cutting" sequence, 38 cuts, a rough draft) and all failed:
any host run (26/38 hit, 156 candidates, mostly noise); host run + long guest answer (10-17/38);
last host sentence before a guest answer (5-13/38).
What the transcript shows at the draft cuts: they sit on the host's question wording
(e.g. "ทีนี้คุยกับท่านกิ้งกือสักนิดหนึ่ง" 975 s; "ถ้ารถคุณมีประกันต้องทำอย่างไรครับ" 2098.8 s;
"คือรถที่มันจมน้ำ ซ่อมนี่แพงไหม" 3366 s), or a break announcement (687.7 s).
Next step needs the user's rule (or a clean 10-minute stretch of exact topic boundaries), or a
text-based question detector; do not try a fourth timing rule blind.

## Update 2026-09-30 (end of session): answer key exists
The user reviewed the 31 topic starts Claude picked by reading the transcript (v0), and saved
32 markers in sequence "Footages Copy 01" -> `tests/data/topic_cut_starts_hks290969.json`.
Of the 31 v0 picks: 24 kept within 1.5 s, 6 nudged (1400->1411.3, 2752->2739.8, 2821->2823.4,
3788->3790.6, 4957->4958.6, 5175->5176.8), 1 replaced (3447 -> 3419.2); 1 marker added (3809.0).
Topic starts by MEANING works; by timing/wording rules it did not (see above).
Open: (1) a repeatable judge for "new topic?" (user asked for the simplest way; the markers-review
loop is it for now); (2) place each start at the question's own sentence, then snap to a studio
camera cut (`cutdeck/topic_layout.py`); (3) real razor cuts (no Adobe razor API: overwrite-as-razor,
unproven with nothing removed); markers-only is what is live now.
