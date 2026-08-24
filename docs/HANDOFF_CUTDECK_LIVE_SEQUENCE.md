# HANDOFF — CutDeck: in-place live-sequence cutting (single-clip + multicam)

**For:** Claude Code, working in `Transcriber_v2` (repo: `B-transcriber`).
**Hardware:** RTX 3070, 8 GB VRAM. Windows host.
**Prime directive:** same as every CutDeck handoff — a false cut is worse than a missed
one. This mode is *more* dangerous than `xml_export.py`'s mode, because it edits an
existing project in place instead of writing a file the editor chooses to import.
Nothing in this handoff runs against real footage until Phase 0 (human-only) has passed.
**Discipline:** every phase ends with the full suite green plus the new acceptance tests
listed per task. Read `CLAUDE.md`, `IMPLEMENT_CUTDECK.md` §B, and `TODO_LEDGER.md` first.
Update `TODO_LEDGER.md` as phases land.

---

## Context: what this handoff is

`cutdeck/{contracts,segment,rules,plan,xml_export}.py` (Phases 0–2) build a `CutPlan` from
a single source media file and export it as a *new* FCP7 sequence for the editor to import.
That mode stays as-is — it's the right shape for "cut a fresh clip into a rough cut."

This handoff adds a second, deliberately separate mode: **cut an already-assembled
Premiere sequence in place** — razor + reverse-chronological ripple-delete, executed live
via generated ExtendScript, instead of building a new sequence for re-import. This is what
makes multicam workable: an editor syncs N camera angles into a sequence once, by hand or
via Premiere's own multicam tools; CutDeck never touches angle assignment, sync, or
effects — it only removes dead air from the existing vertical stack.

**Naming, on purpose:** `xml_export.py` = *new-sequence* mode. This handoff's module,
`cutdeck/jsx_export.py`, = *in-place* mode. Both consume the same `CutPlan` type. Don't
merge them into one code path — they have different risk profiles and different acceptance
bars (a bad new-sequence export just fails to import; a bad in-place edit corrupts a
project the editor may not have backed up).

### Two things this handoff deliberately does *not* build, because they already exist

**Silence detection is not new code.** `cutdeck/rules.py:silence_cuts()` already turns VAD
spans into padded cut regions using `cfg.pad_pre_ms` / `cfg.pad_post_ms` from
`config.yaml`. It takes **no transcript tokens** — `build_cut_spans(tokens=[], spans, ...,
cfg)` with fillers/repeats left at their default `False` yields a pure silence-removal
`CutPlan`. Do not write a parallel "silence interval" data shape or padding constants;
route in-place cutting through `build_cut_spans()` like every other CutDeck mode does.

**Single-clip and multicam are not two features.** The razor/ripple-delete loop iterates
`seq.videoTracks` / `seq.audioTracks` and skips locked/muted tracks — that loop is
identical whether the sequence has one V/A pair or ten synced multicam tracks. The only
difference between the two cases is *where the CutPlan's timestamps come from*:

| Case | Timestamp source | Offset math needed |
|---|---|---|
| Single clip, placed at sequence 0:00 | `ingest()` on the raw clip | none — media time = sequence time |
| Existing multicam sequence | audio mixdown exported *from the sequence itself* | none — mixdown is already in sequence time |

So `jsx_export.py` takes one `CutPlan` and doesn't need to know or care which case
produced it. Build one module, not two.

---

## PHASE 0 — sync-lock probe (human-only, throwaway copy)

**Do this before writing any code that will run against real footage.** Not a Claude Code
task — flagging it here so it isn't silently skipped, per this project's existing
convention for hardware/human-only steps.

On a **throwaway duplicate** of a real multicam sequence:
1. Enable sync lock on all tracks.
2. Manually razor + ripple-delete a short mid-sequence range via the Premiere UI.
3. Confirm every video and audio track shifted together with no residual gap or drift.
4. Repeat with sync lock *off* on one track, to confirm the failure mode is visible
   (a stray, unshifted track) rather than silent.

**Acceptance:** written confirmation (a line in `TODO_LEDGER.md` is enough) of whether
ripple-delete honors sync lock automatically, or whether `jsx_export.py` (Phase 2) must
assert sync lock is enabled before running and abort if not. This finding gates Phase 2's
acceptance criteria below — don't guess at it.

---

## PHASE 1 — `cutdeck/jsx_export.py`, pure generation (no Premiere dependency)

**Build:** a new module mirroring `xml_export.py`'s shape and CLI conventions.

```python
"""jsx_export.py — CutPlan → ExtendScript (.jsx) that razors + ripple-deletes CUT
spans from an *already-assembled* Premiere sequence in place (IMPLEMENT_CUTDECK.md
§B.7 exception — this is the 'in-place' mode; xml_export.py remains the
'new-sequence' mode; do not merge them).

Frame math goes through transcribe.timebase only, same rule as xml_export.py — no
float fps or float seconds ever reaches the generated script. Time objects in the
emitted JSX are set via .ticks (frame-exact, integer), never .seconds.

CUT spans are processed in descending src_in_ms order (reverse chronological) so
each ripple-delete's leftward shift never invalidates a timestamp not yet visited.
"""

from cutdeck.contracts import CUT, CutPlan
from transcribe.timebase import ms_to_frame

TICKS_PER_FRAME = 254016000000  # Premiere's fixed ticks-per-second / fps; confirm
                                 # against a real project export before relying on it
                                 # (see acceptance criteria — do not hardcode blind)


def to_jsx(plan: CutPlan, *, require_sync_lock: bool = True) -> str:
    """Deterministic string generation, no side effects. Testable with no live
    Premiere instance — assert on the generated text, same discipline as
    xml_export.py's tests."""
    cut_spans = sorted(
        (s for s in plan.spans if s.action == CUT),
        key=lambda s: s.src_in_ms,
        reverse=True,
    )
    # ... emit JSX: optional sync-lock assertion block (per Phase 0 finding),
    # then one razor-in/razor-out/ripple-delete block per span, using
    # ms_to_frame(plan.timebase, span.src_in_ms / src_out_ms) for exact frame
    # numbers converted to ticks.
```

**Acceptance:**
- `tests/test_cutdeck_jsx_export.py`: given a synthetic `CutPlan` (2–3 spans, mixed
  KEEP/CUT), the generated JSX contains one razor/ripple-delete block per CUT span, in
  descending `src_in_ms` order, with `.ticks` values that back-convert (via
  `frame_to_ms`) to the expected frame-snapped milliseconds — not the raw unsnapped ms.
- A CutPlan with zero CUT spans emits a script that does nothing (no-op is a valid,
  tested output, not an error).
- A `Timebase.is_vfr` plan raises the same way `xml_export.to_xml` does (GAP-2's refusal
  behavior) — in-place mode should not silently guess frame numbers on VFR sources either.
- If Phase 0 found sync lock is *not* automatic: `to_jsx()` emits a leading
  `app.project.activeSequence` sync-lock check that throws a clear alert and aborts
  before any razor call, rather than proceeding into a partially-cut, desynced sequence.
- Confirm the `TICKS_PER_FRAME` constant (or equivalent `Time` construction approach)
  against a real Premiere `Time` object before trusting it — this is exactly the kind of
  hardcoded-conversion-constant bug this project's own `CLAUDE.md` audits have found
  elsewhere (see `store.get_last_passing_eval()` filter gap, cue-width constant). Prefer
  `Time.setValue(frame_number, TIME_TICKS_PER_FRAME_CONSTANT_FROM_SEQUENCE_SETTINGS)` if
  Premiere's ExtendScript API exposes the sequence's own ticks-per-frame, over a literal.

---

## PHASE 2 — sequence-mixdown ingest path

**Build:** a thin CLI/function wrapper, not new pipeline code.

```
export mixdown (dialogue tracks) from live sequence   [human step or CEP-driven export]
        │
        ▼
transcribe.pipeline.ingest.ingest(mixdown_path, ...)      # existing, unmodified
        │  → AudioChunk[] / VAD spans
        ▼
cutdeck.rules.build_cut_spans(tokens=[], spans, duration_ms, cfg)   # existing, unmodified
        │  fillers_enabled / repeats_enabled stay at config default (False)
        ▼
CutPlan (sequence time, since the mixdown IS the sequence's own audio)
        │
        ▼
cutdeck.jsx_export.to_jsx(plan)                             # Phase 1
```

If multiple mic tracks need combining before VAD, mix them to one file first (ffmpeg
`amix` or Premiere's own export) — do **not** build a parallel multi-track VAD-union
pipeline. `ingest()` is single-file by design; respect that boundary.

**Acceptance:**
- `tests/test_cutdeck_sequence_mixdown.py`: a synthetic multi-silence WAV run through
  `ingest()` → `build_cut_spans()` produces a `CutPlan` whose CUT spans match hand-computed
  expected silence regions (reuse the existing `test_cutdeck_phase1.py` fixtures/pattern
  rather than inventing new silence-detection test data).
- Confirm no code path in this wrapper imports or requires an ASR engine — a
  transcription-free run must work end-to-end (silence-only removal), matching the "ASR is
  optional for this mode" finding above.
- If `cfg.fillers_enabled` or `cfg.repeats_enabled` is `True` in the active config, this
  path should either degrade to silence-only with a logged warning (no word timeline exists
  from a mixdown with no ASR pass) or explicitly require a `--transcribe` flag that runs the
  full ASR pipeline on the mixdown first — pick one and test it; don't leave it undefined.

---

## PHASE 3 — execution bridge (CEP panel / MCP `evalScript()`)

**Build:** wire `jsx_export.to_jsx()`'s output into a live Premiere session via the
file-based IPC + `evalScript()` pattern already scoped in prior notes
(`leancoderkavy/premiere-pro-mcp`-style CEP bridge). Keep the LLM **out of this loop** —
`CutSpan` → JSX → `evalScript()` is a pure mechanical path, same reasoning as the
reconciler's select-only invariant and the takes classifier never touching timecodes.

**Acceptance:**
- A round-trip test against a real (non-throwaway-critical) test project: generate JSX
  for a known small `CutPlan`, execute via the bridge, confirm the resulting sequence
  duration shrank by exactly the summed CUT-span durations, frame-exact.
- Confirm the bridge surfaces a Premiere-side script error (e.g. a locked track blocking
  ripple-delete) back to the caller instead of silently completing a partial edit.
- **Human-only, cannot be Claude Code's acceptance:** the editor personally verifies the
  test project's multicam sync and effects are intact after execution, on real footage,
  before this mode is trusted on anything that matters. Call this out explicitly in
  `TODO_LEDGER.md` as unresolved until it happens, same convention as the Phase 3
  round-trip flag in `HANDOFF_CUTDECK_WORDLEVEL.md`.

---

## PHASE 4 — CLI / config wiring

**Build:** `config.yaml` gains a `cutdeck.mode` (or CLI flag) distinguishing
`new_sequence` (existing `xml_export.py` path) from `in_place` (this handoff's path), so
`plan.py`/callers pick the right exporter without guessing from context. Small, mechanical —
last, because it depends on Phases 1–3 existing to wire together.

**Acceptance:** `tests/test_cutdeck_mode_selection.py` — given each mode value, the correct
exporter module is invoked; an unrecognized mode value raises rather than silently falling
back to one or the other.

---

## Sequencing rationale

Phase 0 first because everything downstream assumes an answer about sync-lock behavior
that nobody has actually confirmed — building Phase 1's abort-check logic without it
would be guessing. Phase 1 before Phase 2 because JSX generation is pure and CI-testable
with zero external dependencies; get it correct and tested before it has to interact with
real audio or a real bridge. Phase 2 before Phase 3 because the mixdown→CutPlan path
reuses fully-tested existing code (`ingest`, `build_cut_spans`) and just needs wrapper
tests — cheap to validate in isolation before adding the live-execution failure surface.
Phase 3 last among the "real" phases because it's the actual new risk (an external tool
editing a live project) and should only run against a `jsx_export.py` that's already
proven correct on synthetic plans. Phase 4 is bookkeeping and goes wherever, so it's last.

---

## Closing invariants (carry forward from prior CutDeck handoffs, apply here too)

- **No fake confidence values; no code-path changes to the reconciler or any existing
  `rules.py` function.** This handoff adds a new consumer of `CutPlan`, not a new producer
  of cut decisions.
- **Frame math has exactly one authority: `transcribe/timebase.py`.** `jsx_export.py`
  imports `ms_to_frame`/`frame_to_ms`; it does not reimplement rounding.
- **The reconciler/LLM stays out of the cut-application loop.** Same reasoning as
  B-transcriber's select-only invariant — `jsx_export.py` is a pure, deterministic
  function of a `CutPlan` it did not decide the contents of.
- **VFR refuses rather than guesses**, matching `xml_export.py`'s GAP-2 behavior.
- **Human-only tasks are called out, not silently omitted:** Phase 0's probe test and
  Phase 3's real-footage multicam verification are both flagged above and must land before
  this mode is used on footage that matters.
