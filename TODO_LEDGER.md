# TODO_LEDGER

Deferred work from the IMPLEMENT_CUTDECK.md build. Each entry has a trigger that
makes it due. Owner: build-discipline.

## Transcriber gaps (Part A)

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
- **Phase 2 — next.** `xml_export.py` (FCP7 XML out). The single acceptance that
  matters: a real 29.97 file imports clean into Premiere, frame-accurate at the
  60-min mark. Per §B.6, do this before the LLM (Phase 5) — it is the riskiest
  external interface. Note: GAP-2 (VFR refuse-to-export) is due here too.
- Deferred within Phase 1: `cut_correction` table is **not** added yet (it is the
  Phase 3 flywheel artifact); only `cut_plan` exists. The `Label` contract type
  exists but is unused until the LLM classifier (Phase 5) produces judgement
  labels — rules currently emit cut reasons directly on spans.
