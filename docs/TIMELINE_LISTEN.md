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
  - The planner's 60 ms default was checked against your cuts. Most of their edges turned out to
    be the Rough Cut's own; on the two cuts with no rough cut (both Gillette videos) it beats the old
    120 ms.
- **The engine is fixed where it hurt cuts.**
  - Thai word *times* were off by up to hundreds of ms, both too wide and too narrow. They are
    now fitted to the audio.
  - **English audio** used to come out as invented Thai, because Thai was hard-coded. It now
    transcribes correctly with `language="en"`, or `"auto"` (10 of 10 unseen files right). Your
    synced F1 feeds are English.
  - Thai text accuracy is otherwise unchanged (no engine swap without the gold set). A name
    glossary is not the answer: it makes the model invent speech.
- **Rough Cut** now reuses the stored source transcripts: no ASR pass, the same cuts frame for
  frame. In your order (rough cut first), it transcribes the source file once instead of a
  throwaway WAV, so everything after it is free.
- Everything ran live in your project on scratch copies. Your `editing` sequence was only read.
  Nothing was exported, and nothing was saved that night (a later check saved the project once:
  see "State you are left in").

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
   p90 200 ms), and 277 of 1,017 ended 100+ ms early. A cut placed at an engine word edge clips
   the first syllable. That is the 1RaceClub "รัส" case (log: "ASR word times ran ~0.1 s off").

## The solution

**Transcribe each source file once, then map it through the clip list.** A cut timeline is a
list of pieces of source files, so a word's timeline position is arithmetic:
`timeline = clip.start + (source - clip.source_in) / speed`, exact in Premiere ticks.

### `premiere_timeline_transcript` (helper command `timeline_transcript`, `cutdeck/timeline_transcript.py`)
- Reads the sequence (`read_timeline`) and takes the clips of one audio track (default: the
  first un-muted track with clips; `track: "A3"` to choose).
- For each clip's source file it finds the finished transcript in the shared store that
  `transcribe` last returned (new or cached; else the newest), by sha256 and from any engine
  (`store.latest_transcript_job`, `job.chosen_at`). A file with transcripts in both Thai and English
  gets a `warnings` line naming the other one and the call that switches to it. Source files never transcribed are
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
  source's full word list and levels: 60 ms of pause (`pad_ms`), then the nearest quiet frame.
  `wordless_ms` (off by default) also takes along a laugh or breath that touches the phrase. A
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

### Piece edges, checked against your own cuts
`scripts/timeline_listen/calibrate_edges.py` runs the planner offline on each piece of a saved cut
and compares its In/Out with the cut's own. Pieces are deduplicated by source span. It also
reports which of the cut's edges sit within a frame of an edge of that project's CutDeck rough cut.

**Most of your edges are the Rough Cut's edges, not edges you placed by ear:** 30 of 34 on the
Max Short, 97 of 120 on `tt`, 1,858 of 1,888 on `yt`. The aggressive Rough Cut itself pads 60/40 ms
(docs/rough-cut.md), so agreement on those cuts mostly measures agreement with the Rough Cut.
**Two cuts are independent:** the Gillette review (`edioting`, 46 edges) and the Gillette Vegas
lecture's `tt` (20261116, 104 edges). Neither project has a CutDeck rough cut, and 0 of their
edges sit on one. That you placed these by hand is an assumption.

Final code, all four cuts (within 1 frame / within 100 ms / off by more than 200 ms):

| cut | edges | pad 120 | **pad 60 (default)** | pad 60 + wordless 600 ms |
|---|---|---|---|---|
| Gillette review, independent | 46 | 7 / 23 / 6 | **16 / 34 / 6** | 12 / 33 / 6 |
| Gillette Vegas lecture `tt` (20261116), independent | 104 | 18 / 48 / 25 | **31 / 63 / 25** | 24 / 62 / 26 |
| Max Short (30 of 34 on rough-cut edges) | 34 | 8 / 23 / 5 | 22 / 23 / 5 | 24 / 25 / 2 |
| tiw `tt` (97 of 120 on rough-cut edges) | 120 | 14 / 84 / 16 | 70 / 87 / 16 | 66 / 85 / 18 |
| tiw `yt` (1,858 of 1,888 on rough-cut edges) | 1,888 | 218 / 1,383 / 270 | 1,241 / 1,439 / 271 | 1,195 / 1,420 / 272 |

- **Pad 60 ms** is the default. It is better on both independent cuts, and it agrees with the Rough
  Cut's own edges on the others. On the few non-rough-cut edges of `tt` (23) and `yt` (30), 60 and
  120 tie.
- **Wordless sound** (a laugh or breath touching the phrase) is worse on both independent cuts. It is
  **off by default** (`wordless_ms`).
- **The big misses are not an editing habit.** Most sit on rough-cut edges where the audio is quiet
  (sound at the edge: 1 of 16 on `tt`, 22 of 271 on `yt`). There the engine's word spans a pause
  that the Rough Cut cut into. On the two cuts with no rough cut, the misses do have sound at your
  edge (4 of 6; 21 of 25): there the cut is inside a word, presumably on purpose, and the planner,
  which keeps whole words, can't match it. A reading I gave earlier tonight ("you trim
  dragged syllables") did not survive this check and is withdrawn.

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
| `cut_words` (final code, after both reviews): remove all three "เอ่อ" fillers | said 3 → 0; joins read naturally; **no new cut in sound** |
| `plan_pieces` from the rough cut, 3 whole utterances in a new order, then `build_sequence` and `timeline_transcript` | **0 cuts in sound (0 tails), no clipped words**, the three lines in the new order. Planning on the rough cut's own pauses had given a one-frame sliver of a neighbouring clip, which is why edges are placed in the source |
| `cut_words` (final code): remove "เดี๋ยวตื่นแล้วหรอ" and "คอลลีฟายกัน" from the rough cut | said 1 → 0 each and the joins read naturally, but the rough cut had already removed every pause around them (words touching, 0 ms). So there is no clean place: cuts at the word boundaries, and the cuts in sound are reported (`no_quiet`, `new_cuts_in_sound`). An earlier, weaker check had passed this case as clean |
| Two sources: the mic file (4 streams, which landed on A1-A4) and the 7 GB camera file placed on V2/A5 | first read of A5: `missing` named the camera file, 9 s (hashing 7 GB included). The helper's own `transcribe` job took 410 s. Re-read: A5 came from the camera transcript (job 81) and A1/A2 from the mic transcript (job 79); A2 warns that it looks like stream 2 |
| Your order, rough cut first: a never-transcribed 96-min source (`10-40-51.mp4` on A5), Rough Cut with speech protection | the job transcribed the source once (store job 82) instead of a WAV, then mapped it: 1,644 cuts, 8 min 40 s in all. `timeline_transcript` on that track straight after: nothing missing, 0 s of new listening |
| Your real work, read offline from `20260130 RENAME template - 2.prproj` after one transcription of `07-07-37.mp4` (196 s, job 83) | `2026-11-21 07-07-37_Synced — CutDeck 94fd4bb9`: 1,091 clips, 1,336 lines; 122 of 2,182 edges with sound at the cut (27 `sound`, 95 tails). `TT max vs everyone v4 (Claude)`: every line of the agent's v4 and of your own cut, in order |
| Your own cut of the Max Short (92.7-135.1 s); most of its edges turned out to be the Rough Cut's (see the calibration section) | 3 of its edges are "in sound": one inside "เฮ้ย", where your log says you cut the repeated words mid-flow on purpose, and one on the tail of the last "ครับ" (the agent's v4 did the same). So `cuts_in_sound` is a list to review, not a list of errors. The per-word `clipped` flag fired 27 times, mostly at quiet edges, so it is now gated by the audio too (27 → 4) |
| `keep_words` on `listen two sources (scratch)` (mic on A1-A4, camera on V2/A5), keeping 2 phrases | a copy with **every track kept** (V1, V2, A1-A5, 2 clips each, ending at 2.27 s); reads back exactly the 2 phrases; **0 cuts in sound** |
| `keep_words` on a rough cut of that multi-track scratch: two spans of 3-4 lines, each crossing rough-cut joins | every track kept (V1, V2, A1-A5, ending at 8.03 s); both spans read back whole. 2 cuts in sound, both expected: one is an inner rough-cut join (the Rough Cut's own edge), one is a span end where the speech runs straight into a laugh (`no_quiet` warned) |
| **Your whole route, end to end:** rough cut (from cached transcripts) → `keep_words` (two spans, every track) → reorder (`build_sequence` into: clone far, lift, clone back, lift) → `timeline_transcript` | the spans play swapped on all 7 tracks (8.03 s); the read-back shows the new order; the new join added no cut in sound (the same 2 source edges as before, moved) |
| Final planner, the Short rebuilt | 0 cuts in sound; the three lines in the new order |
| Through a real MCP client (stdio, `mcp` ClientSession → `python -m cutdeck.mcp_server`) | the four tools are listed; `premiere_timeline_transcript` (125 lines, phrase found at 00:00:04:06) and `premiere_plan_pieces` (same piece as the direct call) answer |
| English source, re-transcribed with `language="en"` (154 s, store job 87), then `timeline_transcript` on the 50 fps scratch | the newest transcript is used (job 87 then; job 89, the `auto` run with identical text, since); the lines read as the broadcast ("So you want to take the gear early because you've got downforce on the car and it helps you slow down."), where before they were invented Thai |
| Coverage of the source transcript | 26 spans (21.5 s) of speech with no cue, now listed as `untranscribed` |

Tests:
- `python -m pytest tests/test_cutdeck_timeline_transcript.py tests/test_cutdeck_word_cut.py` covers
  the mapping, speed, tightening and growth, audio-gated edges, late onsets, the cut planner,
  quiet snapping, whole-word matches and the rough-cut mapping.
- Mutation checks, each turning at least one test red, then restored:
  - the mapping without `- clip.in_`;
  - the sound threshold in `tighten` widened;
  - edge growth off (`REACH_MS = 0`);
  - the audible-edge gate off;
  - unworded sound dropped;
  - quiet snapping off;
  - speed ignored, in the mapping and in the scaled In/Out;
  - corrections off;
  - the cut planner cutting at word edges.
- The full suite has 1,349 passed. The only failures are 8 in `tests/test_text_box.py`, which also
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

## Second code review (02:45)

A second cold review covered the code written after the first one. It found 6 issues (5
confirmed by running them), and all 6 are fixed with tests:
- a zero-length neighbour at a rough-cut join was pulled into a kept word;
- kept spans rounded inward and clipped a kept word at 200% speed;
- the wordless reach read the next word's onset as wordless sound;
- after a file's last word, the reach was capped at the pad;
- the offline reader crashed on a zero-length source;
- NTSC frame rates were wrong in the offline CLI (29.97 is 30000/1001).

A live re-run then caught one more of my own (a word said elsewhere confused the keep edges), also fixed.

## Third code review (03:40)

A third cold review covered the language work and the later fixes. It found 7 issues plus one
note, and all are fixed with tests:
- `language: auto` leaked from one file to the next in a resident engine (the eval harness keeps
  one), and a resumed job could decide its language from a 1-2 s gap excerpt. Now a whole file
  decides afresh, and an excerpt reuses the file's choice or falls back to Thai.
- `qwen3_asr` crashed on `auto`.
- The Thai-pinned HF engines silently decoded `en` as Thai and cached it under the English
  identity. They now refuse.
- The review recheck was Thai-only (now `--language`).
- A reordered zero-length word could widen a planned piece.
- The stretch check accepted a jump back when words touched.
- `join_words` dropped the space before a quote.

## State you are left in

- PR #115 is merged into master, so a helper from master or this branch matches the panel.
- The shared store has the new `job.chosen_at` column (added on first use by this branch's code).
  A backup from before is `output/store-backups/transcriber-20261122-before-chosen_at.db`. Code
  without this change (any branch not yet merged with it, e.g. PR #116's) fails to read jobs
  from the migrated store: merge master into it first.
- Nothing was exported. The project was saved once since, on 2026-11-22 at 07:22, by the
  `cdv.py launch --reload-panel` of PR #115's live check, so the `listen` scratch sequences below
  are now in the saved file (`20260130 RENAME template - Copy_1.prproj`).
- The shared store (`transcriber.db`) gained source transcripts: jobs 79 and 81-90 (90 is the Gillette
  Vegas lecture, 20261116), and one `--experiment` eval row (id 6, not a baseline).
  - Jobs 84 and 88 (Gillette review) and 85 (tiw) are from other projects.
  - Jobs 86, 87 and 89 are the English broadcast in Thai, `en` and `auto`. The newest (89, English)
    is the one the timeline tools use.
  Job 80 is a temporary WAV from the first ASR rough cut, the old behaviour.
- Scripts: `scripts/timeline_listen/calibrate_edges.py` (in the PR). Tonight's one-off experiment
  scripts and outputs are in `output/timeline_listen/`, which git ignores, so they are not in the PR.

## Final checks (04:00)

- **Default decoding is unchanged, by the harness.** `python -m transcribe.eval.harness --experiment`
  on the final code passes with CER_thai 0.0530, WER_latin 0.9231, BER 1.0, cue_BER 0.3214 and 0
  overlapping cues, identical to the last baseline rows. The run is recorded as an experiment, not
  a baseline.
- **Real decodes on the final engine code:** a Thai clip with the default and with `auto` gives
  identical Thai; the English window with `auto` gives English (0 Thai characters).
- **A fresh agent planned your route from the tool descriptions alone.** It found the right tools
  (transcribe on `missing`, `keep_words`, build into the copy to reorder, read back). It was unsure
  about ticks units, `occurrence`, the reorder steps (defined only in JS), and "base never edited"
  vs `into`. The descriptions now answer all of those, including a swap recipe.
  - Re-asked with the new descriptions, a second fresh agent wrote a complete plan. It was run
    verbatim on scratch (`listen agent plan (scratch)`): keep 2 lines with every track, swap them,
    read back. It reads exactly "สวัสดีครับยังไม่อัพโน้น", "อีก 20 นาที"; 0 cuts in sound, 0 tails;
    all 7 tracks (2.63 s). **Your request, end to end, by an agent from the tool descriptions alone.**
- **Offline crash sweep:** `timeline_transcript --prproj` ran on 36 `yt`/`tt`/`race` cuts in 20
  October projects (18 to 2,601 clips). No crash; the sources there are not transcribed, so it
  lists them as `missing`.
- **Not run:** the 8 `live` panel tests (`tests/test_cutdeck_live_premiere.py --live`). They need
  In/Out marks on your `editing` sequence and test the existing panel commands, not tonight's.

## Gaps and limits (please read)

- **Your OBS files' extra streams are harmless today.** In every footage file of 20261121, stream 2
  duplicates stream 1 and streams 3-4 are silent. Per-stream transcription was not built.
- **A wrong-language transcript: partly fixed (2026-11-22, after the PR's first review).**
  - The timeline tools read the transcript `transcribe` last returned, cached or new. Before, they
    read the newest job, so once a Thai job was newest, asking for `en` again hit the cache and
    changed nothing. Now that call switches every timeline tool back to English, with no new
    listening when nothing changed since.
  - A file with transcripts in both scripts gets a warning in `timeline_transcript`,
    `plan_pieces`, `cut_words` and `keep_words`, naming the other job and the call to switch.
    Proven on a copy of the store: the English broadcast flags, and no other file does.
  - Still true: a Rough Cut run first on an English source transcribes it in Thai, because
    `_transcribe_source` uses the default language. It was not switched to `auto`: on Thai files
    `auto`'s margin over English was as small as +0.05 per sample, and a Thai source picked as
    English would ruin the main route. For an English source, run `transcribe(language="en")`
    once; with no other transcript of the file there is nothing to warn about.
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
- **Thai text accuracy is unchanged.** This work fixes *where* words are and which language they
  are decoded in, not how well Thai is recognized. `biodatlab whisper-th-medium` still mishears
  casual speech and F1 names. Any engine
  change needs the gold set (still the #1 blocker).
- **Corrections are applied, but approximately.** A cue corrected in SubtitleDesk or the web
  editor replaces that cue's words, and its lines say `corrected: true`. When the corrected text
  has a different word count, its word times are shared by characters, so word positions inside
  that cue are estimates. No corrections exist in the store yet, so this is unit-tested only.
- **"Any finished transcript" is accepted.** The one `transcribe` last returned for the file's
  sha256 is used, whatever the engine, settings or age.
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
- **Reordering after `keep_words` is proven live**, as `build_sequence` with `into` and the steps
  clone far, lift, clone back, lift (the v3 recipe). It first needed a filler item, because
  `build_sequence` required at least one; it now accepts zero items with `into` and `steps` (also
  proven live). Steps move whole clips by where they start (no razor), so give block boundaries
  that sit on clip edges: a wrong boundary left a 1.3 s hole on a scratch.
- **Frame rates:** every sequence was 30 fps. A 50 fps source (`10-55-45.mp4`) in a 30 fps sequence
  was mapped and kept correctly (`keep_words`: frame-aligned In/Out, video and audio together).
  NTSC rates (29.97 and so on) are handled in code but were not run live.
- **English audio was translated, not transcribed (fixed, see below).** `10-55-45.mp4` is an English F1 broadcast. The
  Thai engine wrote much of it in Thai ("ดังนั้นคุณต้องขับรถเร็ว ๆ"), looped ("รถหัวแข็งของรถหัวแข็ง…"),
  and only switched to English later ("Generally, Haas looks very tricky."). For English-language
  sources, the words on the timeline can be wrong even where the timing is right. **Fixed at
  03:30:** the decode language is now a choice. `transcribe(media_path, language="en")` (MCP and
  helper too) transcribes English correctly with the same model. It is cached apart, and the
  transcript `transcribe` last returned for a file is the one the timeline tools use. Default `th`. `language="auto"`
  picks Thai or English per file from the model's own confidence. It was proven both ways live
  (English broadcast → English, Gillette review → Thai, each identical to the explicit choice) and
  held out on 10 unseen files, 10 of 10 right (docs/ENGINES.md). That covers one Thai speaker (you)
  and one kind of English (F1 broadcast commentary). It also works through the helper
  and MCP route. **Your synced F1 feeds (`1.mp4`, `2.mp4`) are English commentary**: transcribe them
  with `en` or `auto`.
- **A pre-existing Rough Cut bug was reproduced.** Applying a rough cut to `listen two sources
  (scratch)` failed its own read-back once: a 1-frame razor clone was left on A3 past the sequence
  end (5733.267-5733.3 s). The identical retry passed. This is the intermittent native-razor failure
  already in the 1RaceClub log ("razor filler ... not one frame long"). The read-back caught it,
  and the original was untouched. Not fixed (it is UXP cut code, which needs a live probe).
- **The tools need the panel.** The CutDeck panel must be connected to the helper. After a helper
  restart it reconnects by itself, but only if the panel's code matches (see the PR #115 note above).

## Prepared for you: F1 gold-set drafts

Thai text accuracy can only improve against a gold set, and today's has one 60 s F1 clip.
`output/gold_drafts/` (not in git) holds three 90 s clips of your own F1 talk, from three
sessions, with draft transcripts taken from each source's full-context transcript. Its README says
how to correct and freeze them (about 10 minutes of listening each).

## Follow-ups

- When PR #116 (projects layout) merges, `projects/1raceclub/shorts-rules.md` step 1 ("Transcribe
  the rough cut") should read "Read the rough cut with `premiere_timeline_transcript`".
- A stream choice for multi-stream sources: the transcript, the levels and the Rough Cut all
  read the first audio stream.
- Text accuracy: build the gold set, then try an engine change through the harness.

## Scratch sequences made tonight (yours to delete; saved in the project since 2026-11-22 07:22)

All 30 of them start with `listen`; the only other sequence in the project is your `editing`.

- `listen test A (scratch)` and `listen test A (scratch) — CutDeck 86551c23` (a 6-min copy and its rough cut)
- `listen test A words (scratch)` and `listen test A no-er (scratch)` (`cut_words` results)
- `listen speed (scratch)` (the speed probe)
- `listen full (scratch)` and `listen full (scratch) — CutDeck 4002a9e8` (the full-length rough cut)
- `listen short (scratch)` (the reordered Short)
- `listen test A words v2 (scratch)`, `listen test A words v3 (scratch)`, `listen test A no-er v2 (scratch)`, `listen test A no-er v3 (scratch)` and `listen test A no-er v4 (scratch)` (`cut_words` reruns; v4 is the final code)
- `listen short placed (scratch)` (the Short built from `plan_pieces`)
- `listen two sources (scratch)` (mic file on A1-A4, camera file on V2/A5)
- `listen rough-first (scratch)` (the never-transcribed source on A5; its rough cut was analysed but not applied)
- `listen agent plan (scratch)` (the fresh agent's plan, run verbatim)
- `listen two sources kept (scratch)`, `listen two sources kept v2 (scratch)`, `listen two sources kept 60 (scratch)` (`keep_words`)
- `listen keep span (scratch)` (`keep_words` with a 10 s span across rough-cut joins)
- `listen two sources (scratch) — CutDeck 43c26617 (FAILED)` and `listen two sources (scratch) — CutDeck 43c26617` (the razor-bug repro and its retry)
- `listen two sources rc keep (scratch)` (`keep_words` on that rough cut: two multi-clip spans, every track kept)
- `listen short placed 60 (scratch)` and `listen short placed final (scratch)` (the Short re-proven on the final planner)
- `listen test A no-er final (scratch)` (`cut_words` on the final code), `listen 50fps (scratch)` and `listen 50fps kept (scratch)` (the 50 fps check)
- `listen two sources rc keep v3 (scratch)` (`keep_words` across joins, then reordered twice: the second reorder used a wrong boundary and left a 1.3 s hole and empty extra tracks; it is scratch)
