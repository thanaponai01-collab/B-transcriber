# Timeline listening: what the cut timeline says, without listening again

Overnight work, 2026-11-22 (00:40 to 06:00). Branch `feat/timeline-listen`, built on PR #115's
branch (`feat/premiere-text-dialogs`), because the panel running in Premiere is that code.

## The problem (owner, 2026-11-22)

CutDeck can see and drive Premiere; the weak part is hearing. The usual flow is: rough-cut
first, then transcribe. But transcription takes a media *file*, so the agent transcribed either
the source file (whose times don't match the cut timeline) or a render/copy of the cut timeline
(a new file: slow, and the transcript changes from run to run). Either way, the agent did not
know exactly where each word sits on the timeline, and cuts landed wrong.

Root causes found:
1. **No timeline coordinates.** Nothing mapped a transcript onto the clips of a sequence.
   `transcribe` takes one file; the rough cut's own ASR transcribes a throwaway mixdown whose
   sha256 never repeats, so even its cache never hits.
2. **Re-listening changes the words.** Transcribing the cut audio again loses context at
   every cut: on a 6-min rough cut, a fresh transcript of the cut audio agreed with the source
   transcript on only 83% of characters (e.g. "สวัสดีครับ" became "good afternoon").
3. **Engine word times are loose.** faster-whisper's Thai word spans run far into the pauses
   around them (a "ครับ" of 1.0 s). Placing a cut from those times clips words, or leaves gaps
   (the 1RaceClub log: "ASR word times ran ~0.1 s off, v8/v9 clipped รัส").

## The solution

**Transcribe each source file once; map it through the clip list.** A cut timeline is a list of
pieces of source files, so a word's timeline position is arithmetic:
`timeline_ticks = clip.start + (source_ticks - clip.in)`, exact in Premiere ticks.

- New MCP tool `premiere_timeline_transcript` (helper command `timeline_transcript`,
  code `cutdeck/timeline_transcript.py`). It reads the sequence (`read_timeline`), takes each
  clip on one audio track (default: the first un-muted one with clips), finds the newest
  finished transcript of the clip's source file in the shared store (by sha256, any engine),
  and returns:
  - `lines`: the engine's phrase cues as the timeline plays them (`tc`, `start_s/end_s`,
    `start_ticks/end_ticks`, `text`, `clip` id, `src_s`). A cue a cut runs through becomes
    two lines; a cut-away part is gone.
  - `edges_inside_words`: every clip In/Out that cuts into audible speech, with the word,
    how much of it is lost, and `nearest_quiet_ms` (the shift that would put the cut in quiet).
  - `query`: finds a phrase on the timeline (spaces and punctuation ignored, also across a cut).
  - `missing`: source files never transcribed. Run `transcribe(media_path)` once each.
  - `full_path`: a JSON file with every line and word.
- **Copies and re-cuts are free.** A rough cut, a `cut_copy`, a reordered Short: same sources,
  so the same transcript, re-mapped in milliseconds. No GPU, no re-listening, no drift.
- **Word times checked against the audio.** Each word is pulled in to the first and last
  audible 10 ms window inside it, the same loudness rule as the Rough Cut's sound guard
  (floor = 5th-percentile level clamped to -65..-35 dB, sound = 6 dB above it). The source's
  level envelope is decoded once (streamed) and cached by sha256
  (`output/timeline_transcripts/levels/`).
- The sha256 of a large camera file is remembered by (path, size, mtime), so a 7 GB file is
  hashed once (`transcriber.db.sha256-index.json`).

## Evidence (live, Premiere 27.0, project open, user's sequence untouched)

Run folder: `output/verify-cutdeck/runs/20261122-004515-timeline-listen/`.

| Check | Result |
|---|---|
| Source transcript of the 96-min clip (`2026-11-21 10-40-52.mp4`) | 224 s on the RTX 3070, 1,483 cues, 8,523 words (store job 79) |
| `timeline_transcript` on `editing` (1 clip) | 1,481 lines in timeline time; no new transcription |
| Scratch copy `listen test A (scratch)` (110-470 s, via `cut_copy`) then Rough Cut (aggressive, ASR) | 119 cuts, 223 s removed: `listen test A (scratch) — CutDeck 86551c23` |
| `timeline_transcript` on that rough cut | 125 lines, 119 clips, 6 s, 0 missing |
| Edges inside words, engine word times | 105 of 238 |
| ... after tightening words to the audio | 41 |
| ... and counting only cuts in audible sound | **5**, each within 2-8 ms of quiet (the cut pad on a fading tail) |
| Independent check: the rough cut's own audio, extracted from its clips and transcribed fresh | fresh cues found in the mapped transcript sit a median **3 ms** from the mapped position (p10 -117, p90 +363 ms, the fresh transcript's loose cue times); text agreement 83% (the re-listening drift above) |

Tests: `python -m pytest tests/test_cutdeck_timeline_transcript.py` (reorder, same source
twice, cut through a word, tolerance, a cue split by a cut, find across a cut, track choice and
skips, missing and offline media, paging, zero-length engine words, tightening, the audio gate).

## What is not done / gaps (for the morning)

Updated through the night; see the PR for the latest.

- Only one audio track is mapped per call (default the first un-muted one with clips). A synced
  multicam with the voice on A3 needs `track: "A3"`.
- Clips at speeds other than 100% or reversed are skipped (listed in `skipped`), not mapped.
- Nested sequences have no media file: skipped.
- Text accuracy is the engine's (biodatlab whisper-th-medium). This work fixes *where*, not
  *what*. The gold set remains the blocker for any engine change (memory: audit findings).
