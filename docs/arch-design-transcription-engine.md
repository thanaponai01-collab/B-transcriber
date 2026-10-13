# Transcription engine: five improvements

Design only, 2026-10-12. Nothing here is built yet. Goal from the owner: **the transcript
should match the real audio as closely as possible, and every tool in this repo should get
that same engine.** SRT and Premiere timing come later; robustness comes first.

Evidence labels: **proven** = ran it this session · **traced** = read the whole code path ·
**suspected** = neither.

## Where we are

| Fact | Label | Source |
|---|---|---|
| Engine A `faster_whisper` (whisper-th-medium CT2); Engine B passthrough; LLM tiebreak off | traced | `transcribe/config.yaml` |
| Last gated run (9 clips, 2026-10-07): CER_thai .168, **WER_latin .876**, BER .570, cue_BER .368 | traced | `config.yaml` `recover_short_spans` comment |
| Every engine swap and second engine tried so far lost to th-medium | traced | `docs/ENGINES.md`, TODO_LEDGER Phase B |
| Main `transcriber.db` has **0 bias terms, 0 corrections, 0 eval_run rows** (54 jobs) | proven | sqlite query |
| Helper transcribe jobs (used by ClubFriday) write to a **new empty DB per job** (`<job folder>/transcribe.db`), so they get no bias terms and no cache | traced | `cutdeck/ai_worker.py:15-19`, `run.py` reads bias from that conn |
| Rough Cut uses `store._DEFAULT_DB`; the editor uses CWD-relative `transcriber.db` | traced | `cutdeck/rough_cut.py:162`, `editor/server.py:27` |
| `run_file` doesn't return its `job_id`; Rough Cut looks it up by path afterwards | traced | `rough_cut.py:180-186` |
| No metric for speech that produced no text (the 4 s silent drop in the 2026-08-10 report) | proven | `grep` of `eval/metrics.py` |
| Still open: 120 ms orphan fragment at a window seam (`น` at 97.12 s); term errors (ธรณีสงฆ์, โหนกระแส, ฉ้อโกง, money amounts) | traced | TODO_LEDGER 2026-08-10 |
| Per-cue confidence is only word probability; `avg_logprob` / `no_speech_prob` are dropped | traced | `engines/faster_whisper.py:303,554` |
| `transcribe/review.py` (suspicion flags) runs only from `tools/recheck_subtitles.py`, not in the pipeline | proven | `grep` |
| faster-whisper 1.2.1 installed; both `WhisperModel.transcribe` and `BatchedInferencePipeline.transcribe` accept `hotwords` | proven | `inspect.signature` |
| Fine-tune data collected: 0.63 min vs ~45 min floor | traced | TODO_LEDGER Phase C step 2 |

**The read:** the model choice has been searched hard and th-medium keeps winning. The
remaining accuracy is lost *around* the model: speech that never gets decoded, vocabulary
it can't know (names, show titles, English terms), and corrections that never flow back
because each tool keeps its own empty database. Those five gaps are below.

## Before / after

```
BEFORE                                             AFTER
CLI ─────────► run_file(db=transcriber.db)         CLI ──────────┐
editor ──────► transcriber.db (CWD-relative)       editor ───────┤
Rough Cut ───► run_file(db=_DEFAULT_DB)            Rough Cut ────┼─► TranscriptionService.transcribe(media, range, glossary)
helper/ClubF ► run_file(db=<job>/transcribe.db)    ClubFriday ───┤      │  one store, one cache, one glossary + bias index
MCP ─────────► helper                              MCP/helper ───┘      ▼
                                                                Transcript{job_id, cues, words, confidence,
returns: list[dict] of cues, no job_id                      coverage_gaps, review_flags, engine/model id}
learning: corrections land in whichever DB              corrections from every tool → one bias index
          the tool opened (all empty today)                                   → fine-tune manifest
```

## The five improvements (in build order)

### 1. Measure what "accurate to the audio" means, first

*Problem.* Nine gold clips, no eval history in the main DB, and no signal for the worst
failure the owner has reported: real speech producing no text at all. CER counts deletions
but averages them away. Every later item needs a measurement that can fail.

*Change.*
- Add **`speech_coverage_miss`** to `eval/metrics.py`: milliseconds of reference speech
  (gold cue spans) with no hypothesis cue overlapping them, ÷ total reference speech. Gate it
  (bump `METRICS_VERSION` to 4). Also report orphan cues (< 300 ms, isolated).
- Grow the gold set from the owner's **Premiere hand recuts**: they are ground truth that
  already exists. `tools/make_gold.py` handles it; the contamination rule stays. Add the
  "noisy / hard clip" that HANDOFF_ONE_ENGINE §3 still lists as open. Target: 15+ clips,
  tagged by type (interview, monologue, music bed, phone audio).
- Pin one eval DB path in config so baselines stop disappearing.

*Done when.* A harness run on the current config sets a v4 baseline; a deliberately broken
config (e.g. `vad_threshold: 0.8`) fails `speech_coverage_miss`.

### 2. One engine service every tool calls

*Problem.* Four callers, three database locations, one of them empty per job. A fix or a
learned term reaches some tools and not others. ClubFriday transcripts can never benefit
from the flywheel today.

*Change.* A thin `transcribe/service.py`:

```python
transcribe(media_path, *, range_ms=None, glossary=(), config=None) -> Transcript
# Transcript: job_id, cues, words, per-cue confidence, coverage_gaps,
#             review_flags, engine_name, model_id, pipeline_version
```

- Wraps `run_file`; it doesn't replace it (the harness and `make_gold` keep calling it).
  `run_file` gains the `job_id` it already knows.
- One store path from config (`store.path`), used by the CLI, the editor, `ai_worker`,
  Rough Cut and the MCP server. Per-job folders keep their result JSON, not their own DB.
- The sha256 cache already in Rough Cut moves into the service, so ClubFriday re-opening the
  same range costs zero GPU time.
- The VRAM rule doesn't change: the helper's single GPU lane is still the only caller that
  loads a model.

*Done when.* A test fakes the engine (mock) and calls the service from each of the four
entry points; all four rows land in one DB, and a bias term inserted once shows up in every
caller's `EngineInput`. `node --test tests/*.cjs` and the pytest suite stay green.

### 3. No speech left behind (coverage guard)

*Problem.* The 2026-08-10 incident: a 4 s window with two utterances and a money figure
produced nothing. The seam fixes and `recover_short_spans` closed most cases, but nothing
*checks* afterwards, and the 120 ms orphan at a window seam is still open.

*Change.* A post-decode pass in `refine.py`:
1. Compare the speech map (VAD spans plus the sound guard's loud runs) with the cues.
   Any speech span of ≥ 600 ms that no cue covers is a **gap**. An isolated cue under 300 ms
   next to a gap is an **orphan**.
2. Re-decode each gap alone, with ±1 s of context and no `initial_prompt`. If it yields text,
   insert those tokens (these are Engine A tokens, so select-only still holds).
3. Anything still empty goes into `Transcript.coverage_gaps`. **No placeholder text is ever
   generated.** The editor and ClubFriday show the gap so a human hears it.

Cost: GPU time only for gaps, inside Engine A's existing residency.

*Done when.* `speech_coverage_miss` drops on the gold set with no gated regression; a
unit test with a synthetic dropped span shows the re-decode path firing.

### 4. Know the vocabulary: per-job glossary plus a flywheel that actually fills

*Problem.* WER_latin .876 means most English words come out wrong. The recurring errors are
proper nouns and domain terms the model has never seen (show name, guest names, legal terms,
brands). The bias index is empty because corrections never reach it (see #2). A 2026-08-05
probe rejected one batch of bias-index terms, so this must stay eval-gated.

*Change.*
- **Glossary per job**: a short list the user (or a project file next to the media) supplies:
  show title, people, brands, numbers style. It's passed through `EngineInput.bias_terms`.
- Use faster-whisper's **`hotwords`** for glossary terms (proven present in 1.2.1), and keep
  `initial_prompt` for style context. Probe both against prompt-only behind the harness,
  since hotwords can also cause insertions.
- **Corrections from every tool feed one bias index**: editor diffs (already built), ClubFriday
  text edits, and Premiere recut SRTs (`scripts/learn_from_srt.py` exists). `min_occurrences`
  and `stale_engine_weight` stay as they are.
- The exception lexicon keeps doing normalization only. Don't merge it with the bias list.

*Done when.* A gold clip with its glossary beats the same clip without one on CER_thai or
WER_latin, with no gated regression across the set. A ClubFriday edit appears as a
`correction` row in the shared DB.

### 5. Say how sure it is, and send humans to the right spot

*Problem.* A second whole-file engine was tried four ways and lost: it doubled runtime and
diluted good text. Yet the user still has to read the whole transcript to find the bad
parts. `review.py` already finds suspicious cues, but nothing runs it in the pipeline.

*Change.*
- Carry `avg_logprob`, `no_speech_prob` and `compression_ratio` per segment into each cue
  (stored in `raw`, so there is no contract change; confidence stays `None` where an engine
  has none).
- Run `review.suspicion_reasons` inside the service and return `review_flags`, ranked.
- **Targeted second opinion**: for the top-N flagged windows only, decode again with
  different settings (greedy, or a wider context window), and show both as candidates. The
  human picks, so the system still selects and never generates. The pick becomes a
  correction (feeding #4) and a fine-tune sample.

*Done when.* On the gold set, flagged cues hold a measurably higher share of the CER errors
than unflagged ones (precision of flags > base error rate). That is the check that the flags
point at real mistakes.

## What this unlocks

Items 2, 4 and 5 make every human fix land in one place. That is the data the LoRA fine-tune
(Phase C, built but starved at 0.63 min) needs. A fine-tuned th-medium on the owner's own
shows is likely the largest single accuracy gain left (**suspected**, untested until the data exists).
SRT and Premiere timing (`cue_BER`, layout) benefit afterwards, because better text and
fewer gaps give better cue starts.

## Limits and non-goals

- No model swap, no second whole-file engine and no LLM tiebreak re-try. Those are settled
  in `docs/ENGINES.md` unless new evidence appears.
- Select-only reconciliation, the one-model VRAM rule and the 0.02 regression gate all still apply.
- Nothing here is proven on GPU yet. Each item has its own harness run before activation.

## Build status

| # | Status (2026-10-13) |
|---|---|
| 1 | **Built; baseline still open.** `speech_coverage_miss` (gated) and `orphan_cues` in metrics v4, `store.path` shared DB, harness uses it. **Proven (4-clip GPU probe, scratch DB):** `vad_threshold: 0.8` raises `speech_coverage_miss` 0.0075 → 0.0258 and the run does not pass (UNRESOLVED, since 4 clips are too few for a CI-confirmed fail). Open: only `yt t1 singapore` plus `Short1-3` (restored from git `e9f8ed4`) have audio on this machine; the other 6 gold clips' media sit on the unmounted `F:\Me\Works` drive. Put them back in `transcribe/eval/goldenset/`, then run `python -m transcribe.eval.harness --config transcribe/config.yaml --establish-baseline` for the v4 production baseline. Gold growth to 15+ clips needs the owner's recuts. |
| 2 | **Built (2026-10-12).** `transcribe/service.py`; Rough Cut, helper `ai_worker`, editor and CLI share the `store.path` DB. The helper's transcribe result now carries `transcript_job_id`. |
| 3 | **Built, OFF.** **Proven (4-clip probe):** with the guard on, output is identical to off (no uncovered speech of 600 ms or more on these clips), so there is no drop to show yet. Stays OFF until the full gold set shows a drop. |
| 4 | **Built; probe says do not use a glossary yet.** **Proven (GPU, `yt t1 singapore`, glossary of 10 F1 terms taken from the reference, so an optimistic case):** none CER_thai .043 / WER_latin 1.000 / coverage_miss 0; prompt .357 / .542 / .189; hotwords .322 / .833 / 0; both .664 / .667 / 0, with the glossary echoed as text. A glossary brings English terms back but wrecks Thai text, so `bias_channel: prompt` without a glossary stays the default, and no caller passes `glossary=`. Also seen: without a glossary, English words are **deleted** inside an existing cue (`ใน นะครับ`); `speech_coverage_miss` can't see that, only WER_latin can. **ClubFriday edits → corrections: built.** Saving quotes splits each edited quote back onto its cues (`clubfriday.server.split_quote_edit`) and writes `correction` rows to the shared store through `flywheel.diff.save_corrections`, the same write path the editor now uses (`tests/test_clubfriday.py`). Sessions transcribed before this change are skipped. |
| 5 | **Flags proven useful on 4 clips; second opinion not built.** **Proven:** flagged cues hold 43% of character errors in 30% of the text (error density .210 flagged vs .118 unflagged). Mixed per clip: `repetitive text` flags 15 of 17 cues in Short1 (one high-compression segment flags every cue inside it), and colloquial `เนี้ย` triggers `unfamiliar Thai fragments` on the F1 clip, where flagged cues are *cleaner* than unflagged ones. Open: the targeted second-opinion decode needs a helper job type (GPU stays in the helper lane) plus a picker UI. |

## Build order and cost

| # | Item | Depends on | Rough size |
|---|---|---|---|
| 1 | Measurement (coverage metric, gold growth) | none | small code; gold growth needs the owner's recut files |
| 2 | One engine service, one store | none | medium; touches 4 callers |
| 3 | Coverage guard | 1 (to prove it) | medium |
| 4 | Glossary + live flywheel | 1, 2 | medium |
| 5 | Confidence + review flags + targeted second opinion | 1, 2 | medium |
