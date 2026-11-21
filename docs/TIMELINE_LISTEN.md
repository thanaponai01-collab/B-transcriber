# Timeline listening: what the cut timeline says, without listening again

Overnight work, 2026-11-22 (from 00:40). Branch `feat/timeline-listen`, PR #117, stacked on
PR #115's branch (`feat/premiere-text-dialogs`) because the panel running in Premiere is that
code (master's helper refuses its `place_text` registration).

## Morning summary

- **The fix:** the agent no longer transcribes a cut timeline. Each source file is transcribed
  once, and its words are mapped through the timeline's clips in exact ticks. A rough cut, a
  copy or a reordered Short is read in about 2 s, and its words never change between reads.
- **New tools:** `premiere_timeline_transcript` (what is said where, plus every cut that lands
  in sound) and `premiere_cut_words` (remove phrases; each cut goes in the quiet pause, then the
  result is read back to check it).
- **The engine is fixed where it hurt cuts.** Thai word *times* were off by up to hundreds of
  ms, both too wide and too narrow. They are now fitted to the audio. Words *text* is unchanged
  (no engine swap without the gold set).
- **Rough Cut** now reuses the stored source transcripts: no ASR pass, the same cuts frame for
  frame.
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
- `sources[].note` warns when a file has several audio streams. Everything here, the Rough Cut
  included, reads the first stream (see Gaps).

### Word times fitted to the audio (`tighten`)
Each source's 10 ms level envelope is decoded once, streamed, and cached by sha256 in
`output/timeline_transcripts/levels/`. Sound means the Rough Cut sound guard's rule: 6 dB above
the file's floor (the 5th-percentile level, clamped to −65..−35 dB). Each word is:
1. pulled in to the first and last audible window inside the engine's span;
2. where an edge borders a pause, grown out through continuous sound, at most 400 ms and never
   into a neighbouring word.

On the 96-min source, late onsets of 100+ ms went from 256 to 6 and early ends from 275 to 5
(the rest are beyond the 400 ms reach).

### `premiere_cut_words` (helper command `cut_words`, `cutdeck/word_cut.py`)
- `remove`: `[{"text": "...", "occurrence": n}]` or `[{"from_ticks", "to_ticks"}]`.
- Each cut runs from the pause before the words to the pause after them, leaving `keep_ms`
  (default 250, never more than was there) of pause at the join. It then moves to the nearest
  frame where the audio is quiet; `no_quiet` says when a side had none.
- A phrase found only inside a longer word is refused, not cut through.
- It makes `result_name` with `cut_copy` (the source is never edited), then reads the result back
  and returns:
  - `checks`: how many times each phrase is said, before and after;
  - `joins`: the words either side of each join;
  - `new_cuts_in_sound`: any new cut that has sound at it.

### Rough Cut speech protection reuses the source transcripts (`rough_cut._mapped_transcript`)
With speech protection on, if every reference-track source has a stored transcript, its words
are mapped onto the range instead of transcribing the WAV. Otherwise it falls back to the old
path. See docs/rough-cut.md.

### Agents are told
The MCP server's instructions now say: to know what a sequence says and where, call
`premiere_timeline_transcript`, not `transcribe` on a render; remove words with
`premiere_cut_words`.

## Evidence (live, Premiere 27.0, your project open)

Run folder: `output/verify-cutdeck/runs/20261122-004515-timeline-listen/`, with every request and result.

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
| `cut_words`: remove "เดี๋ยวตื่นแล้วหรอ" and "คอลลีฟายกัน" | said 1 → 0 each; joins read naturally; no new cut in sound |
| `cut_words`: remove all three "เอ่อ" fillers | said 3 → 0; no new cut in sound |

Tests:
- `python -m pytest tests/test_cutdeck_timeline_transcript.py tests/test_cutdeck_word_cut.py` covers
  the mapping, speed, tightening and growth, audio-gated edges, late onsets, the cut planner,
  quiet snapping, whole-word matches and the rough-cut mapping.
- Each test was shown to fail on a broken implementation.
- The full suite has 1,308 passed. The only failures are 8 in `tests/test_text_box.py`, which also
  fail on the base branch: the `uharfbuzz` module is not installed here.
- `node --test tests/*.cjs`: 795 passed. `scripts/check_rough_cut.py` passes.

## Gaps and limits (please read)

- **Text accuracy is unchanged.** This work fixes *where* words are, not *what* they are.
  `biodatlab whisper-th-medium` still mishears casual speech and English phrases. Any engine
  change needs the gold set (still the #1 blocker).
- **Editor corrections are not applied.** Lines come from the engine's raw word list, not from
  corrections saved in the web editor or SubtitleDesk.
- **"Any finished transcript" is accepted.** The newest one for the file's sha256 is used,
  whatever the engine, settings or age.
- **One audio track per call.** On a synced multicam with the voice on A3, pass `track: "A3"`.
- **First audio stream only.** Multi-stream files (OBS) are read from their first stream, and
  UXP cannot say which stream a Premiere clip plays. Your 10-40-52 file has 4 streams: 1 and 2
  are identical (the voice), 3 and 4 are silent, so it is fine. A file with mic and desktop on
  separate streams would need a stream choice. The tool warns about this.
- **Reversed clips are skipped**, and so are nested sequences (no media file).
- **Joins are frame-accurate, not sample-accurate.** A tight join (words touching) can be up to
  one frame (33 ms) off.
- **The cross-checks share `audio_extract`'s assumptions** (ffmpeg's first stream, its timing),
  so they cannot catch a stream mismatch.
- **Long sources are transcribed whole.** A 3-hour stream takes about 7-8 min once, even if only
  10 minutes are used. After that it is free.
- **The tools need the panel.** The CutDeck panel must be connected to the helper. After a helper
  restart it reconnects by itself, but only if the panel's code matches (see the PR #115 note above).

## Scratch sequences made tonight (yours to delete; the project was not saved)

- `listen test A (scratch)` and `listen test A (scratch) — CutDeck 86551c23` (a 6-min copy and its rough cut)
- `listen test A words (scratch)` and `listen test A no-er (scratch)` (`cut_words` results)
- `listen speed (scratch)` (the speed probe)
- `listen full (scratch)` and `listen full (scratch) — CutDeck 4002a9e8` (the full-length rough cut)
- `listen short (scratch)` (the reordered Short)
