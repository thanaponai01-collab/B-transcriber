# Timeline listening: what the cut timeline says, without listening again

Overnight work, 2026-11-22 (from 00:40). Branch `feat/timeline-listen`, PR #117, stacked on
PR #115's branch (`feat/premiere-text-dialogs`) because the panel running in Premiere is that
code (master's helper refuses its `place_text` registration).

## Morning summary

- **The fix:** the agent no longer transcribes a cut timeline. Each source file is transcribed
  once, and its words are mapped through the timeline's clips in exact ticks. A rough cut, a
  copy or a reordered Short is read in about 2 s, and its words never change between reads.
- **New tools:**
  - `premiere_timeline_transcript`: what is said where, plus every cut that lands in sound.
  - `premiere_plan_pieces`: pick the lines for a Short by their words. Each piece's edges go in
    the *source* file's own pauses, and the result is ready for `build_sequence`.
  - `premiere_cut_words`: remove phrases with each cut in the pause, then read the result back to
    check it.
  - `premiere_keep_words`: keep only these phrases on a copy of the rough cut, every track kept.
- **Your failing case now passes.**
  - A reordered 3-piece Short planned by words from a rough cut was built and read back with
    0 cuts in sound and no clipped words.
  - On your own route (copy the rough cut, keep every track), `keep_words` kept two phrases with
    every track intact and 0 cuts in sound.
  - The planner's edges match yours: 23 of 34 within one frame of the edges you cut by ear.
- **The engine is fixed where it hurt cuts.** Thai word *times* were off by up to hundreds of
  ms, both too wide and too narrow. They are now fitted to the audio. Words *text* is unchanged
  (no engine swap without the gold set).
- **Rough Cut** now reuses the stored source transcripts: no ASR pass, the same cuts frame for
  frame. In your order (rough cut first), it transcribes the source file once instead of a
  throwaway WAV, so everything after it is free.
- Everything ran live in your project on scratch copies. Your `editing` sequence was only read.
  Nothing was saved or exported.

## The problem

CutDeck can see and drive Premiere; the weak part is hearing. The usual flow is: rough-cut
first, then transcribe. But transcription takes a media *file*, so the agent transcribed either
the source file (whose times don't match the cut timeline) or a render or copy of the cut timeline
(a new file: slow, and the transcript changes from run to run). Either way the agent did not
know exactly where each word sits on the timeline, and cuts landed wrong.

Root causes, each measured:
1. **No timeline coordinates.** Nothing mapped a transcript onto a sequence's clips.
   `transcribe` takes one file. The Rough Cut's own ASR transcribed a throwaway WAV whose sha256
   never repeats, so even its cache never hit.
2. **Re-listening changes the words.** A fresh transcript of a 6-min rough cut's own audio agreed
   with the source transcript on only 83% of characters (85% on a late window of the full cut).
   Example: "สวัสดีครับ" came back as "good afternoon". Context is lost at every cut.
3. **Engine word times are loose, in both directions.** faster-whisper's Thai word spans run
   into pauses (a 1.0 s "ครับ"), and they also start late and end early. On the 96-min source, a
   quarter of the words after a pause started 100+ ms after their sound began (256 of 1,017;
   p90 200 ms), and 275 of 1,058 ended 100+ ms early. A cut placed at an engine word edge clips
   the first syllable. That is the 1RaceClub "รัส" case (log: "ASR word times ran ~0.1 s off").

## The solution

**Transcribe each source file once, then map it through the clip list.** A cut timeline is a
list of pieces of source files, so a word's timeline position is arithmetic:
`timeline = clip.start + (source - clip.source_in) / speed`, exact in Premiere ticks.

### `premiere_timeline_transcript` (helper command `timeline_transcript`, `cutdeck/timeline_transcript.py`)
- Reads the sequence (`read_timeline`) and takes the clips of one audio track (default: the
  first un-muted track with clips; `track: "A3"` to choose).
- For each clip's source file it finds the newest finished transcript in the shared store, by
  sha256 and from any engine (`store.latest_transcript_job`). Source files never transcribed are
  listed in `missing`: run `transcribe(media_path)` once each, then call again.
- `lines`: the engine's phrase cues as the timeline plays them (`tc`, `start_s/end_s`,
  `start_ticks/end_ticks`, `text`, `clip` id, `src_s`). A cue a cut runs through becomes two
  lines; a cut-away part is gone.
- `query`: finds a phrase on the timeline, ignoring spaces and punctuation, also across a cut.
  `whole_words` says whether it starts and ends on word edges.
- `cuts_in_sound`: every clip In/Out with audible sound within 20 ms of the cut. It carries the
  word it cuts (`word: null` means sound no word covers: an onset, a laugh, music), how much of
  the word is lost, `nearest_quiet_ms` (the shift that puts the cut in quiet) and a `severity`:
  - `tail`: quiet within 10 ms, the faint end of a fade.
  - `sound`: the cut is in the sound.
- `full_path`: a JSON file with every line and word.
- Speed changes are mapped. Premiere reports a sped-up clip's In/Out divided by its speed, a new
  row in PREMIERE_FACTS. Reversed clips, disabled clips and clips with no media (nested
  sequences) are listed in `skipped`.
- `untranscribed`: speech the VAD heard but no cue covers (the engine dropped it). It is mapped
  onto the timeline so an agent does not mistake it for a pause. The 96-min source has 26 such
  spans, 21.5 s in all.
- `from_ticks` / `to_ticks` narrow `lines`, `cuts_in_sound` and `untranscribed` alike.
- `sources[].note` warns when a file has several audio streams. `warnings` flags a track whose
  clips look like a later stream (Premiere lays each stream on its own track). Everything here,
  the Rough Cut included, reads the first stream (see Gaps).

### Offline: a saved project, no Premiere
`python -m cutdeck.timeline_transcript --prproj <file> --sequence <name> [--track A1] [--query ...] [--json]`
reads a saved sequence through `prproj_reader` (speed is taken from source over timeline length,
fps defaults to 30) and prints the same timeline transcript.

### Word times fitted to the audio (`tighten`)
Each source's 10 ms level envelope is decoded once, streamed, and cached by sha256 in
`output/timeline_transcripts/levels/`. Sound means the Rough Cut sound guard's rule: 6 dB above
the file's floor (the 5th-percentile level, clamped to −65..−35 dB). Each word is:
1. pulled in to the first and last audible window inside the engine's span;
2. where an edge borders a pause, grown out through continuous sound, at most 400 ms and never
   into a neighbouring word.

Measured on four sources (words after a pause of 150+ ms; "late" means the sound began 100+ ms
before the engine's start, "early" means it went on 100+ ms past the engine's end):

| source (store job) | late starts, before → after | early ends, before → after |
|---|---|---|
| `10-40-52.mp4` mic (79) | 256/1,017 → 6/1,058 | 277 → 5 |
| `10-40-53-cam.mp4` camera (81) | 275/1,034 → 9/1,045 | 298 → 2 |
| `10-40-51.mp4` (82) | 247/991 → 4/1,042 | 264 → 3 |
| `07-07-37.mp4` mic, 1RaceClub FP3 (83) | 214/948 → 6/975 | 212 → 5 |

What remains is sound beyond the 400 ms reach.

### `premiere_cut_words` (helper command `cut_words`, `cutdeck/word_cut.py`)
- `remove`: `[{"text": "...", "occurrence": n}]` or `[{"from_ticks", "to_ticks"}]`.
- Each cut runs from the pause before the words to the pause after them, leaving `keep_ms`
  (default 250, never more than was there) of pause at the join. It then moves to the nearest
  frame where the audio is quiet. When the words touch, there is no quiet frame: the cut stays on
  the word boundary and `no_quiet` gives that side's dB above the sound threshold. (Moving to the
  quietest nearby frame was tried live: it left part of a removed filler behind.)
- A phrase found only inside a longer word is refused, not cut through.
- It makes `result_name` with `cut_copy` (the source is never edited), then reads the result back
  and returns:
  - `checks`: how many times each phrase is said, before and after;
  - `joins`: the words either side of each join;
  - `new_cuts_in_sound`: any new cut that has sound at it.

### `premiere_plan_pieces` (helper command `plan_pieces`, `word_cut.plan_pieces`): placing a Short's edges
- `keep`: the phrases to play, in order, found on any timeline (usually the rough cut).
- Each piece's In/Out is placed in the **source file's** pauses around its words, using the
  source's full word list and levels: 60 ms of pause (`pad_ms`) and any wordless sound touching the
  phrase, then the nearest quiet frame. A
  rough cut has removed most pauses; the source still has them.
- Returns `items` for `premiere_build_sequence` (back to back on V1/A1) and `pieces`, with
  `no_quiet` when a phrase has no pause in the source (it is mid-sentence: keep whole sentences).
- Edits nothing. Read the built Short back with `premiere_timeline_transcript`.

### `premiere_keep_words` (helper command `keep_words`): cut a Short from a synced rough cut, every track kept
- Your route: copy the rough cut and work from there, because a Short rebuilt from items lost audio
  tracks.
- `keep` lists the phrases. Their spans are placed as in `plan_pieces` (in the source's pauses,
  never past their own clip on this timeline), and everything else is cut with `cut_copy`, so
  every video and audio track and layer stays.
- The copy is read back (`lines`, `cuts_in_sound`). Reorder afterwards.

### Piece edges are calibrated on your own cut
The planner was run offline on each of the 17 pieces of your cut of the Max Short (saved v4), and
each of its 34 In/Out edges was compared with the one you chose by ear.
- **Pad:** 30, 60 and 90 ms of pause score about the same (21, 22 and 19 of 34 edges within a
  frame). 120 ms and more is clearly worse (7 within a frame). The default is now 60 ms.
- **Wordless sound:** in 4 pieces you kept 200-530 ms of audible sound that has no word (a breath,
  a laugh, a reaction, or a word the engine missed). The planner had dropped it. A piece now takes
  along wordless sound that touches it: at most 100 ms of quiet in between, up to 600 ms, never
  into a neighbouring word.
- **Result:** 23 of 34 edges within one frame of yours, 25 within 100 ms, and 2 off by more than
  200 ms. Without the wordless rule it was 22, 23 and 5.
- **Caveat:** these values were tuned and scored on the same 34 edges of one Short. A second
  hand-cut Short would confirm them.
- Where you cut mid-flow on purpose (no pause), the planner reports `no_quiet`.

### Rough Cut speech protection reuses the source transcripts (`rough_cut._mapped_transcript`)
With speech protection on, if every reference-track source has a stored transcript, its words
are mapped onto the range instead of transcribing the WAV. A source with no transcript is
transcribed whole first when the cut uses at least half of it; otherwise it falls back to the old
path. See docs/rough-cut.md.

### Agents are told
The MCP server's instructions now say: to know what a sequence says and where, call
`premiere_timeline_transcript`, not `transcribe` on a render; remove words with
`premiere_cut_words`.

## Evidence (live, Premiere 27.0, your project open)

Run folders hold every request and result:
- `output/verify-cutdeck/runs/20261122-004515-timeline-listen/`
- `output/verify-cutdeck/runs/20261122-013033-timeline-listen-final/` (re-proofs, two sources, rough cut first)
- `output/verify-cutdeck/runs/20261122-015758-short-placed/` (`plan_pieces` Short and final `cut_words`)

| Check | Result |
|---|---|
| Transcribe the 96-min source `2026-11-21 10-40-52.mp4` | 224 s on the RTX 3070: 1,483 cues, 8,523 words (store job 79) |
| `timeline_transcript` on `editing` (1 clip) | 1,481 lines on the timeline, no new transcription |
| 6-min scratch copy, rough cut (aggressive, speech protection) | 119 cuts, 223 s removed |
| ... `timeline_transcript` on it | 6 s the first time (decodes the level envelope), then about 1 s |
| ... edges reported as cut "inside a word", by raw engine word times | 105 of 238: the engine-times problem |
| ... edges with audible sound at the cut (the honest count) | 29 of 238: 21 tails (≤10 ms from quiet), 8 in sound, 5 of them inside a word |
| ... a fresh transcript of that rough cut's own audio | cues sit a median **3 ms** from the mapped positions (p10 −117, p90 +363: the fresh transcript's loose times); 83% text agreement |
| Rough Cut again, now from the mapped transcripts | **the same 119 cut spans, frame for frame**; 15 s, no ASR pass |
| Full 96-min copy, rough cut | analysis 1 min 55 s with no ASR (1,483 lines mapped); 1,652 cuts applied in 12 s; 52.5 min removed |
| ... `timeline_transcript` on the 1,653-clip result | **about 2 s** |
| ... edges with sound at the cut | 239 of 3,306: 185 tails, 54 in sound, all within 42 ms of quiet (mostly 12-22 ms, under a frame). The Rough Cut's edges are sound |
| ... fresh transcript of timeline 2,200-2,400 s (source around 80-90 min) | median offset **−13 ms**; 85% text agreement. No drift late in the file; ffprobe shows start_time 0 on every stream |
| Speed 200% and 50% on a 10 s scratch | every line lands at (source − 112 s) / speed |
| Reordered Short built with `build_sequence` (3 pieces, new order) | read back in the new order at the exact positions (0.143 / 1.357 / 2.763 s); the 4 cuts into neighbouring words were flagged |
| Both rough cuts re-analysed offline on the final code (fitted words) | 119/119 and 1,652/1,652 cut spans, identical to the first runs |
| `cut_words` (final code): remove all three "เอ่อ" fillers | said 3 → 0; joins read naturally; **no new cut in sound** |
| `plan_pieces` from the rough cut, 3 whole utterances in a new order, then `build_sequence` and `timeline_transcript` | **0 cuts in sound (0 tails), no clipped words**, the three lines in the new order. Planning on the rough cut's own pauses had given a one-frame sliver of a neighbouring clip, which is why edges are placed in the source |
| `cut_words` (final code): remove "เดี๋ยวตื่นแล้วหรอ" and "คอลลีฟายกัน" from the rough cut | said 1 → 0 each and the joins read naturally, but the rough cut had already removed every pause around them (words touching, 0 ms). So there is no clean place: cuts at the word boundaries, and the cuts in sound are reported (`no_quiet`, `new_cuts_in_sound`). An earlier, weaker check had passed this case as clean |
| Two sources: the mic file (4 streams, which landed on A1-A4) and the 7 GB camera file placed on V2/A5 | first read of A5: `missing` named the camera file, 9 s (hashing 7 GB included). The helper's own `transcribe` job took 410 s. Re-read: A5 came from the camera transcript (job 81) and A1/A2 from the mic transcript (job 79); A2 warns that it looks like stream 2 |
| Your order, rough cut first: a never-transcribed 96-min source (`10-40-51.mp4` on A5), Rough Cut with speech protection | the job transcribed the source once (store job 82) instead of a WAV, then mapped it: 1,644 cuts, 8 min 40 s in all. `timeline_transcript` on that track straight after: nothing missing, 0 s of new listening |
| Your real work, read offline from `20260130 RENAME template - 2.prproj` after one transcription of `07-07-37.mp4` (196 s, job 83) | `2026-11-21 07-07-37_Synced — CutDeck 94fd4bb9`: 1,091 clips, 1,336 lines; 27 of 2,182 edges in sound (95 tails). `TT max vs everyone v4 (Claude)`: every line of the agent's v4 and of your own cut, in order |
| Calibration against your ear: your own cut of the Max Short (92.7-135.1 s) | 3 of its edges are "in sound": one inside "เฮ้ย", where your log says you cut the repeated words mid-flow on purpose, and one on the tail of the last "ครับ" (the agent's v4 did the same). So `cuts_in_sound` is a list to review, not a list of errors. The per-word `clipped` flag fired 27 times, mostly at quiet edges, so it is now gated by the audio too (27 → 4) |
| `keep_words` on `listen two sources (scratch)` (mic on A1-A4, camera on V2/A5), keeping 2 phrases | a copy with **every track kept** (V1, V2, A1-A5, 2 clips each, ending at 2.27 s); reads back exactly the 2 phrases; **0 cuts in sound** |
| Coverage of the source transcript | 26 spans (21.5 s) of speech with no cue, now listed as `untranscribed` |

Tests:
- `python -m pytest tests/test_cutdeck_timeline_transcript.py tests/test_cutdeck_word_cut.py` covers
  the mapping, speed, tightening and growth, audio-gated edges, late onsets, the cut planner,
  quiet snapping, whole-word matches and the rough-cut mapping.
- Mutation checks, each turning at least one test red, then restored:
  - the mapping without `- clip.in_`;
  - edge growth off (`REACH_MS = 0`);
  - the audible-edge gate off;
  - unworded sound dropped;
  - quiet snapping off;
  - speed ignored, in the mapping and in the scaled In/Out;
  - corrections off;
  - the cut planner cutting at word edges.
- The full suite has 1,325 passed. The only failures are 8 in `tests/test_text_box.py`, which also
  fail on the base branch: the `uharfbuzz` module is not installed here.
- `node --test tests/*.cjs`: 795 passed. `scripts/check_rough_cut.py` passes.

## Independent code review (02:15)

A reviewer subagent read the diff cold. It found 10 issues (4 confirmed by running them) and
I fixed 8, each with a test:
- `tighten` rounded every edge to the 10 ms grid (it now keeps exact times where an edge does
  not move);
- `plan_pieces` gave Out before In for a phrase that crosses a cut (now refused);
- a zero-length last word was left out of a removal;
- the range filter lost an edge sitting exactly on `from_ticks`;
- a through-edit counted as two cuts;
- concurrent cache writes could crash, and a half-written cache was never rebuilt;
- one undecodable source failed the whole command;
- a pause shorter than a frame always cut into the kept word.

After the fixes, the rough cut's cut list is still identical, and the Short still has 0 cuts in sound.

Left as is:
- A Rough Cut with speech protection hashes each source once even when it won't use its
  transcript (a cost, not a wrong result).
- A cut made from several sources records only the first source's transcript job id.

## State you are left in

- The checkout is on `feat/timeline-listen`; it was on `docs/projects-layout`. The helper runs
  this branch's code (a superset of PR #115, which the panel needs).
- A helper restarted from master or `docs/projects-layout` will refuse the panel's `place_text`
  registration, because that is PR #115 code.
- Premiere is back on `editing`. Nothing was saved or exported.

## Gaps and limits (please read)

- **Your OBS files' extra streams are harmless today.** In every footage file of 20261121, stream 2
  duplicates stream 1 and streams 3-4 are silent. Per-stream transcription was not built.
- **Untranscribed speech is listed, not filled in.** Re-decoding 12 of the 26 gaps on their own
  gave text for all 12: some plausible ("เตรียม", "ฮ่าๆ", "บ๊ายบาย"), some invented ("สล็อตออนไลน์",
  a classic Whisper hallucination on short clips). Filling them in automatically would put invented
  words on the timeline.
- **A name glossary is not the fix for names.** Tried tonight on your F1 audio, through both the
  decoder prompt and hotwords. Names came out right ("รัสเซล" 1 → 14), but the model invented
  name lists in place of real speech and dropped 28-30% of the text. Even a 3-name list invented
  "แม็คลาเรน" 17 times and dropped 14% (details in docs/ENGINES.md). The flywheel's learned bias
  terms go through the same channel, so the same risk grows as corrections accumulate.
  Fix names after decoding instead (a reviewed substitution list, or SubtitleDesk corrections
  through the flywheel).
- **Text accuracy is unchanged.** This work fixes *where* words are, not *what* they are.
  `biodatlab whisper-th-medium` still mishears casual speech and English phrases. Any engine
  change needs the gold set (still the #1 blocker).
- **Corrections are applied, but approximately.** A cue corrected in SubtitleDesk or the web
  editor replaces that cue's words, and its lines say `corrected: true`. When the corrected text
  has a different word count, its word times are shared by characters, so word positions inside
  that cue are estimates. No corrections exist in the store yet, so this is unit-tested only.
- **"Any finished transcript" is accepted.** The newest one for the file's sha256 is used,
  whatever the engine, settings or age.
- **One audio track per call.** On a synced multicam with the voice on A3, pass `track: "A3"`.
- **First audio stream only.** Multi-stream files (OBS) are read from their first stream, and
  UXP cannot say which stream a Premiere clip plays. Placing your 4-stream 10-40-52 file put
  streams 1-4 on **A1-A4** (live). Streams 1 and 2 are identical (the voice) and 3-4 are silent,
  so it is fine. In a file with mic and desktop on separate streams, A2's words would be wrong.
  The tool warns (`warnings`, `sources[].note`). The Rough Cut has the same blind spot: choose
  A2 as Reference Audio and it still hears stream 1.
- **Constant background sound hides pauses.** The sound rule is loudness against the file's
  floor, so under a music bed or game audio there is no quiet frame. `cuts_in_sound` then lists
  most edges, and `cut_words` reports `no_quiet`.
- **Short edges are placed only for whole utterances.** A phrase that sits mid-sentence has no
  pause even in the source, so its piece edge is in speech (reported as `no_quiet`).
- **Cutting inside continuous speech is never clean.** Run `cut_words` on a timeline that still
  has its pauses (before the rough cut, or the source sequence) when you can.
- **Reversed clips are skipped**, and so are nested sequences (no media file).
- **Joins are frame-accurate, not sample-accurate.** A tight join (words touching) can be up to
  one frame (33 ms) off.
- **The cross-checks share `audio_extract`'s assumptions** (ffmpeg's first stream, its timing),
  so they cannot catch a stream mismatch.
- **Long sources are transcribed whole.** A 3-hour stream takes about 7-8 min once, even if only
  10 minutes are used. After that it is free.
- **The tools need the panel.** The CutDeck panel must be connected to the helper. After a helper
  restart it reconnects by itself, but only if the panel's code matches (see the PR #115 note above).

## Follow-ups

- When PR #116 (projects layout) merges, `projects/1raceclub/shorts-rules.md` step 1 ("Transcribe
  the rough cut") should read "Read the rough cut with `premiere_timeline_transcript`".
- A stream choice for multi-stream sources: the transcript, the levels and the Rough Cut all
  read the first audio stream.
- Text accuracy: build the gold set, then try an engine change through the harness.

## Scratch sequences made tonight (yours to delete; the project was not saved)

- `listen test A (scratch)` and `listen test A (scratch) — CutDeck 86551c23` (a 6-min copy and its rough cut)
- `listen test A words (scratch)` and `listen test A no-er (scratch)` (`cut_words` results)
- `listen speed (scratch)` (the speed probe)
- `listen full (scratch)` and `listen full (scratch) — CutDeck 4002a9e8` (the full-length rough cut)
- `listen short (scratch)` (the reordered Short)
- `listen test A words v2 (scratch)`, `listen test A words v3 (scratch)`, `listen test A no-er v2 (scratch)`, `listen test A no-er v3 (scratch)` and `listen test A no-er v4 (scratch)` (`cut_words` reruns; v4 is the final code)
- `listen short placed (scratch)` (the Short built from `plan_pieces`)
- `listen two sources (scratch)` (mic file on A1-A4, camera file on V2/A5)
- `listen rough-first (scratch)` (the never-transcribed source on A5; its rough cut was analysed but not applied)
