# Timeline transcript at the cut: how far to trust each word edge (2026-11-28/29)

Question: for any sequence, is each word's start and end on the timeline within a stated
tolerance of the sound, with an error bar per edge, and is speech with no word reported?
No cut audio is transcribed again at any step. Branch `timing/cut-trust` (it carries all of
`timing/judge`, which is not on master yet).

**The reference is still provisional.** Every timing number below scores against the timing
judge's agent marks (726 edges, `transcribe/eval/judge/`, judge.lock). The owner's Praat files
(`E:/Me/5.Claude/timing-judge-labels`, 26 clips) have 0 marks so far. When they are marked:
`python -m transcribe.eval.judge.praat collect`, re-lock, then `python tools/timing_options.py fit`
rescores the table and refits the bars. The judge marks only onsets after and offsets before a
pause of 100 ms or more: **edges inside running speech are not measured by anyone yet.**

## 1. Where today's error comes from (heldout, 279 marked edges, within one frame)

| Part | Measure | Result |
|---|---|---|
| Source time, stale transcript | most stored jobs predate word_align (2026-11-24) or its tuned knobs (11-28); the tool served Engine A times + `tighten` | **45.5%** vs 77.1% with CTC + snap: 32 points |
| Source time, `tighten` over CTC words | the tool re-fitted CTC-timed words to the level envelope | −6.1 points, all on ends (68.8% → 55.8%) |
| Source time, CTC + snap itself | `causes.py` on the 61 misses | placement 54 (CTC 22, snap 22, snap broke a good CTC start 10), collisions 2 |
| Text | marks with no word, VAD cuts | 5 of 279 (1.8%); wrong text: CER_thai 0.053 on the gold set (not split per edge) |
| Mapping | Premiere's own render vs the mapping (below) | 0.07 ms after one constant 21.33 ms |

## 2. Mapping round trip (`tools/mapping_roundtrip.py`)

`yt` (20261124, 873 clips on A1) through `timeline_from_prproj` + `audio_clips`, each clip
cross-correlated against the owner's own render `yt las.mp4`: 812 clips checked (61 under 0.6 s
skipped), all at **+21.33 to +21.40 ms**, one constant: 1024 samples at 48 kHz, AAC priming.
Removed, the residual is ≤ 0.07 ms (0.002 frame). If the constant belongs to Premiere's playback
of AAC sources rather than to the render, every edge is 21 ms off and every bar under ~45 ms is
wrong: a WAV render settles it. Not run: the live `read_timeline` path and speed-changed clips
(Premiere was not open). The owner's projects (18 saved, 2026-11-10 on) have 0 reversed clips and
0 nested speech clips; the only real speed change is a 29× race feed. Found:
`timeline_from_prproj` infers speed 0.83–1.10 on 557 SFX clips with no speed tag (none speech).

## 3. Options on the same judge (tool view: pieces merged into Thai words)

| Option | tune w1 | heldout w1 | starts / ends (heldout) | ≤20 / 40 / 80 ms | \|err\| median / p90 | vs current, heldout (95% CI; edges better/worse) |
|---|---|---|---|---|---|---|
| Engine A only | 18.1% | 12.5% | 21.3 / 3.6 | 11 / 23 / 47% | 85 / 255 ms | −64.5 [−74.6, −54.5]; 25/176 |
| Engine A + tighten (tool before, stale job) | 41.7% | 45.5% | 61.7 / 29.0 | 43 / 51 / 67% | 35 / 215 | −31.5 [−45.0, −16.5]; 33/101 |
| Energy-only snaps on Engine A | 59.0% | 75.3% | 80.9 / 69.6 | 65 / 81 / 86% | 15 / 132 | −1.8 [−7.9, +4.4]; 27/22 |
| CTC (sakares) + snap + tighten (tool before, fresh job) | 61.3% | 71.0% | 85.8 / 55.8 | 65 / 77 / 82% | 15 / 170 | −6.1 [−15.7, +2.1]; 18/28 |
| **CTC (sakares) + snap (current pipeline)** | **67.2%** | **77.1%** | 85.1 / 68.8 | 67 / 83 / 87% | 15 / 105 | — |
| CTC (airesearch) + snap | 69.7% | 78.1% | 84.4 / 71.7 | 68 / 84 / 88% | 15 / 80 | +1.1 [−1.4, +4.0]; 13/11 |

Tune is where the options were chosen; heldout was already seen by two earlier keep decisions
(T2, T5). Per-edge confidence, 90% bars fitted on tune, checked on heldout. A bar is given only
to an edge with a pause beside it (100 ms of PAUSE-rule quiet within 300 ms outside the edge);
22 of 274 matched marked edges get none (a word-gap gate left 55 without one).

| Error bar | heldout coverage | mean bar | signal AUROC for "within one frame" |
|---|---|---|---|
| one constant bar | 98.8% | 165 ms | |
| CTC margin (top-1 minus top-2 log-prob at the letter) × placement | 94.4% | 87 ms | 0.52 (no signal) |
| **energy step across the edge × placement (snap / ctc / engine / collapsed)** | **93.3%** | **62 ms** | 0.88 |
| same bars on a stale (tightened) transcript | 88.5% | 121 ms | |

**Recommendation, from these numbers:** keep the current pipeline (CTC sakares + snaps), stop
`tighten` from re-fitting CTC-timed words, re-time stale transcripts with CTC (no new ASR), and
put the energy-step × placement bar on every edge beside a pause. The airesearch checkpoint is
ahead on both splits but its heldout CI includes 0 and its edges split 13/11; energy-only is close
on heldout but 8 points behind on tune (CI below 0).

## 4. Holes: speech no word covers

Picked on tune, checked on heldout, against marked speech (onset to next offset): sound under
the PAUSE rule (skips breaths and room tone) ≥ 100 ms that no word covers. Heldout: 14 of 14
reported holes were speech, 4 of 5 wordless speech runs found; tune 26 of 30 and 7 of 10.
VAD-based detectors were noisier (precision 0.27–0.66). On real sequences the holes are a mix,
and each says which kind it may be:

| Sequence | holes | between two words (`between_words`) | holding a collapsed word (`untimed_words`) | other |
|---|---|---|---|---|
| Qatar Rough Cut | 399 (81 s) | 153 | 30 | 216 |
| `yt` 20261124 | 164 (36 s) | 60 | 17 | 87 |

8 of 8 sampled `yt` holes (spectrogram) were voiced speech with the next word's start placed
100–370 ms late inside running speech: a word-edge error of the unmeasured kind, not missing
text. "Other" holes are not characterised.

## 5. Audit and back-test (saved projects, a copy of the store, the two sources re-timed)

Flags fixed before opening the cuts. F1: sound within 20 ms of the cut (the tool's existing
`severity: "sound"`). F2: F1 and the cut inside a word by more than that edge's bar.

| Sequence | edges | F1 | faint tail | F2 |
|---|---|---|---|---|
| Qatar Rough Cut `2026-11-28 14-04-01_Synced — CutDeck 583e212f` | 3,272 | 50 | 189 | 7 |
| `yt` (20261124), the owner's final | 1,738 | 53 | 112 | 8 |
| …of which the owner's own edges (not in the agent's `clean v2` at 00:54) | 7 | 3 | 1 | 1 |

**The back-test is not passed, and it is too small to pass.** Only 7 owner-made edges had their
voice file online (older voice files are deleted; the HKS footage on G: is not mounted). Every flag
on them, from the spectrogram: (1) out at 27:04:24 on the last 12 ms of ตัวเอง's fade; (2) in at
27:04:24 exactly on ซึ่ง's onset: its CTC start is 53 ms early, outside its 25 ms bar, so F2 fires
on a tool error; (3) out at 27:32:25 on the word boundary of ที่สาม, cutting the restart
"เป็น เอ้ย เป็น" with 18 ms between words: sound at the cut, deliberate. F1 flags 3 of 7 (none an
audible clip), F2 flags 1 (a placement error).
Rough Cut F2 (7): each sits in a quiet or faint stretch while the word's engine end or early start
reaches over it: word-span errors, not cuts in speech. `yt` inherited F2 (7): 3 are real cuts inside
speech made by agent edits and kept (a held เอ่อ, between Mirror's syllables, โอเค); 4 are
word-span errors.

## 6. What was built

- `word_align.retime_words` records `start_by` (snap / ctc / engine) and `end_by` (snap / engine).
- `python -m transcribe.retime MEDIA`: CTC + snaps on a stored transcript's own words, same job;
  text, cues and corrections untouched; ~45 s per 1.5 h source. One model on the GPU: not while
  a transcribe job runs. It writes the shared store, so Rough Cut and the HKS gates (which read
  the same stored words, still through `tighten`) see the new times too.
- `timeline_transcript.build` (`premiere_timeline_transcript`), additive fields: `start_err_ms` /
  `end_err_ms` on each line and on every word in the full file (with `start_by` / `end_by`), only
  beside a pause; `cut_err_ms` on each cut edge; `holes` (with `between_words` / `untimed_words`);
  per source `timing` ("ctc" or "tightened", the latter with the retime command).
- Behaviour change: for a source whose words word_align placed (every transcript made from now
  on, or re-timed), `build` no longer runs `tighten` over them. `cut_words`, `clean_speech`,
  `keep_words`, `plan_pieces` and `split_pieces` read words through `build`, so they get these
  times. Tests pass; not yet run live. `source_words` called directly (Rough Cut, HKS gates) is unchanged.
- Bars live in `cutdeck/edge_bars.json`, written by `python tools/timing_options.py fit`.
- Gates: harness experiment on a copy of the store vs eval_run 13: every paired delta 0
  (CER_thai 0.0530, cue_BER 0.333, 0 overlaps), pass. pytest 1827 passed; node 849 passed.
- Audit/back-test: `python tools/cut_audit.py` (on a copy of the store; it re-times nothing itself).

## 7. Not proven yet

- Every timing number and every bar against the owner's Praat marks (0 of 26 marked).
- Edges inside running speech: no reference marks them, so they get no bar; the hole sample
  suggests their errors reach 100–370 ms. Marking them needs a different Praat task (word
  boundaries inside phrases, not only pause edges).
- The live path (`read_timeline`), speed-changed clips (50/200/99%), and a WAV render that settles
  whether the 21.33 ms belongs to the render or to Premiere's playback of AAC sources.
- `premiere_timeline_transcript` and the word-cutting commands with the new times in live Premiere.
- A back-test on more of the owner's hand cuts (needs G: mounted or other cuts whose voice files
  are online).
- Bars for collapsed words (2 tune edges: they get the global 165 ms) and for corrected cues whose
  words are shared out by character count (no bar: never measured).
- Holes with a word on one side or none (216 / 87): not characterised.
- Text errors per edge (no reference transcript on the timing clips).
- The judge lock fails on a fresh checkout when git turns judge files to CRLF (core.autocrlf).
