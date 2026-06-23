# TODO_LEDGER

Deferred work from the IMPLEMENT_CUTDECK.md build. Each entry has a trigger that
makes it due. Owner: build-discipline.

## Transcriber gaps (Part A)

- **Engine default switched to `faster_whisper` (CTranslate2), single-engine
  (2026-06-18).** `config.yaml` now runs `engine_a: faster_whisper` /
  `engine_b: passthrough`. Whole-file transcription (capability flag
  `Engine.prefers_whole_file`) on the RTX 3070: 5-min clip in ~1m30 (was 10m+ and
  the HF transformers dual-engine path never finished). Also fixed this session:
  HF `array`→`raw` input-key break (transformers 5.9.0), OOM-retry reusing
  mutated dicts (`_batch.py`), repetition-loop survival, and the align_hyp
  far-match producing file-spanning timestamps.
- **Cue granularity — DONE (2026-06-18).** faster-whisper now runs with
  `word_timestamps=True` and `_group_words_into_cues` re-joins the sub-word Thai
  pieces into phrase cues, breaking only at word boundaries on a >700 ms gap or a
  >6 s span. Result on the 5-min clip: ~37 cues, median ~7 s, no mid-word cuts;
  runtime ~1m40 (word timestamps roughly double the engine pass, still sub-
  realtime). Tested in `tests/test_faster_whisper_cues.py`. Residual: occasional
  long cue when Whisper drifts a single word's end timestamp — cosmetic.
- **Engine B re-introduction is eval-gated.** Cross-engine agreement only earns
  its 2× cost if the harness proves it lowers `cer_thai`. **Due when:** a real
  bias-sensitive gold set exists to measure it.

- **GAP-4 chunk overlap (other half).** `stitch.py` is built, tested, and wired
  into `run.py`, but `ingest.py` still emits non-overlapping VAD chunks, so the
  stitcher is currently a no-op. **Due when:** chunking is changed to emit
  ~0.5–1 s overlap (or fixed-window chunking replaces VAD-segment chunking).
  Until then words can still be lost at segment seams.
- **GAP-5 prompt injection — GPU verification. ✅ DONE (2026-06-11).** Proven on
  the RTX 3070 with transformers 5.9.0: `get_prompt_ids` exists and the pipeline
  accepts `prompt_ids`; transcribe ran clean with and without bias terms.
  Residual: whether bias terms measurably *improve* accuracy is an eval question,
  not a wiring one — settle it once the gold set has real bias-sensitive samples.
- **GAP-2 VFR conform.** `is_vfr` is probed and persisted; `ingest.conform_vfr`
  config flag exists but no CFR-proxy transcode is implemented, and XML export
  does not yet refuse to run against a VFR original. **Due when:** `xml_export.py`
  (CutDeck Phase 2) is built.
- **GAP-6 gold-set promote CLI** — not started. **Due when:** first fully
  human-corrected job exists to promote.
- **GAP-7 editor reason UI.** Column + API + diff plumbing done; the one-tap tag
  UI in `static/index.html` is not. **Due when:** editor front-end is next touched.
- **GAP-8 job resumability** — not started. **Due when:** a multi-hour file is
  run for real and a crash costs a full re-run.
- **A.2 loudness pre-pass + editor confidence highlighting** — not started.

## CutDeck (Part B)

- **Phase 0 — DONE.** timebase + VAD persistence + schema migration in place.
- **Phase 1 — DONE (2026-06-12).** `cutdeck/` package built:
  `contracts.py` (Segment/Label/CutSpan/CutPlan/CutConfig + Timebase re-export),
  `segment.py` (gap/VAD utterance segmentation), `rules.py` (deterministic
  silence cuts shrunk by padding + config-gated filler removal + min-clip merge),
  `plan.py` (contiguous/exhaustive CutPlan, JSON round-trip, store glue, and a
  `python -m cutdeck.plan --job-id N` CLI). `cut_plan` table + store CRUD added.
  18 acceptance tests green in `tests/test_cutdeck_phase1.py`; Phase 0 + smoke
  unaffected. Determinism, padding-no-overlap, and min-clip invariants all proven.
- **Phase 2 — BUILT (2026-06-19), real-import acceptance PENDING.**
  `cutdeck/xml_export.py`: CutPlan → FCP7 (xmeml v5) XML. One `<sequence>`, video
  track + 2 linked audio tracks (stereo), one clipitem per KEEP span laid
  end-to-end, all referencing a single `<file>` listing. Frame math via
  `timebase.ms_to_frame` only; rate emitted as integer timebase + ntsc flag.
  GAP-2 satisfied: VFR timebase → export refuses. Round-trip key
  `cd{job}_p{plan}_s{span}` on clip name + comments. CLI:
  `python -m cutdeck.xml_export --job-id N` (or `--plan-id N`), writes the file
  and flips plan status to `exported`. 3 acceptance tests in
  `tests/test_cutdeck_xml_export.py` (frame accuracy/contiguity, VFR refusal, no-
  keep refusal); phase0/1 + smoke unaffected (35 green). **The acceptance that
  actually matters is still open:** a real 29.97 file must import clean into
  Premiere, frame-accurate at the 60-min mark, audio linked, no offline media —
  verify on the real machine. Untested in the wild: stereo link layout and the
  Windows `file://localhost/C%3A/` pathurl form.
- Deferred within Phase 1: `cut_correction` table is **not** added yet (it is the
  Phase 3 flywheel artifact); only `cut_plan` exists. The `Label` contract type
  exists but is unused until the LLM classifier (Phase 5) produces judgement
  labels — rules currently emit cut reasons directly on spans.
