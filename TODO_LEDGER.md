# TODO_LEDGER

Deferred work from the IMPLEMENT_CUTDECK.md build. Each entry has a trigger that
makes it due. Owner: build-discipline.

## CutDeck XML recut, `recut_sequence` mode (docs/HANDOFF_CUTDECK_XML_RECUT.md) — Phases 0-4 built, Phase 5 still human-only — 2026-08-29

**Correction to the handoff doc itself, done in the same session:** its "Why
this handoff exists" section repeated the retired "UXP has no split/razor
action" claim that issue #17's section above already corrects as false. The
handoff's real justification is current and different — the mark-and-apply
UXP panel is blocked by a host **panel-compositing bug** (nothing paints on
screen in Premiere 26.3.2.2, confirmed via DevTools, see
`uxp/spike18_split_probe/README.md`), not a split-capability gap. Fixed
in-place in the handoff doc; this mode is a second independent path with no
live-Premiere dependency at all, not a workaround for a UXP limitation.

- **Phase 0 (fixture) — DONE, 2026-08-29.** Real Premiere FCP7 export
  captured from the user's own project (`20260829 14-20-04.xml`): 1
  sequence, 32948 frames @ CFR 30fps, V1-V3 stacked angle clips + several
  stereo audio tracks (angle audio channels), no filters/transitions/nested
  sequences. Scrubbed via `scripts/scrub_fcpxml.py` (3 distinct source paths
  + 4 names neutralized, all numerics untouched) and committed as
  `tests/fixtures/cutdeck_recut_sample_scrubbed.xml`. This is the full
  ~18-minute sequence, not a hand-trimmed 30-60s clip as the handoff's ideal
  fixture describes — used here as a structural smoke fixture (parses and
  recuts without crashing, checked in
  `test_real_captured_fixture_recuts_without_crashing`), not for exact
  frame-level acceptance. A trimmed 30-60s fixture with a hand-verified
  ground-truth cut is still open if tighter frame-accuracy acceptance is
  ever needed.
- **Phase 2 (`cutdeck/xml_recut.py`, the transform) — DONE.** Surgical
  ElementTree rewrite, not model-and-regenerate. Handles all four cases from
  the handoff's table: a clip wholly after a cut shifts left; a clip
  straddling one or two cut edges is razored into 1-3 pieces (the common
  case — a full-length clip with a cut in the middle — splits into two,
  keeping the original id on piece 0 and cloning derived ids for later
  pieces); a clip wholly inside a cut is dropped; every track (locked,
  disabled, or not) shifts identically, no exemptions. Markers shift or, if
  inside a cut, are dropped and counted. Refuses (raises `XmlRecutRefusal`,
  naming the clip/timecode) on any `<transitionitem>`, nested `<sequence>`
  clip, or a `<filter>`-carrying clip a cut boundary lands inside — **known
  gap, not yet covered:** speed/time-remap clips have no dedicated check
  (none seen in the one real fixture so far; add one with a test before
  trusting this on footage that uses it). VFR refuses (GAP-2). **Links are
  dropped wholesale, not rewritten** — a split clip's cloned ids invalidate
  any `<linkclipref>` pointing at the original single id, and the handoff
  explicitly sanctions shipping an unlinked-but-correct sequence over a
  subtly wrong linked one; sync is guaranteed by the per-track frame shift
  regardless of links. 13 tests in `tests/test_cutdeck_xml_recut.py`
  (synthetic minimal xmeml for precise unit assertions + the real Phase-0
  fixture for a structural smoke test).
- **Phase 3 (CLI + duration guard) — DONE.** `python -m cutdeck.xml_recut
  sequence.xml mixdown.wav [--dry-run] [--job-id] [--config] [--db]`. Routes
  the mixdown through the existing, unmodified `sequence_mixdown.
  plan_from_mixdown` → `ingest()` path (no ASR import reachable, asserted by
  test) using the **XML's own sequence rate**, not a guessed/fabricated one.
  Hard-refuses (`DurationMismatch`) unless the mixdown's duration matches
  the XML's declared sequence duration within one frame — the "nastiest
  silent failure" the handoff calls out (an in/out-range or work-area
  mixdown export would land every cut at the wrong time, uniformly).
  `--dry-run` writes nothing. Output: `<input>_cut.xml` beside the source;
  sequence `<name>` gets ` — CutDeck` appended. 4 tests in
  `tests/test_cutdeck_xml_recut_cli.py`.
- **Phase 4 (mode registration) — DONE.** `cutdeck/export_mode.py` gains
  `MODE_RECUT_SEQUENCE = "recut_sequence"` → `xml_recut.recut`; its
  docstring states the signature is `(source_xml, plan) -> (xml, report)`,
  not interchangeable with the other two exporters' `(plan, media_path,
  ...)` shape. `config.yaml`'s `cutdeck.mode` comment updated to list all
  three values. `tests/test_cutdeck_mode_selection.py` extended, one new
  test.
- **Phase 5 (human gate) — IN PROGRESS, 2026-08-29. Two real bugs found and
  fixed via a live round trip on the user's own 18-minute sequence** (the
  actual fixture this session captured, not a synthetic one) — exactly what
  Phase 5 exists to catch, since neither was visible from the unit tests
  alone:
  1. **Duplicate full `<file>` listings.** `_clone_clipitem`'s deepcopy
     duplicated whatever `<file>` child the split clip carried; when that
     clip happened to be the one holding the source's ONE full listing
     (`<pathurl>`, `<media>`, ...) — the common case, since that's whichever
     clipitem for a source appears first and gets cut/split like everything
     else — every split piece got its own full copy (122 duplicate `file-1`
     listings observed on the real 123-cut run). Premiere resolved *video*
     fine against the duplicates but the sequence imported with **video
     playing and every audio track completely silent**. Fixed by
     `_dedupe_file_listings()`: a document-order pass collapsing every
     listing after the first full one per file id back to an empty stub —
     the FCP7 invariant the original document already held before cloning
     broke it.
  2. **Stale `<pproTicksIn>`/`<pproTicksOut>`.** Even after fix 1, audio was
     *still* silent. Root cause: Premiere's audio engine reads these two
     high-precision tick fields (a fixed 254016000000 ticks/sec, confirmed
     against the real fixture's own `pproTicksOut` value) for playback
     precision, separately from the frame-based `<in>`/`<out>` this
     transform was already updating on every trim. Leaving ticks untouched
     left them describing the clip's *original, untrimmed* source range —
     video played from the correct frame (frame math was always right);
     audio played from wherever the stale ticks pointed, which is exactly
     "plausible but silently wrong," the thing this whole handoff is
     designed to prevent. Fixed: `_frame_to_ticks()` recomputes both fields
     from the same trimmed frame numbers on every split/trim, via exact
     `Fraction` math (no float touches a tick value, same discipline as
     `transcribe/timebase.py`).
  Both are covered by regression tests
  (`test_split_clone_does_not_duplicate_the_full_file_listing`,
  `test_trim_updates_ppro_ticks_not_just_frame_in_out`) plus consistency
  checks folded into the real-fixture smoke test. **Confirmed working,
  2026-08-29: the editor re-imported the ticks-fixed file and audio now
  plays correctly** — Phase 5 human gate passed for the core transform.

- **`cutdeck/xml_audio_extract.py` — DONE, 2026-08-29, same session, prompted
  by the editor asking why a manual mixdown export is needed when the XML
  already names the source audio.** Builds the sequence-timeline mixdown WAV
  directly from the XML's own clipitems + source media via ffmpeg —
  `plan_from_mixdown`'s VAD input, without a Premiere export step. Reads a
  chosen reference audio track (default: first track with clips; a
  multi-mic sequence needs `--audio-track` to say which one carries
  dialogue), resolves each clip's source file via the same
  first-full-listing convention `_dedupe_file_listings` relies on, extracts
  each segment with `-ss`/`-to` (preferring `pproTicksIn`/`pproTicksOut` for
  sub-frame precision, matching xml_recut's own tick-precision fix above),
  and pastes into a silence buffer at the clip's timeline position. Disabled
  clips are skipped (silence), matching a real Premiere render. Explicitly
  trades fidelity for convenience: it reads only what the XML states, so any
  gain/EQ/pan/crossfade the real Premiere mix applies is invisible to it —
  fine for this project's real sequences (no effects, confirmed Phase 0),
  not a substitute for a manual export on a heavily mixed sequence.
  `cutdeck/xml_recut.py`'s CLI now takes `mixdown_wav` as optional: omit it
  and the CLI auto-extracts to a temp file instead. **Verified against the
  real 18-minute fixture**: auto-extracted run produced the same 123 cut
  spans (749098ms vs the manual mixdown's 749130ms — the small delta is
  track-A1-only vs Premiere's full mix, expected) and passed the same
  file-listing/ticks structural checks as the manually-mixed run. 4 tests in
  `tests/test_cutdeck_xml_audio_extract.py`, real ffmpeg on PATH (not
  mocked), same discipline as `tests/test_cutdeck_preview.py`. Not yet
  independently re-verified with a live Premiere import (the manually-mixed
  run already passed that gate on the same source XML and cut plan shape;
  the auto-extracted plan is structurally equivalent, but hasn't itself been
  through Phase 5).

## CutDeck mark-and-apply live-sequence cutting (issue #17) — supersedes the section below — 2026-08-25

**The ExtendScript/QE-DOM design in the section immediately below this one is retired.**
`cutdeck/jsx_export.py` and its test were deleted (issue #23); `cutdeck.mode`'s `in_place`
value is gone (unrecognized values still raise loudly, per `export_mode.py`'s existing
discipline). Replaced by a **UXP mark-and-apply** plugin: split every track at every cut
boundary and *disable* the region rather than deleting it (`cutdeck/mark_export.py`,
issue #19); one later Apply pass collects everything still disabled and ripple-deletes it
in one atomic `executeTransaction`. See issue #17's spec for the full design and issues
#18–#23 for the build breakdown.

**Corrections to the findings below, each wrong and each recorded here with its reason so
a future session cannot re-derive the wrong conclusion from these notes alone:**

- **"The UXP `premierepro` API has no split/razor action of any kind... a hard capability
  wall, not a translation/API-naming problem."** True for a single call, **false as a
  capability claim**. A split composes from primitives UXP does expose, all verified
  against Adobe's published type definitions (`adobe/premierepro-types`,
  `src/premierepro.d.ts`): `createCloneTrackItemAction` (duplicate) +
  `createSetStartAction`/`createSetEndAction` (trim sequence-time bounds) +
  `createSetInPointAction`/`createSetOutPointAction` (trim source-media bounds). Mark
  never needs the composed "split" as a single operation anyway — it disables the region
  between two boundary splits rather than removing anything, via
  `createSetDisabledAction`, which exists directly on both `VideoClipTrackItem` and
  `AudioClipTrackItem`.
- **"ExtendScript debugging via VS Code/Cursor's extension is the only viable live-test
  route."** Superseded, and unsound on 26.3 regardless of tooling — see the 26.3 QE
  silent-no-op hazard below.
- **Phase 0's unresolved sync-lock question (partial probe, inconclusive).** Does not need
  answering for the new design. Mark moves nothing — every split lands at an absolute,
  unchanging sequence timestamp, so there is nothing for sync lock to protect against
  during Mark. Apply's single `createRemoveItemsAction(sel, ripple=true, MediaType.ANY)`
  ripples every disabled item, video and audio together, in one call — there is no
  per-track loop for sync lock's behavior to matter to.
- **Phase 2's mixdown ingest path** (export a sequence mixdown, probe its timebase, ingest
  it). Superseded by `cutdeck/live_clip.py` (issue #20): the plugin sends a clip
  descriptor (media path, start time, in/out points, the sequence's own timebase) and
  Python reads the **original media file** directly — no render wait, full-quality audio,
  reuses existing media-sha256 job caching, and never triggers the fabricated-25fps-on-
  audio-only-probe trap `sequence_mixdown.py` documents.
- **The multicam justification** ("this is what makes multicam workable") in
  `docs/HANDOFF_CUTDECK_LIVE_SEQUENCE.md`. Contradicted by the editor's real project
  (`20260217 - ATIME DO DEE.prproj`, inspected directly): **zero** multicam clips across
  28 sequences. The real target is a single clip, or a stack of already-synced raw clips
  assembled by hand. Corrected in that document directly (issue #23); multicam and nested/
  layered edits are both explicitly out of scope for issue #17.

**New hazards discovered building this, recorded so they aren't rediscovered the hard
way:**

- **Premiere 26.3 silently ignores QE structural edits on some installations**
  (`ripple_delete`, `razor`/`split`) — per the `leancoderkavy/premiere-pro-mcp` project.
  This is *why* the ExtendScript/QE-DOM path was removed rather than merely deprecated: a
  module that reports success and does nothing is the exact failure mode CutDeck's "a
  false cut is worse than a missed one" directive exists to prevent.
- **Premiere 26.2 cold-start WebSocket permission bug:** an *installed* UXP plugin can
  fail with `"Permission denied to the url ws://127.0.0.1:<port>. Manifest entry not
  found."` even with `"domains": "all"` in the manifest, until UXP Developer Tool has
  loaded a dev build in the same session. Root cause is timing, not a missing permission —
  a reconnect loop is a day-one requirement for the plugin (issue #22), not later
  hardening. Load via UXP Developer Tool rather than a `.ccx` install until this is
  understood.

---

## [RETIRED, corrected above] CutDeck in-place live-sequence cutting (HANDOFF_CUTDECK_LIVE_SEQUENCE.md) — Phases 1/2/4 built, Phase 0/3 still human-only — 2026-08-24

Built and tested (all GPU-free, no live Premiere dependency):

- **Phase 1** — `cutdeck/jsx_export.py` (`to_jsx`): pure CutPlan -> ExtendScript
  generation. CUT spans processed in descending `src_in_ms` order; frame math
  goes through `transcribe.timebase.ms_to_frame` only. VFR refuses (GAP-2, same
  as `xml_export.to_xml`). No hardcoded `TICKS_PER_FRAME` — the generated JSX
  reads the sequence's own `seq.timebase` at runtime instead, sidestepping the
  "confirm the constant against a real Premiere Time object" risk entirely.
  `tests/test_cutdeck_jsx_export.py`, 5 tests.
- **Phase 2** — `cutdeck/sequence_mixdown.py` (`plan_from_mixdown`): thin
  wrapper routing a sequence's own audio mixdown through the existing
  `ingest()` -> `build_cut_spans(tokens=[], ...)` -> `build_plan()` path, no new
  pipeline code. `cfg.fillers_enabled`/`repeats_enabled` degrade to
  silence-only with a logged warning (chosen over a `--transcribe` flag — no
  ASR wiring exists in this path and none should, per the handoff). No
  `engines.*` import anywhere in the call path (asserted by test).
  `tests/test_cutdeck_sequence_mixdown.py`, 4 tests.
- **Phase 4** — `cutdeck/export_mode.py` + `config.yaml`'s new `cutdeck.mode`
  key (`new_sequence` | `in_place`, defaults `new_sequence`). Unrecognized mode
  raises rather than silently picking an exporter.
  `tests/test_cutdeck_mode_selection.py`, 5 tests.

**Still open, both explicitly human-only per the handoff — do not skip silently:**

- **Phase 0 (sync-lock probe) — partially run, 2026-08-24, inconclusive for
  the open question.** Human test on a throwaway duplicate sequence, via
  Premiere's **UI-driven** ripple-delete (right-click / Shift+Delete):
  (1) sync lock ON on all tracks → razor + ripple-delete shifted every track
  together, no gap, as expected. (2) sync lock turned OFF on one track only,
  same operation elsewhere → that track **still shifted with the rest**,
  same as case (1) — sync lock being off made no observed difference via the
  UI path. **Caveat, do not over-read this:** `jsx_export.py`'s generated
  script does not call Premiere's UI ripple-delete — it calls the QE
  (Quality Engineering) DOM directly (`qeTrack.razor()` +
  `item.remove(true, true)` per track, see `cutSpan()`). UI-level
  ripple-delete and QE-level scripted razor/remove are different code paths;
  Premiere's UI may honor/ignore sync lock differently than a QE script does.
  This result suggests sync lock's effect on ripple-delete may be weaker or
  absent even at the UI level, which if anything argues for keeping
  `to_jsx()`'s current conservative behavior — `require_sync_lock=True`'s
  `confirm()` gate, plus `cutSpan()` cutting every unlocked/unmuted track
  independently rather than relying on rippling to propagate. Do **not**
  relax either of those based on this result alone. What's still unconfirmed
  and blocks Phase 3: whether the QE-level `item.remove(true, true)` call
  itself ripples other tracks on its own (independent of sync lock), which
  would matter for the "does `cutSpan()`'s per-track loop double-cut"
  question below — only a live QE-script test (Phase 3) can answer that.
- **Phase 3 (execution bridge + live round trip)** — not built. `jsx_export.py`'s
  razor/ripple-delete calls target Premiere's QE (Quality Engineering) DOM,
  the standard community pattern for this operation, but the exact method
  names/signatures (`track.razor()`, `item.remove(true, true)`,
  `qeSeq.getItemAtTime()`) are **unverified against a real Premiere instance**
  — there is no CEP panel / MCP `evalScript()` bridge in this repo to test
  against, and building one plus the round-trip test both require live
  Premiere + real footage, which this session had no access to. One specific
  open question flagged inline in `jsx_export.py`'s `cutSpan()`: it cuts every
  unlocked track independently (conservative — doesn't assume sync lock
  propagates through a QE-level scripted edit) rather than cutting once and
  trusting sync lock to ripple the rest; if Phase 0/3 confirm QE ripples DO
  propagate across sync-locked tracks, that loop double-cuts and must change.
  Do not trust
  `jsx_export.py`'s output on footage that matters until: (a) the bridge
  exists, (b) the round-trip test in the handoff's Phase 3 acceptance passes
  on a throwaway test project, and (c) the editor has personally verified
  multicam sync/effects survive on real footage. Trigger: whenever CutDeck's
  in-place mode is actually about to be used.

**Live-test infra finding, 2026-08-24 — UXP cannot host this feature; do not
retry a UXP plugin without new evidence.** While setting up a Phase 3 manual
test session, confirmed the user's Premiere Pro build has dropped the classic
`File > Scripts` menu entirely (Adobe moved to UXP-based extensibility;
ExtendScript itself is still supported underneath, just through Sept 2026,
and only reachable via a CEP panel or an external debugger attach — not a
built-in menu). This raised the question of porting `jsx_export.py` off
classic ExtendScript/QE DOM onto Premiere's newer `require("premierepro")`
UXP API instead. **Investigated and ruled out:** per Adobe's own UXP API
reference (`SequenceEditor` class — `createCloneTrackItemAction`,
`createInsertProjectItemAction`, `createOverwriteItemAction`,
`createRemoveItemsAction`, `insertMogrtFrom*`, `getInstalledMogrtPath` are
the full method list) and confirmed live on Adobe's developer forums as of
mid-2026, **the UXP `premierepro` API has no split/razor action of any
kind** — razor/blade exists only in the legacy QE DOM, which is
ExtendScript-only. `createRemoveItemsAction` can ripple-delete an entire
existing `TrackItem`, but nothing in UXP can divide one continuous clip into
two at an arbitrary mid-clip time, which is the operation `jsx_export.py`'s
`cutSpan()` fundamentally depends on (razor in, razor out, then remove the
middle). This is a hard capability wall, not a translation/API-naming
problem — a UXP plugin cannot implement this feature at all today. **Do not
spend time porting `jsx_export.py` to UXP or building a UXP plugin for it
unless Adobe ships a split/razor action in a future UXP release** (check
https://developer.adobe.com/premiere-pro/uxp/changelog/ first). The correct
route to actually exercise `jsx_export.py`'s existing output against a live
Premiere instance is attaching a classic ExtendScript debugger (e.g. the
"ExtendScript Debugger" VS Code/Cursor extension, `adobe.extendscript-debug`,
sideloaded via `.vsix` since it's not indexed in Cursor's default
marketplace) directly to the running Premiere process — this was in progress
(debugger installed, session not yet launched) when this session ended.

## Structural debt carried through the 2026-08-13 architecture refactors (issues #3-#6)

The four behaviour-preserving refactors (cue splitter → `transcribe/cues/`,
speech windowing → `transcribe/audio/`, eval metric plumbing, `run_file` seams)
were gated on byte-identical behaviour, so pre-existing structural flags moved
with the code rather than being fixed. Running the structural reporter over the
changed files leaves 24 flags. None is an unaccounted new defect, but three
deserve a trigger:

1. **`cues/split.py::_split_greedy` — complexity 31, 123 lines.** Moved verbatim
   out of `engines/faster_whisper.py`; it was equally tangled there, just harder
   to find. It is now in a module named for what it does, which is the whole
   point of issue #3. **Trigger:** the next change to a cue-break *rule* (not a
   constant) — split the whitespace-break decision, the sentence-forcing and the
   length/gap fill into named steps first, then make the change. Do not
   restructure it speculatively: `cue_boundary_error_rate` is the user's daily
   pain and this function's exact behaviour is currently the baseline.

2. **`cues/split.py::_dp_split_segment` — complexity 17, 77 lines.** Same
   provenance. **Trigger:** HANDOFF_CEILING_BREAK §5 says to delete the losing
   algorithm after one release of A/B. If the DP re-probe (HANDOFF_ONE_ENGINE
   §1, due once the gold set grows) loses again, this whole function goes and
   the flag with it. Do not refactor a function that is a candidate for deletion.

3. **`pipeline/refine.py::refine` (97 lines) and `pipeline/run.py::run_file`
   (165 lines, down from 383).** Both are flagged on *length only* — neither is
   flagged for complexity, because both are flat sequences of named pipeline
   phases with no nesting. That shape is deliberate: CLAUDE.md's documented batch
   flow should be readable at a glance in the code, and breaking either into
   sub-functions would hide the phase order it exists to show. **Trigger:** if
   either grows a second level of conditional nesting, or if a phase is added
   that is not a single call, extract that phase.

Also flagged and deliberately *not* debt: the duplicated field lists in
`db/store.py` (`EvalRunRow` read shape vs `EvalRun` write record) are the
tradeoff issue #6 explicitly chose and documented — `EvalRunRow` carries
database-assigned `id`/`ran_at` that a writer must not supply. A test asserts
every `EvalRun` field is persisted, so the two cannot drift silently.


## Mid-word truncation / dropped-content bug — ROOT-CAUSED AND FIXED (VAD-span-seam cause), one residual mechanism still open — 2026-08-10

**User-reported, from real production output**: `F:\Me\Works\20260807 - โหน(หลัง)กระแส 155\5. EXPORTS\Audio_test.srt`
(13-min episode, `biodatlab/whisper-th-medium-combined` via `faster_whisper`,
production config) compared against the user's own Premiere hand-recut of the
first ~3 min (`hon trim 3 mins mine.srt`, ground truth for that span).

**Two related but distinct defects found, both content-loss, not just accuracy:**

1. **A ~4s window of real speech produced zero output.** Between
   `01:57.04` and `02:01.18` the hand-recut has two full utterances
   (`-ห้ามบุกรุก -ใช่ค่ะ` and `เมย์จ่ายไปทั้งหมด 380,000`, including a specific
   monetary figure); Audio_test.srt has nothing there at all — the cue before
   ends at `01:57.04`, the next cue starts at `02:01.18`. Not a wording error;
   the engine never emitted text for that audio.
2. **Systemic mid-word truncation, ~13 occurrences across the 13-min file**
   (roughly one per minute), always at a point where a chunk/batch boundary
   would plausibly fall:
   - Orphan 1-4-character fragment cues — the stray head or tail of a word,
     stranded as its own cue, immediately abutting (0.0s gap) the cue before
     it, but followed by a 1-8s gap before the next real cue (i.e. real
     speech in between was never decoded):
     `น` (97.12-97.24), `กับ` (165.72-166.10), `ยื` (180.82-184.20),
     `มั` (263.28-266.93), `ไค` (552.50-557.82), `ได้` (643.37-643.65),
     `เงิน` (703.72-710.90).
   - Cues that end mid-word with nothing recovering the rest:
     `ทยอยจ่าย 15 ธันว` (should continue "ธันวาคม…", 4.1s gap after),
     `แล้วอยากให้ผมมาร` (2.6s gap after),
     `คุณโอนเข้าที่บ` (likely "…บัญชี", 1.9s gap after),
     `ตำรวจเขาก็รับแจ้งคว` (likely "…ความ", 4.5s gap after),
     `แล้วเขาทำ` (cut off clean, 5.9s gap after).

**Hypothesis, not yet verified**: `ingest.py`'s VAD chunking (or
`BatchedInferencePipeline`'s internal batch splitting, since Engine A is
`prefers_whole_file=True`) is cutting mid-word rather than at a silence
boundary, and whatever falls on the far side of that cut — from a fragment
up to several seconds of following speech — is never stitched back in.

**Next step (not started)**: pull `EngineResult.raw["words"]` for this job
from the DB and check whether the audio in these gaps was even handed to the
engine, or inspect `ingest.py`'s VAD chunk boundaries directly against these
timestamps, to confirm chunk-boundary truncation vs. some other cause before
attempting a fix.

**RESOLVED (2026-08-10): root-caused directly against the real incident audio
(the file above still on disk), not just theorized. `ingest.py`'s VAD was a
red herring** — Engine A is `prefers_whole_file=True`, so `ingest.py`'s VAD
never touches this audio at all (per its own docstring); the real chunking
lives entirely inside `engines/faster_whisper.py`'s own `_vad_speech_spans` +
`_split_long_span` + `_recover_truncated_tail` machinery.

**Root cause, confirmed by direct redecode:** `faster_whisper.vad.
get_speech_timestamps` (the installed faster-whisper 1.2.1's own Silero
wrapper, read from source, not assumed) pads every detected speech chunk by
`speech_pad_ms` (400ms) on each side, and — critically — when the *real*
silence between two adjacent chunks is under `2*speech_pad_ms` (800ms), it
splits that silence evenly onto both chunks instead of leaving it as a gap.
The practical effect: **any real pause shorter than ~800ms between two VAD-
detected speech chunks is reported as an exact zero-width gap**, indistin-
guishable in the returned timestamps from "one continuous run of speech."
Verified against this file's own audio: `_vad_speech_spans` returns span#1
`[14.320-120.864]` and span#2 `[120.864-185.680]` touching at exactly
120.864s with zero reported gap. `_transcribe_batched` treated these as two
*fully independent* decode jobs — `_split_long_span`'s 4s window-to-window
overlap + `stitch.py` dedup only ever applied *inside* one span, never
*across* the seam between two spans. Direct proof: redecoding audio
110.0-127.0s as a single window (bypassing the span split entirely)
recovered the complete, correct utterance —
`ห้ามบุกรุก ใช่ค่ะ เมย์จ่ายไปทั้งหมด 380,000 บาท เขาคืนยอด 145,000...` —
matching the user's own hand-recut ground truth word-for-word in substance.
In the actual production run, this exact utterance was **entirely absent**
(cue ends `01:57.04`, next cue starts `02:01.18`, nothing between). Two more
of the reported orphan fragments (`ยื` at 180.82s, `ไค` at 552.50s) were
redecoded the same way and also recovered full coherent sentences instead of
the multi-second garbled/stretched artifact production emitted.

**Two-part fix, both in `transcribe/engines/faster_whisper.py`:**
1. **`_merge_contiguous_spans`** (new function): merges any two consecutive
   VAD spans whose reported gap is <= 50ms (float-rounding tolerance around
   the "0" the padding-merge produces) into one span *before* `_split_long_
   span` ever runs, closing the seam structurally rather than patching
   around it. A genuine pause (>= ~800ms real silence, which is the only
   case that can produce a *nonzero* reported gap given the padding-merge
   math above) is left untouched. Wired into `_transcribe_batched` right
   after `_vad_speech_spans`.
2. **`_recover_truncated_tail`'s stretch-detection loosened**: it used to
   also require the suspicious (>=1500ms-duration) last word to land within
   `_TRUNCATION_STRETCH_TOL_MS` (500ms) of the window's own end before
   attempting recovery — modeling only "stretched all the way to the
   boundary." Confirmed on this same real audio that this was too strict:
   the `ยื`/`ไค` fragments both had 1.3-3.9s of real, coherent, un-decoded
   speech trailing the suspicious word *before* the window's actual end —
   short of the old tolerance, so recovery never even attempted them. The
   gate is now just "is the last word's own duration suspicious" (existing
   `_TRUNCATION_TAIL_MS` check) plus the existing "is there >= 0.5s of real
   tail audio to redecode" check — both already-justified signals, no new
   tunable constant. `_TRUNCATION_STRETCH_TOL_MS` deleted; `win_dur_ms` param
   dropped from `_recover_truncated_tail` (no longer used by the check).

**Tests**: `tests/test_vad_span_merge.py` (new, 5 tests: exact-zero merge,
near-zero/float-rounding merge, a genuine pause preserved, a chain of 3+
touching spans, empty/single-span no-ops). `tests/
test_faster_whisper_truncation_recovery.py` updated for the new signature and
gate: added `test_recovers_when_suspicious_word_ends_well_short_of_window_end`
(the case that used to be silently skipped, now recovers) and `test_no_
recovery_when_tail_audio_too_short` (the boundary-proximity gate is gone, but
the pre-existing too-little-audio-to-redecode guard still correctly no-ops).
Full suite: **478 passed** (was 478 before too — same count, one test
replaced/renamed, one added net of the deleted-signature updates).

**Real-corpus harness gate** (`python -m transcribe.eval.harness --config
transcribe/config.yaml --db transcriber.db`, production run, not
`--experiment` — a genuine bug fix is meant to become the new baseline on a
pass, matching this repo's own harness convention): baseline `eval_run.id=58`
(`cer_thai 0.1751, wer_latin 0.8291, BER 0.5493, cue_BER 0.4043`) →
new `eval_run.id=59` (`cer_thai 0.1795 [0.0861,0.2833]`,
`wer_latin 0.8547 [0.5259,1.0797]` — printed `UNRESOLVED`, CI still contains
baseline, `BER 0.5568 [0.3305,0.8187]`, `cue_BER 0.4057 [0.2484,0.5538]`,
`cue_overlaps=0`, `cue_count_delta=+12`, `rtf=0.203`, **`passed=True`, no
confirmed regression on any gated metric**). All four point estimates moved
slightly worse (more/smaller cues from the now-different window boundaries
shift a few match points), but none crossed into confirmed-regression territory
— expected and acceptable for a fix whose entire purpose is recovering
previously-missing content the 8-clip gold set doesn't happen to contain.
`eval_run.id=59` is now the active passing baseline.

**End-to-end re-verified against the real incident file** (fresh pipeline
run, scratch DB, same config): the 4-second dropped utterance now transcribes
as `[116640–117660ms] ห้ามบุกรุก ห้ามบุกรุก`, `[118360–120900ms]
ใชสามแสนแปด`, `[120900–124880ms] เขาคืนยอดหนึ่งแสนสี่หมื่นห้าพันบาทมา
แล้วก็` — complete and correctly timed, matching the hand-recut ground
truth. 3 of the 4 investigated orphan fragments (`กับ`, `ยื`, `ไค`) now
transcribe as full coherent sentences with no truncation artifact; a fourth,
previously-unexamined region (`มั` at 263.28s) also resolved as a side effect
of a merge elsewhere shifting that span from the `normal` (<=25s, never
tail-recovered at all) path into the `long` (merge+split+recover) path.

**Not fixed, two residual issues found during this same re-verification —
different mechanisms, tracked separately, not blocking this fix:**
- **`น` at 97.12s is unchanged** — still a stray 120ms fragment followed by a
  ~1.08s gap. Its duration (120ms) is far under `_TRUNCATION_TAIL_MS`
  (1500ms), so it was never eligible for `_recover_truncated_tail`'s
  detection at all — this looks like a `stitch.py` seam-dedup miss at an
  internal `_split_long_span` window boundary (a different mechanism from
  root causes A/B above), or possibly a genuinely hard-to-hear word.
  **Trigger to revisit:** next time a user report or gold-clip audit turns
  up another short (<1500ms) isolated fragment at a window seam — worth a
  dedicated `stitch.py` investigation at that point, not worth chasing on
  one instance alone.
- **`ได้` at 643.37s is unchanged, but on inspection this was never content
  loss** — the surrounding text (`...ก็ยังไม่` / `ได้` / `เหมือนกันเลยครับ...`)
  is fully correct and complete; `ได้` is just an ordinary short word the
  greedy cue-splitter (`_group_words_into_cues_greedy`) isolated into its
  own one-word cue. A cosmetic cue-segmentation artifact, unrelated to this
  incident — not touched here.

**Secondary finding (unchanged, still open, still lower priority)** — the
vocabulary/substitution-error list below this entry — is a distinct accuracy
question from the content-loss bug just fixed; not addressed by this fix and
not attempted here.

**Secondary finding from the same comparison (lower priority, vocabulary
accuracy not content loss)**: recurring term-level substitution errors in the
first 3 min — `ธรณีสงฆ์`→`ตรณีสงฆ์`/`โดรณีสงฆ์` (3x), `ฉ้อโกง`→`ชอบโกง` (recurs
later in the file too), `โฉนด`→`ฉนด`, `น็อคดาวน์`→`นกดาว`, the show's own name
`โหนกระแส`→`โหนกัน`/hallucinated `เปรต` insertion, `ผู้เสียหาย`→`จะหาย`, plus
digit errors (`480,000`→`400,000`, `950,000`→`900,000`, a dropped `650,000`).
Candidates for `normalization.exception_lexicon` / bias terms once the
content-loss bug above is understood — accuracy tuning is secondary to fixing
outright dropped content.

## HANDOFF_THAI_BREAK_ATOMS Phase 1 — atoms layer built, vetoes deleted, harness green — executed 2026-08-06

**Built the inversion the handoff below specifies: `transcribe/thai/atoms.py`**
(`BreakLexicon`, `default_lexicon(config)`, `glue_atoms`, `snap_boundary_offsets`)
merges STYLE_GUIDE §7's four unsplittable units into indivisible break-atoms
*before* either cue splitter runs, so a break inside one is unrepresentable
rather than checked-and-vetoed at each break decision point.

- **Both splitters rewired** (`_group_words_into_cues_greedy`/`_dp` in
  `transcribe/engines/faster_whisper.py`): call `timed_tokens` → `glue_atoms`
  → operate on atoms. `_dp_split_segment`'s candidate-filtering loop is gone
  entirely — every inter-atom boundary is legal by construction, so
  `candidates = list(range(n_words + 1))` replaces the four-veto exclusion
  check. The greedy path's `_may_break_at_space` lost all four veto calls
  (digit/mai-yamok/reciprocal/classifier-demonstrative) down to just the
  pre-existing size-minima + `_remainder_stands_alone` checks — a break the
  loop can now propose is always already legal.
- **All four veto functions deleted** (`_numeral_break_veto`,
  `_mai_yamok_break_veto`, `_reciprocal_particle_break_veto`,
  `_classifier_demonstrative_break_veto`, plus `_next_real_word_texts`,
  `_CLASSIFIERS`, `_DEMONSTRATIVES`) — their linguistics moved into
  `atoms.py`'s `default_lexicon`/`BreakLexicon` docstrings and comments.
  Confirmed zero remaining call sites (`grep -rn "_break_veto"` → no matches).
- **Sentence-boundary snapping** (§2.3 item 1): `snap_boundary_offsets` moves
  a crfcut boundary that lands inside an atom's char span outward to the
  atom's start, so a sentence "boundary" crfcut finds mid-atom can't force an
  illegal split. Gap-within-an-atom (§2.3 item 2) and counters-count-atoms
  (§2.3 item 3) needed no new code — both fall out for free once a merged
  atom is a single `TimedToken` entry the loop can't see inside.
- **Config extension points wired**: `config.yaml`'s new `thai_atoms:` block
  (`extra_bind_left`, `extra_pairs`, `disable`) plus `unsplittable_terms`
  seeded from the existing `normalization.exception_lexicon` — read by
  `default_lexicon(config)`. `FasterWhisperEngine.__init__` gained a
  `config: dict | None = None` param (builds `self._lexicon` once, no
  GPU/model cost); `pipeline/run.py`'s `_safe_get_engine` threads the full
  config to `faster_whisper` specifically (not the other engines, to avoid
  disturbing their existing kwarg-fallback behavior).
- **Tests**: every pre-existing test in `test_faster_whisper_cues.py`,
  `test_cue_split_dp.py`, `test_cue_target_chars_config.py`,
  `test_cue_space_break.py` passes unchanged (47 tests, the incident's own
  fixtures). New `tests/test_thai_atoms.py` (29 tests): glue semantics per
  rule (space-absorbed `ๆ`, digit+unit across whitespace and fused, the
  classifier+demonstrative+noun triple, an exception-lexicon term pythainlp
  splits — `COVID-19` → `COVID-`/`19`), merged-atom timing/confidence/char_pos,
  verbatim-text (§2.3 item 5), `snap_boundary_offsets`, the gap-inside-atom
  invariant (§2.3 item 2), CutDeck's `words_from_pieces` staying word-level
  (§2.3 item 4, a regression guard, not a change), and **the property test**:
  across 8 fixture sentences × `target_chars` 5..60 × both algorithms, no cue
  boundary ever falls strictly inside an atom's `[start_ms, end_ms)` span —
  the invariant the old scattered-veto design could never state cleanly. Full
  suite: **409 passed** (was 380).
- **Harness gate, run for real** (this machine has the model/gold-set
  audio/GPU): `python -m transcribe.eval.harness --config transcribe/config.yaml
  --db transcriber.db --experiment` against baseline `eval_run.id=46`
  (`cer_thai 0.1751`, `wer_latin 0.8291`, `BER 0.5324`, `cue_BER 0.3904`).
  Result: `cer_thai 0.1751` (byte-identical), `wer_latin 0.8291`
  (byte-identical), `BER 0.5324` (byte-identical), `cue_BER 0.3925` (+0.0021,
  comfortably inside the run's own CI `[0.2243, 0.5492]`, which contains the
  baseline), `cue_overlaps=0`, `cue_count_delta=+13`, `passed=True`. Exactly
  the handoff's own prediction ("unchanged-to-slightly-improved... behaviour
  deltas should be edge cases") — the port changed nothing measurable except
  a handful of atom-boundary edge cases in cue counting.

**Acceptance met**: suite green, property test in place, zero veto call
sites remain in any splitter, harness run recorded against the real baseline.

**Deferred (unchanged from the handoff)**: Phase 2 (grow the lexicon —
spoken demonstratives นี่/นั่น/โน่น, classifiers beyond 5 entries, final
particles), Phase 3 (cue-legality lint in the harness, reusing the same
`BreakLexicon`), Phase 4 (POS-conditioned rules, evidence-gated). See
`docs/HANDOFF_THAI_BREAK_ATOMS.md` for the full spec.

## HANDOFF_THAI_BREAK_ATOMS Phase 2 — lexicon grown in three batches — executed 2026-08-06

Grew `transcribe/thai/atoms.py`'s default lexicon per §4's three concrete
gaps (gap 4, ambiguous post-verbals like เอง/ด้วย/directional
ไป/มา/ขึ้น/ลง, stays explicitly parked for Phase 4's POS-conditioning per
the handoff — not attempted here). Baseline throughout: `eval_run.id=46`
(`cer_thai 0.1751`, `wer_latin 0.8291`, `BER 0.5324`, `cue_BER 0.3904`).

- **Batch 1 (§4 item 1, commit `488ae3d`) — demonstratives grown to spoken/
  deictic forms + คนนึง/คนหนึ่ง.** `_DEMONSTRATIVES` gained นี่ นั่น โน่น
  นู่น นู้น alongside the written-register นั้น/นี้/โน้น; a new
  `_NUMERAL_ONE_FORMS = {นึง, หนึ่ง}` folds into the same `pair_bind_left`
  mechanism (คนนึง/คนหนึ่ง = "a/one NOUN", same atomic shape — STYLE_GUIDE §8's
  register choice is untouched, this only stops either spelling from being
  split). 7 new tests. Harness `--experiment`: **byte-identical** to baseline
  on all four gated metrics (`cue_BER 0.3925`, matching the Phase-1 port run
  exactly) — this 8-clip gold set doesn't currently exercise these forms, so
  it's a clean non-regression, not evidence of improvement yet.
- **Batch 2 (§4 item 2, commit `3062e2c`) — classifiers grown from 5 to 19.**
  Added เรื่อง แห่ง ลูก ใบ เล่ม คัน หลัง เครื่อง ชิ้น ชุด คู่ ครั้ง ที รอบ
  (the handoff's named set — a hand list beats an unshipped pythainlp-corpus
  derivation, per the handoff's own Phase 4 note). 6 new parametrized tests.
  Harness `--experiment`: again **byte-identical** to baseline — same
  "protection installed, not yet exercised by this corpus" story as batch 1.
- **Batch 3 (§4 item 3, commit `f8e5020`) — final/polite particles as
  `bind_left`.** New rule category `final_particle` (17 particles: นะ ครับ
  ค่ะ คะ สิ เลย ล่ะ แหละ หรอก เถอะ จ้ะ อ่ะ มั้ย ไหม เหรอ หรอ ป่ะ), own
  disable toggle, highest homograph risk of the three (เลย is also "at
  all"/"past"/a place name) — accepted per §2.4. **This batch actually moved
  the needle, and not for the better**: `cer_thai`/`wer_latin` unchanged, but
  `boundary_error_rate` moved `0.5324→0.5493` and `cue_BER` moved
  `0.3904→0.4043`. Both stayed `UNRESOLVED` under the CI-aware gate (both
  point estimates fall inside the baseline's own 95% bootstrap CI on this
  8-clip corpus — `gate_unresolved: boundary_error_rate,cue_boundary_error_rate`
  on `eval_run.id=56`), so the run is a formal pass, not a confirmed
  regression. Plausible mechanism, not confirmed: gluing เลย mid-utterance
  (e.g. ก็เลย "so") as well as utterance-finally shifts a handful of atom
  boundaries enough to push interpolated switch/cue-start timestamps outside
  the match tolerance elsewhere in the transcript — the accepted cosmetic
  cost of over-gluing (§2.4), not a text change or a bug (property test and
  full suite both stayed green: 441 passed).

**Trigger to revisit:** if a future production (non-experiment) harness run
on a grown gold set shows `boundary_error_rate` or `cue_boundary_error_rate`
as a **confirmed** regression (CI excludes baseline) and batch 3 is still in
the diff between the last-good baseline and that run, narrow
`final_particle`'s set (เลย is the prime suspect given its homograph load) or
gate it behind `disable` pending real Premiere-recut evidence — do not
silently revert the whole batch without checking which particle is actually
responsible first.

**Not done here (still open per the handoff):** Phase 3 (cue-legality lint
in the harness, reusing `BreakLexicon` so lint and splitter can't drift
apart), Phase 4 (POS-conditioned rules — only worth probing if a future run
shows over-gluing has a *confirmed*, not just unresolved, cost), and §4's
gap 4 (เอง/ด้วย/directional verbs — parked for Phase 4 by design, genuinely
ambiguous without POS context).

## HANDOFF_THAI_BREAK_ATOMS Phase 3 — cue-legality lint built, wired into the harness, real-corpus baseline recorded — executed 2026-08-06

Built the harness eyes §5 specifies: `transcribe/thai/lint.py::find_cue_legality_violations(cues, lexicon)`
scans a time-ordered cue list for the four illegal-break shapes named in the
handoff — `particle_initial` (a cue opens on `bind_left` material),
`digit_final` (a cue ends on a digit whose unit/classifier landed in the next
cue), `classifier_demonstrative_split` (a classifier ends one cue, its
matching demonstrative/"one" opens the next), `unsplittable_term_split` (an
exception-lexicon term's char span crosses a cue boundary) — reusing
`BreakLexicon` directly (no restated rules) so the lint can't drift from what
`glue_atoms` protects, per the handoff's own "same law as `db/store.py`
owning SQL."

- **Wired into `transcribe/eval/harness.py`**: runs on both hypothesis AND
  reference cues for every clip (§5 — a reference violation means the
  *lexicon* is wrong, not the hypothesis), prints per-clip detail whenever
  either side is nonzero, aggregates a corpus total, and records it as
  `eval_run.cue_legality_violations` — **descriptive only, no gate, no
  `METRICS_VERSION` bump**, exactly as specified. New DB column
  (`schema.sql` + `store._migrate` + `EvalRunRow` + `create_eval_run`).
- **Windows console fix found along the way**: printing a violation's Thai
  `detail` crashed the harness outright (`UnicodeEncodeError` — this
  machine's console is cp1252, not UTF-8). Added `harness._safe_print`
  (falls back to `errors="replace"` on a `UnicodeEncodeError`) so a
  console-encoding limitation can never crash a harness run — the DB row
  itself is unaffected (sqlite3/Python strings are already correct UTF-8;
  only the terminal echo was lossy).
- **Tests**: 16 unit tests in `tests/test_thai_lint.py` (one per rule ×
  fires/doesn't-fire/disable-toggle, empty/missing-text-key robustness, the
  §5 "reference is scanned the same way as hypothesis" contract) + 2 harness
  wiring tests (zero-violation run records 0; a synthetic particle-initial
  hyp cue is counted, printed, and **does not fail the run** — Phase 3 has
  no gate). Full suite: **459 passed** (was 441).
- **Real harness run** (`python -m transcribe.eval.harness --config
  transcribe/config.yaml --db transcriber.db`, no `--experiment` — this is a
  pure harness-instrumentation addition, it cannot change any gated metric):
  `cue_legality_violations=0 (reference=4)`, `passed=True`. **Acceptance
  met**: the hypothesis count is 0 on the real 8-clip gold set with the
  current lexicon, exactly as the handoff predicted (Phase 1/2 already
  proved byte-identical hypothesis output, so this was expected, not lucky).
- **Triaged the 4 reference-side hits (§5's "printed, not hidden"
  contradiction) — all 4 are false positives of the lint, not a lexicon
  defect, and the glue rule itself needs no change:**
  - `Bangkok Festivals_CT6_PeterWolf` cue 76: `'ครับ คือจริงๆ มันมีเสน่ห์มากฮะ'`
  - `Bangkok Festivals_CT6_Short2_D1` cue 30: `'ครับ ก็อาจจะมีหลายๆ องค์ประกอบ'`
  - `Short1` cue 8: `'ค่ะ'` (whole cue, next cue is an unrelated `'โอ้โห'` reaction)
  - the DCA/Wealthy40 clip, cue 13: `'นะครับ'` (whole cue, a standalone
    acknowledgment tag)

  In every case the human recut used a final particle as a **discourse-
  initial filler or a standalone interjection cue** — real, common spoken-
  Thai patterns STYLE_GUIDE §7's rule was never meant to forbid. The rule
  (and the `final_particle` glue behind it) targets a particle **stranded
  from the sentence it belongs to** (the incident's own `...ไปกิน` |
  `ครับ` shape); it says nothing about a particle legitimately *opening* new
  content or standing alone as its own reaction. `particle_initial`'s
  "cue's first token is `bind_left` material" heuristic can't see that
  distinction from bare cue text alone (no adjacency info to the *source*
  audio stream survives once a human has already hand-cut the SRT) — a
  known, accepted limitation of a text-only reference scan, not a signal
  that `final_particle` over-glues in production. Confirms Phase 2 batch
  3's own finding (byte-identical hyp output) from a different angle: the
  glue rule is not the problem; a cue-text-only lint heuristic just cannot
  fully replicate human pragmatic judgment, and was never expected to
  (§5 frames this exact scan as "free bug reports... triage them," not
  "auto-correct them").

**Acceptance met**: harness prints the count (hyp + reference, per-clip
detail on nonzero); real baseline run shows hyp=0 with the Phase-1/2
lexicon; the 4 nonzero reference cases were triaged per the handoff's own
instruction and traced to a lint-heuristic blind spot, not a lexicon
defect — no code change indicated.

**Trigger to gate `cue_legality_violations`** (§5: "gate it only after a
few runs show it stable at 0"): once a few more production harness runs
(ideally after the gold set grows past 8 clips) keep confirming hyp=0, add
it to the regression gate — a future nonzero hyp count would mean a new
break path forgot to consult `glue_atoms`/`BreakLexicon`, exactly the class
of defect this handoff exists to make structurally impossible to reintroduce.

**Not done here (still open per the handoff):** Phase 4 (POS-conditioned
rules — only worth probing if a future run shows over-gluing has a
*confirmed*, not just unresolved, cost), and §4's gap 4 (เอง/ด้วย/directional
verbs — parked for Phase 4 by design).

## HANDOFF_THAI_BREAK_ATOMS Phase 4 — POS-conditioned กัน probe built, run, and rejected on a confirmed real-corpus regression — executed 2026-08-06

**§6's own trigger had not fired.** Before starting, checked both disjuncts
against this ledger: Phase 2 batch 3's `boundary_error_rate`/`cue_BER`
regression stayed `UNRESOLVED` (CI contains baseline), never *confirmed*, and
Phase 3's lint found `cue_legality_violations=0` on hypothesis output — no
live gap-4 particle pain either. Per §6 ("only if...") and Phase 2/3's own
"not worth probing" notes above, Phase 4 was not due. **Executed anyway on
explicit user instruction to override the gate**, not on new evidence.

**Built exactly the probe §6 names for กัน** (the auto-derive-classifiers-
from-corpora half of §6 was not attempted — out of scope for one probe, and
Phase 2's own "a hand list beats an unshipped derivation" finding already
argues against it):

- `transcribe/thai/atoms.py`: `BreakLexicon` gained `pos_conditioned_bind_left`
  (a `bind_left`-shaped set whose glue only fires when the nearest preceding
  REAL token's `pythainlp.tag.pos_tag` (perceptron, ORCHID tagset) result
  starts with `V`). New `pos_tag_texts()`/`is_verb_tag()` helpers — one
  classification function, so `glue_atoms` and the lint can't restate it
  differently and drift (the same law the lexicon itself follows). New
  `thai_atoms.pos_condition_reciprocal` config toggle (default `false`):
  when `true`, `default_lexicon` moves `กัน` out of unconditional `bind_left`
  and into `pos_conditioned_bind_left` instead of adding a second rule —
  gluing behaviour for every other rule (mai yamok, classifiers, final
  particles) is untouched.
- `transcribe/thai/lint.py`'s `particle_initial` check extended to also fire
  for `pos_conditioned_bind_left` material, using the *same* `is_verb_tag`
  classification over the two adjacent cues' edge tokens — necessarily a
  narrower context window than `glue_atoms` sees (a whole segment's real
  tokens at once), a documented limitation in the same spirit as Phase 3's
  own particle-initial blind spots, not a new kind of drift.
- **Verified the mechanism actually discriminates the homograph it targets**
  (not just wired-but-inert): `เราทะเลาะกันเมื่อวาน` (reciprocal, ทะเลาะ tags
  `VACT`) still glues `ทะเลาะกัน` under the flag; `เขากันไม่ให้เข้ามา` (กัน =
  "block", เขา tags `PPRS`, a pronoun) does NOT glue under the flag but DOES
  glue (over-glues, `เขากัน`) with the flag off — the exact before/after §6
  predicts. 7 new tests in `test_thai_atoms.py`, 2 new in `test_thai_lint.py`
  covering both the glue and lint side of this. Full suite: **466 passed**
  (was 459).
- **Harness `--experiment` run, flag temporarily set to `true`**, vs
  production baseline `eval_run.id=57` (`cer_thai 0.1751`, `wer_latin 0.8291`,
  `BER 0.5493`, `cue_BER 0.4043`, `rtf 0.1961`): **byte-identical** on all
  four gated metrics, `rtf 0.198` (within run-to-run noise), `passed=True`.
  **Originally logged here as "not evidence either way — the gold set has
  zero กัน occurrences." That claim was wrong** (see the correction below,
  same day) — the check behind it had a bug, not the corpus.

**CORRECTION (same day, 2026-08-06):** the "zero occurrences" check iterated
gold JSON assuming a bare list; the real format is `{"tokens": [...]}` (a
dict — see `transcribe/eval/README.md`), so `isinstance(data, list)` was
`False` on every one of the 8 files and the scan silently matched nothing on
all of them, not just this corpus. Re-checked correctly (iterate
`data["tokens"]`): กัน **does** occur in the real reference transcripts —
`เหมือนกัน`/`ด้วยกัน`/`ต่างกัน` are single fused pythainlp tokens (never reach
the glue rule at all), and the standalone-token occurrences (`คบกัน`,
`คุยกัน`, `ประกอบกัน`, `อัปเดตพอร์ตกัน`, `ใกล้ๆกัน`) are almost all
verb-preceded — glue identically whether the flag is on or off, which is why
the harness run was still byte-identical even with the bug fixed (a
different, better-founded route to the same non-signal).

**But one real sentence is a confirmed negative result, not a null one:**
`Short2.json`'s reference contains `ทำแบบนี้กันทั้งนั้น` ("[everyone] does it
like this") — กัน here marks the verb phrase `ทำแบบนี้` as collective, but
its immediate predecessor token is the demonstrative `แบบนี้`
(`pythainlp.tag.pos_tag` → `DDAC`), not the verb `ทำ` itself. Fed straight
through `glue_atoms`: default (`false`) correctly produces the atom
`แบบนี้กัน`; `pos_condition_reciprocal=true` strands `กัน` as its own atom —
**reproducing, on real unremarkable creator speech already in the gold set,
the exact stranded-particle defect this whole handoff exists to prevent.**
Locked in as `test_pos_conditioned_reciprocal_strands_gan_after_a_demonstrative_real_corpus_case`
in `test_thai_atoms.py`.

**Decision (unchanged: flag stays `false`), but the reasoning is now
stronger.** This is no longer "insufficient evidence" — it's a confirmed
design flaw: a single-token POS lookback is too narrow for ordinary
VERB+OBJECT+กัน / VERB+DEMONSTRATIVE+กัน constructions, which are at least as
common in real speech as the "กัน = block" homograph the probe was built to
catch. **Do not re-enable `pos_condition_reciprocal` without first widening
the check** (e.g. "is there a verb tag anywhere in this clause," not just
"is the immediately preceding token a verb") and re-running this exact
fixture. The code, toggle, and tests stay in the tree — correct as an
opt-in, off-by-default building block, just not safe to flip on as designed.

**Gold-set growth for the actual gap that remains:** the "กัน = block"
homograph itself (§6's original motivating case) still doesn't occur
anywhere in the current 8 clips — that part of the original (wrong) finding
happens to still be true, just for a narrower reason. Testing it for real
needs a clip with that sense in it; per `SOURCES.md`'s contamination-guard
discipline, that has to be a real audio+human-transcript pair from the
user's own footage, not a fabricated one — flagged back to the user rather
than invented.

## Thai break-atoms — incident fixed (uncommitted), durable design handed off — 2026-08-06

**Incident (user-reported, from real Premiere output):** the greedy cue
splitter's length/gap-forced break consulted no protection rule and severed
bound Thai units — `ทะเลาะ | กัน` (verb + bound reciprocal particle) and
`ผู้หญิง | คนนั้น` (noun + classifier+demonstrative). Root cause: break-legality
was only enforced on the optional whitespace-break path, never on the forced
path.

**Fixed in this working tree (spot fix):** four veto functions in
`engines/faster_whisper.py` (`_numeral_break_veto`, `_mai_yamok_break_veto`,
`_reciprocal_particle_break_veto`, `_classifier_demonstrative_break_veto`) now
checked on all three break paths (greedy space, greedy forced, DP candidates);
regression tests in `tests/test_faster_whisper_cues.py`; rules recorded in
STYLE_GUIDE §7. Full suite 380 green 2026-08-06.

**Deferred (the durable fix):** `docs/HANDOFF_THAI_BREAK_ATOMS.md` — invert
veto-at-break-time into atoms-by-construction: a `glue_atoms` pass next to
`cutdeck/words.py::timed_tokens` driven by a declarative `BreakLexicon`
(data, config-extensible), consumed by every splitter so illegal breaks
become unrepresentable; then grow the lexicon (missing spoken demonstratives
นี่/นั่น/โน่น, classifier list beyond 5 entries, final particles นะ/ครับ/สิ…),
add a cue-legality lint to the harness, and optionally probe POS-conditioned
rules. **Trigger:** next session touching cue splitting, the CutDeck two-line
caption wrapper (STYLE_GUIDE §7 forbids building it without this), or the
next user report of a severed unit — whichever comes first. Judge every step
by cue_BER under the CI rule.

## HANDOFF_ONE_ENGINE Phase D — N-best self-ensemble built, probed, and closed — executed 2026-08-05

**Repurposed the reconciler (`align_hyp.py`/`reconcile.py`) for its one honest
single-engine use per the handoff's own framing (§6): pseudo-Engine-B as a
second decode pass through Engine A's own already-loaded residency, zero
second model load. Wiring is real, tested, and correct. Both probes on the
ladder were run for real against the grown 8-clip corpus (`eval_run.id=47`
baseline) and rejected on evidence — `self_ensemble.enabled` stays `false`,
production config unchanged. Per the handoff's acceptance criterion ("any
variant that improves wer_latin or BER with cer_thai held → activate;
otherwise record and close the reconciler track entirely"): closed.**

**What was built** (all gated behind `self_ensemble.enabled: false`, off by
default):
- `FasterWhisperEngine.transcribe()` gained optional `temperature`/`beam_size`
  overrides, threaded through `_transcribe_batched`/`_decode` — `None` (the
  default) omits both keys, byte-identical to pre-Phase-D behaviour. Not part
  of the abstract `Engine.transcribe(inp)` contract; every other engine's
  `transcribe(inp)` call site is unaffected.
- `pipeline/run.py`: when `self_ensemble.enabled`, the pipeline never
  instantiates or loads a real `engine_b` at all — Engine A's own residency is
  called twice (hypothesis A at `temperature_a`/`beam_size_a`, hypothesis B at
  `temperature_b`/`beam_size_b`) inside Engine A's existing load/unload
  bracket, then unloaded once. Both hypotheses flow through the *unmodified*
  `align_hyp.align` → `reconcile.reconcile` path as a genuine A/B pair — proven
  by a fake whole-file test engine (`tests/test_self_ensemble.py`) whose two
  disagreeing hypotheses ("hello" vs "halo") reach the reconciler and resolve
  to one of the two candidates, never invented text. A resume mid-way (crash
  exactly between `engine_a_done` and `engine_b_done`) reloads Engine A once
  to redecode hypothesis B rather than emitting `result_b_tokens=None`.
  Requires a whole-file Engine A — raises `ValueError` for a chunk engine
  (tested), since there is no per-chunk restitch path for a second hypothesis.
  Harness CLI: `--self-ensemble` / `--self-ensemble-temp-b` /
  `--self-ensemble-beam-b`, mirroring the existing `--engine-b` A/B-probe
  convention. 4 new tests (`tests/test_self_ensemble.py`), +1 existing-test
  fix (`tests/test_cue_target_chars_config.py`'s fake `_transcribe_batched`
  needed the new `temperature`/`beam_size` kwargs). Full suite: **371
  passed** (was 367).

  **Fresh-eyes review (`scrutinize`, isolated context, 2026-08-05) caught a
  real bug before this closed out**: `run.py` was reading
  `engine_b_name = config["engine_b"]` before `self_ensemble_cfg` and never
  overriding it — only the harness CLI's `--self-ensemble` flag relabeled it
  to `"self_ensemble"`. Toggling `self_ensemble.enabled: true` directly in
  `config.yaml` instead (bypassing the CLI) would have silently mislabeled
  `job.engine_b`/`engine_result.engine_name` with whatever the raw config
  string said, AND `store.find_resumable_job` keys purely on
  `(media_id, engine_a, engine_b, pipeline_version)` — none of which encoded
  self-ensemble state — so a self-ensemble job and a genuine passthrough job
  for the same media could have cross-resumed into each other's cached
  `engine_result` rows. **Fixed**: `run.py` now derives
  `engine_b_name = "self_ensemble"` itself whenever `self_ensemble.enabled`,
  independent of the caller and of whatever `config["engine_b"]` literally
  says — the harness CLI's own relabeling is now redundant but harmless.
  Covered by a new resume-mid-phase test
  (`test_self_ensemble_resume_mid_phase_redecodes_hypothesis_b`) that
  deliberately sets a mismatched `engine_b: "passthrough"` in its config and
  asserts the stored job identity is `"self_ensemble"` regardless, plus that
  a crash landing exactly between `engine_a_done` and `engine_b_done`
  correctly reloads Engine A once to redecode hypothesis B rather than
  resuming with `result_b_tokens=None`. Review also confirmed: the
  production path (`self_ensemble.enabled: false`, the default) is
  byte-identical to pre-Phase-D behaviour; the no-generation invariant
  (`reconcile.py`'s `ReconcilerViolation` guard) is untouched and holds; and
  every quantitative probe number below was independently re-verified
  against `eval_run` rows in `transcriber.db`.

**Probe (a), "same params, temperature 0 vs 0.2" — REJECTED, architecturally
inert, not a close call.** `FasterWhisperEngine` uses
`BatchedInferencePipeline` (the ~3x-realtime VAD-batched decode path, not the
sequential per-segment path) for speed. Read against the installed
faster-whisper 1.2.1 source: `generate_segment_batched` always calls
`ctranslate2.Whisper.generate(beam_size=options.beam_size, ...)` — beam search
(`beam_size=5`, production) is deterministic search, not sampling, and
CTranslate2's `sampling_temperature` has no effect while `beam_size>1`.
Confirmed empirically two ways: (1) a direct hypothesis-A-vs-B comparison on a
real gold clip (`Short1.mp3`, 36s, 14 cues) at temperature 0.0 through 1.0 —
byte-identical token text and confidences at every temperature; (2) the full
harness run (`--self-ensemble --experiment`, 8 clips) reproduced
`eval_run.id=47`'s point estimates to the last decimal
(`cer_thai=0.1751, wer_latin=0.8291, BER=0.5324, cue_BER=0.3904`) — zero
reconciler disagreements were possible, so zero metric movement was possible.
This is not a statistical loss, it's a proof that the probe as literally
specified cannot produce a self-ensemble signal through this pipeline.

**Adapted probe, beam_size_b=1 (greedy) vs beam_size_a=5 (production) —
REJECTED, real diversity but every metric worse.** Since temperature alone is
inert at `beam_size>1`, `beam_size` was added as a second override (still same
residency, still zero second load) — CTranslate2's `generate()` does support
`beam_size=1` greedy decode, which is genuinely different from beam-5 search
(confirmed on the same clip: real content differences, 16 cues vs 14, not just
re-timed boundaries; also confirmed `sampling_topk` defaults to 1 in this
call path, so temperature is *still* inert even at beam_size=1 — greedy is
fully deterministic, three different temperatures produced identical greedy
output). Harness run (`--self-ensemble --experiment`, `beam_size_b=1`
default) against the same 8-clip corpus: **every single gated metric moved
in the wrong direction** — `cer_thai 0.2348` (vs 0.1751), `wer_latin 0.8846`
(vs 0.8291), `BER 0.6474` (vs 0.5324), `cue_BER 0.4301` (vs 0.3904). All four
are CI-*unresolved* (baseline still inside the 95% band, so `passed=True`,
no hard gate failure) rather than confirmed regressions, but "unresolved" is
not "promising" — there is no metric where the point estimate moved the right
direction at all. Reading it honestly: greedy (`beam_size=1`) decode is a
categorically weaker hypothesis than beam-5 search, and the reconciler
sometimes routes to it on disagreement — the "second hypothesis" is net-harmful
information to blend in, not a source of real agreement signal. Tuning
`beam_size_b` toward 2-3 would only trade some of this quality loss for less
diversity, converging back toward probe (a)'s no-op; not worth a further
harness run without new evidence this trade has a sweet spot.

**Probe (b), "beam-5 top-1 vs top-2" — NOT attempted, scoped and declined.**
CTranslate2's `Whisper.generate()` does expose `num_hypotheses` (verified via
its installed Python binding's docstring) for real N-best beam candidates at a
fixed beam width — the architecturally correct way to get two comparable,
both-beam-5-quality hypotheses. But faster-whisper's public
`BatchedInferencePipeline`/`WhisperModel` API never threads `num_hypotheses`
through `generate_segment_batched` — getting it would mean bypassing
faster-whisper's transcribe() entirely and reimplementing its batched decode
+ word-timestamp cross-attention alignment (`add_word_timestamps`/
`find_alignment`, currently only reachable via the *sequential*, non-batched
path) directly against the raw CTranslate2 model. That is a new subsystem,
not a probe — disproportionate given probe (a) and its adaptation both failed
cleanly, and every prior Engine-B-shaped decorrelation idea in this repo
(funasr, typhoon_rt, whisper_multi, qwen3_asr, both LLM-reconciler rounds) was
also rejected. Not ruled out forever — just not worth building blind; would
need a specific new reason to expect real-beam N-best to behave differently
from the two failure modes just measured (no diversity vs. harmful diversity).

**Probe (c), Ollama round 3 (7B, few-shot)** — moot: gated on (a)/(b)
producing real same-scale candidates for the LLM to judge, which neither did.

**Verdict: reconciler track closed per the handoff's own criterion.** The
Engine Contract, `align_hyp.py`, `reconcile.py`, and the self-ensemble wiring
all stay in the codebase (sound plumbing, proven correct, cheap to keep per
§8 housekeeping) — but no further probing is planned without new evidence.
`self_ensemble.enabled: false` in `config.yaml`, unchanged production config.
See `docs/HANDOFF_ONE_ENGINE.md` §6/§9 for the original spec and standing
rejections this joins.

## HANDOFF_ONE_ENGINE Phase C step 1 — fine-tune data engine built — executed 2026-08-05

**`tools/make_finetune_set.py`** (HANDOFF_ONE_ENGINE.md Section 5 item 1):
ingests (audio, hand-recut SRT) pairs — the Premiere recut-loop artifact — and
DB `correction` rows into a JSONL training manifest of (audio slice, corrected
text) utterances, ready to feed a future LoRA fine-tune of the Phase B winner
(`biodatlab/whisper-th-medium-combined`).

- `from-srt <srt> --audio <path> --source <name>`: reuses `srt_io.parse_srt`
  (the same path `make_gold.py` uses), slices audio to cue spans via
  `pipeline.ingest.load_audio` + `soundfile`, appends to
  `transcribe/finetune/manifest.jsonl`.
- `from-corrections --db <path>`: joins `correction` -> `job` -> `media` ->
  `token` to recover each correction's audio span and uses
  `corrected_text` as the label (deletion corrections with empty text are
  skipped — nothing to train on); a job's media whose source is on disk is
  decoded once and reused across all of that job's corrections.
- **Contamination guard is mechanical, not a convention**: every ingest call
  takes an explicit declared source name and `find_contamination()` parses
  `transcribe/eval/goldenset/SOURCES.md`'s table live and refuses (raises
  `ContaminationError`, writes nothing) on a match — case-insensitive
  substring match against gold-clip names and backtick-quoted source-video
  tokens, both directions, per SOURCES.md's own "assume distinct source,
  verify" default. `from-srt` fails closed before any decode/write;
  `from-corrections` skips the contaminated job and keeps processing others
  (it walks many jobs unattended, so one contaminated job must not abort the
  rest), returning the skip count rather than raising. This is Phase A.4's
  standing trigger ("Phase C tooling being built") discharged.
- `stats`: reports total utterances/minutes collected so far against the
  handoff's thresholds (`MIN_COLLECT_MINUTES=45`, `TARGET_MINUTES=60`,
  arXiv 2604.06507 lineage) — `keep-collecting` / `usable-but-below-target` /
  `ready`.
- 13 new tests (`tests/test_make_finetune_set.py`): gold-sources parsing
  against the real `SOURCES.md`, contamination match/no-match/too-short-needle
  cases, both ingest paths (including the contaminated-job skip and the
  empty-text-deletion skip), stats verdict boundaries. Full suite: **357
  passed** (was 344).

## HANDOFF_ONE_ENGINE Phase C step 2 — recut-archive inventory — probed 2026-08-05, 0.63 min collected

**Three candidate sources probed against the real tool; three-for-three
disqualified, one usable clip found on the fourth:**

1. `SOUND FINAL mine.srt` / `SOUND FINAL.mp3` (`20260625 - Bangkok Festivals -
   CT6`) — **refused, contaminated**: this is the exact raw interview already
   frozen as three gold-set clips (`Short1_D5`/`Short2_D1`/`PeterWolf`).
2. `หายไปนานเลย...Wealthy 40 - [j6IECK-D-D8].th.srt` (yt-dlp download) —
   **refused, contaminated** (same source video as the Wealthy40 gold clip,
   full video excluded per the hold-out rule regardless of time range) **and**
   not a hand-recut anyway — inspected the content: rolling overlapping
   timestamps and mid-word script-mixing garbage (`คekสำคัญ`) are the
   signature of a raw YouTube auto-caption, not corrected supervision.
3. `Short1/2/3 mine.srt` (`20260713 - CFD 90`) — **refused, contaminated** —
   not a name coincidence: sha256-verified byte-identical to the gold set's
   own `Short1`/`Short2`/`Short3` audio. `transcribe/eval/goldenset/SOURCES.md`
   updated with this confirmed provenance (was previously "unconfirmed,
   assume independent") and a new exclusion group for the whole
   `20260713 - CFD 90` project folder.
4. `Short4.mp3` (same CFD 90 folder, no gold-set counterpart) — clean.
   Transcribed fresh via `transcribe.pipeline.run.run_file` +
   `align_force.export_srt` (job_id=27, 24 cues) so the user could recut it;
   user hand-corrected and returned `Short4 mine.draft.srt`. Ingested via
   `from-srt --source CFD90_Short4_20260713`: **+24 utterances, 0.63 min** —
   the first real (non-dry-run) manifest entries. `stats` verdict:
   `keep-collecting` (need ~70+ clips at this rate to clear the 45 min floor).

**Reading it honestly**: the existing 8-clip gold set already consumed a
disproportionate share of the user's best-organized recut archive (an entire
interview + an entire short-form project's first three clips). Real Phase C
progress depends on recuts from sources *outside* Bangkok Festivals CT6,
Wealthy40 DCA, and CFD90-Short1-3 — an ongoing collection process, not a
one-session inventory.

## HANDOFF_ONE_ENGINE Phase C step 3 — LoRA training pipeline built, wiring-proof dry run only — executed 2026-08-05

**User explicitly asked to "finish phase 3" despite the 0.63 min collected
(§ step 2) being far below the handoff's own ~45 min floor. Resolved via
question to the user: build + wire the real training pipeline, but treat any
run against current data as a dry run proving the mechanism only — never a
real Phase C candidate, never pushed through the eval harness.**

**`tools/finetune_lora.py`**: HF `transformers` + `peft` LoRA on the Phase B
winner (`biodatlab/whisper-th-medium-combined`), per the handoff's recipe —
`target_modules=[q_proj, v_proj, out_proj, fc1, fc2]`, first 3 encoder layers
excluded from adapter injection (`build_exclude_regex`, enumerates exact
layer indices via `peft`'s `exclude_modules` + `re.fullmatch`, verified
against installed peft 0.19.1 source rather than assumed from memory), r=8/
alpha=16/dropout=0.05, AdamW via `Seq2SeqTrainer`. Reads
`transcribe/finetune/manifest.jsonl` (the step-1 data engine's output),
decodes+resamples audio, tokenizes labels, pads with a `DataCollator` that
masks label padding to -100.

- **Data-floor guard is mechanical**: `check_data_sufficiency()` calls
  `tools.make_finetune_set.compute_stats` and refuses to run for real
  (raises, writes nothing) below `MIN_COLLECT_MINUTES` unless `--dry-run` is
  passed. A dry run caps training to 2 steps and writes a `DRY_RUN.md`
  marker beside the saved adapter so a future session can't mistake it for a
  real candidate.
- **Manually dry-run for real** (not just unit-tested) against the 24-
  utterance / 0.63-min manifest from step 2: loaded the actual
  `biodatlab/whisper-th-medium-combined` checkpoint, applied LoRA (7,077,888
  / 770,935,808 params trainable, 0.918%), ran 2 optimizer steps
  (`train_loss=2.539`), saved a real PEFT adapter to
  `transcribe/finetune/lora_out/` with `DRY_RUN.md` alongside it. This is the
  wiring proof the user asked for — the pipeline is real and runs end to
  end; the resulting checkpoint is explicitly not evidence of anything about
  model quality.
- Output is a saved adapter only — `merge_and_unload()` +
  `ct2-transformers-converter` (the rest of the handoff's "zero adapter code
  changes" promise) is unbuilt, deferred until a real (non-dry-run) training
  run produces an adapter worth promoting.
- `peft>=0.19.0` and `datasets>=5.0.0` added to `requirements.txt` (both were
  already present in this venv; not previously declared). `transcribe/finetune/data/`
  and `transcribe/finetune/lora_out/` added to `.gitignore` (audio slices and
  checkpoints are regenerable/user-supplied; `manifest.jsonl` stays tracked
  as a small provenance index).
- 10 new tests (`tests/test_finetune_lora.py`): manifest load/missing/empty,
  the layer-freeze regex (including a double-digit-layer-count case that a
  naive char-class range would get wrong), the data collator's label-padding
  contract (via lightweight `BatchFeature`/`BatchEncoding` fakes — no real
  model weights loaded in the automated suite, matching this repo's existing
  convention for ASR-adapter tests), and both branches of the data-floor
  guard. Full suite: **367 passed** (was 357).

**Still open, unchanged**: real training waits for real data. Steps 4-5
(synthetic code-switch augmentation, gate against `eval_run.id=47`) do not
start until a non-dry-run training run exists, which does not start until
`tools/make_finetune_set.py stats` clears `MIN_COLLECT_MINUTES` — collection
is the active bottleneck, not tooling.

## HANDOFF_ONE_ENGINE Phase B — engine bake-off re-probed on the grown 8-clip corpus — executed 2026-08-05

**All 3 candidates re-run against `eval_run.id=47` (the fresh Phase A CI
baseline) with CI-aware verdicts (`--experiment`, never became the
baseline). Verdict: unchanged from the 5-clip probes — production
`faster_whisper`/th-medium still wins on every gated signal, now with a real
statistical read instead of a bare point estimate.**

| Candidate | `eval_run.id` | `cer_thai` (95% CI) | `wer_latin` (95% CI) | `BER` (95% CI) | `cue_BER` (95% CI) | `rtf` | Verdict |
|---|---|---|---|---|---|---|---|
| **th-medium (baseline, `id=47`)** | 47 | 0.1751 [0.0845, 0.2777] | 0.8291 [0.4848, 1.0415] | 0.5324 [0.2873, 0.8289] | 0.3904 [0.2163, 0.5526] | 0.133 | incumbent |
| Typhoon Whisper Large-v3 | 48 | 0.2468 [0.1517, 0.3659] — *unresolved* | 0.9530 [0.8281, 1.0000] — *unresolved* | **0.8792** [0.7526, 1.0000] — **confirmed regression** | **0.6462** [0.5879, 0.6885] — **confirmed regression** | 0.350 | **REJECTED** |
| Pathumma Whisper Large-v3 | 49 | 0.1918 [0.1371, 0.2600] — *unresolved* | 0.9188 [0.7515, 1.0000] — *unresolved* | 0.6697 [0.5229, 0.8868] — *unresolved* | **0.6245** [0.5510, 0.6846] — **confirmed regression** | 0.349 | **REJECTED** |
| Qwen3-ASR-1.7B (as Engine A) | 50 | 0.2167 [0.1301, 0.3503] — *unresolved* | **0.9615** [0.8763, 1.0000] — **confirmed regression** | **0.8866** [0.7730, 1.0000] — **confirmed regression** | **0.8237** [0.7764, 0.8559] — **confirmed regression** | 0.321 | **REJECTED** |

"Unresolved" = point estimate crossed the regression band but the run's own
bootstrap CI still contains the baseline value (Phase A §3.1 rule) — a real
signal, not noise-proof, just not yet distinguishable from resampling noise
on 8 clips. "Confirmed regression" = the CI excludes the baseline too.

**Reading it honestly:**
- **Typhoon/Pathumma**: same qualitative story as the old 5-clip verdict
  (HANDOFF_CEILING_BREAK §4) — both large-v3 fine-tunes lose on cue timing
  (`cue_BER`) hard enough to be a *confirmed* regression even under the new
  CI-aware gate, not just a point-estimate loss. Typhoon additionally
  confirms a real BER loss now that the corpus has real switches to measure
  against (old 5-clip run scored BER 1.0000 for a different reason — zero
  switches found at all — this 8-clip run's 0.8792 is a genuine, still-bad,
  code-switch-detection result). This is now the **third** time a
  published-SOTA Whisper large-v3 lineage model has lost to th-medium on
  this repo's specific corpus (turbo, Typhoon, Pathumma) — the
  normalization-policy-divergence hypothesis (HANDOFF_CEILING_BREAK §7) is
  still the prime suspect and still unverified, but the pattern is now
  three-for-three across two corpus sizes.
- **Qwen3-ASR as Engine A**: rejected exactly as the handoff's own caveat
  predicted — "per-word timestamps would need the forced-align path... this
  may disqualify it on cue_BER alone, which is itself a valid verdict."
  `cue_count_delta=-187` (vs th-medium's +11): the adapter's `max_span_s=8.0`
  span-capped internal VAD produces far coarser cues than th-medium's
  phrase-cue granularity, and `cue_BER 0.8237` is now a *confirmed*
  regression, not a close call. `wer_latin`/`BER` also confirmed-regress —
  consistent with the prior Engine-B-track finding (TODO_LEDGER 2026-08-05,
  "Qwen3-ASR span-granularity fix") that it transliterates code-switched
  English into Thai script rather than preserving it; as a sole Engine A
  with no th-medium candidate to fall back to, that flaw is fully exposed
  instead of partially masked by the reconciler.
- **`rtf` note (descriptive, not gated)**: all three candidates run at
  ~0.32-0.35 (still ~3x realtime), vs th-medium's 0.133 (~7.5x) — the large-v3
  models are ~2.6x slower even before considering they lose on accuracy too.

**Named fine-tuning base checkpoint (Phase C, per HANDOFF_ONE_ENGINE §4 item
5): `faster_whisper` / `biodatlab/whisper-th-medium-combined`
(`models/whisper-th-medium-ct2`)** — the incumbent wins cleanly, so Phase C
fine-tunes th-medium, exactly the "stated honestly" expected outcome in the
handoff. `config.yaml`'s `engines.faster_whisper` comment block updated with
this re-probe; production config unchanged.

Acceptance met: one table, all 4 candidates × all gated metrics × CI, named
checkpoint. See HANDOFF_ONE_ENGINE.md §4/§10 for what's next (Phase C).

## HANDOFF_ONE_ENGINE Phase A — gate CIs/RTF + contamination guard — executed 2026-08-05

**§3 items 1, 2, 4 DONE; item 3 (noisy/hard gold clip) still open, needs the
user's audio — see below.**

1. **Bootstrap CIs in the harness** (`transcribe/eval/metrics.py`:
   `bootstrap_ci`/`_resample_aggregate`/`CI_METRICS`): 95% percentile
   bootstrap over clip-level resampling (1000 draws), one band per gated
   metric (`cer_thai`, `wer_latin`, `boundary_error_rate`,
   `cue_boundary_error_rate`). Stored on `eval_run` (8 new nullable `*_ci_lo`/
   `*_ci_hi` columns, idempotent `_migrate` ALTERs — no `METRICS_VERSION`
   bump, this is descriptive, not a metric-definition change).
2. **Gate rule changed**: a point-estimate regression whose CI still contains
   the baseline value is recorded in the new `eval_run.gate_unresolved`
   column (comma-separated metric names) and printed as `UNRESOLVED`, instead
   of hard-failing the run. Only a regression whose CI *excludes* the
   baseline still fails. `overlapping_cues` stays a hard, CI-independent
   invariant, unchanged.
3. **RTF recorded** (`eval_run.rtf`, wall-clock decode time ÷ total gold-set
   audio duration via `ingest.load_audio`) — descriptive only, `NULL` when
   duration can't be probed (synthetic test paths), not gated until a speed
   floor is chosen.
4. **`transcribe/eval/goldenset/SOURCES.md`** added — reconstructs clip
   provenance from `git log` (no gold JSON stores a source field). Confirms
   `Short1_D5`/`Short2_D1`/`PeterWolf` are the same raw interview
   (`SOUND FINAL.mp3`) via the `PeterWolf` commit's explicit overlap ranges;
   every other clip is unconfirmed-but-treated-as-independent. Phase C's
   fine-tune data engine (`tools/make_finetune_set.py`, not yet built) must
   read this file and refuse a training candidate whose source matches a row
   — **trigger for that enforcement: Phase C tooling being built**, tracked
   here so it isn't silently skipped when that phase starts.
5. **7 new tests** (`tests/test_phase_a_ci.py`): `bootstrap_ci` degeneracy on
   1 clip, seeded reproducibility, bound ordering across all 4 metrics, empty
   corpus; harness records CI+RTF on `eval_run`; RTF is `None` (not a crash)
   when a clip's audio can't be duration-probed; a constructed 3-clip case
   where the point estimate crosses the regression band but the run's own CI
   contains the baseline — verified `passed=True` + `gate_unresolved ==
   "cer_thai"` instead of a hard fail. Full suite: **344 passed** (was 337).
6. **NOT done — schedule-critical, needs the user**: §3 item 3, the
   noisy/hard-clip gold stratum (the TVSpeech-lesson stratum from
   HANDOFF_CEILING_BREAK §1.2 item 3). No amount of code work substitutes for
   real hard-condition audio; asked the user directly — answer: proceed
   without it for now, tracked here as a known gap, not a blocker. Every
   phase gated on gold-set completeness (Phase B below, and any later
   re-probe) proceeds on the current 8-clip corpus.
7. **Fresh CI-bearing baseline recorded**: `eval_run.id=47` (real
   `faster_whisper`/th-medium production run, `--config transcribe/config.yaml
   --db transcriber.db`, `passed=True`) reproduces `id=46`'s point estimates
   exactly (`cer_thai 0.1751`, `wer_latin 0.8291`, `BER 0.5324`, `cue_BER
   0.3904` — same config/code/audio, deterministic pipeline) and adds:
   `cer_thai` CI `[0.0845, 0.2777]`, `wer_latin` CI `[0.4848, 1.0415]`, `BER`
   CI `[0.2873, 0.8289]`, `cue_BER` CI `[0.2163, 0.5526]`, `rtf=0.133`
   (~7.5× realtime — comfortably clears the speed handoff's ≥3× target).
   **Reading the CI widths honestly: they are wide** (e.g. `wer_latin`'s
   [0.48, 1.04] spans essentially its whole possible range) — an 8-clip
   corpus really can't resolve fine margins yet, exactly the finding this
   phase exists to surface. Any future probe whose point estimate wins by a
   few percent should be read against these bands, not treated as decisive.
   **Gotcha hit + confirmed still real**: `run_harness` does not call
   `init_db` on the caller's `db_path` — the pre-existing `transcriber.db`
   needed the one-time manual
   `python -c "from transcribe.db.store import init_db; init_db()"` before
   the new CI/RTF columns existed, exactly as CLAUDE.md's Token-granularity
   note warns for every prior `eval_run` column addition. First harness
   invocation crashed with `sqlite3.OperationalError: table eval_run has no
   column named cer_thai_ci_lo` until that migration ran.

## Gold-set growth (HANDOFF_CEILING_BREAK §1.2/§3.2) — 3 clips added 2026-08-05, IN PROGRESS

**Three clips landed** (commits `6543249`, `4e87034`, `9705e70`, plus a
cosmetic em-dash/cp1252 console fix in `3032a16`):

1. **`Short1_D5`** — 12 cues from a hand-fixed Premiere SRT, 9/12 tagged
   mixed script; the first genuinely code-switch-dense sample in the corpus.
   `cer_thai` moved 0.1415→0.2067 and `cue_boundary_error_rate` 0.3590→0.4495
   on the resulting 6-clip corpus vs the old 5-clip baseline — not a
   regression, the corpus is just honestly harder now (switches 104→132).
   `eval_run.id=42` reset to `passed=1` as the new baseline.
2. **`PeterWolf`** — ~3.7 min segment (23:43-27:23) trimmed from a raw
   interview to avoid overlapping `Short1_D5`/`Short2_D1` from the same
   source; 88 cues, dense classical-music code-switch content (Prokofiev,
   Peter and the Wolf, Disney, Composer, etc). `cue_boundary_error_rate`
   moved 0.4495→0.4624 on the 7-clip corpus — corpus genuinely harder, same
   production config. `eval_run.id=44` reset to `passed=1`.
3. **Wealthy40 DCA-update clip** — first 2 min of a finance-vlog clip, heavy
   Thai/English code-switching (DCA, AMD, Earnings). Corpus now **8 clips,
   ~10.4 min total** (confirmed by summing gold-JSON token spans). This is
   the clip that finally moved `wer_latin`/BER off their old near-inert
   baseline: **`wer_latin` 1.0452→0.8291, `boundary_error_rate`
   0.8169→0.5324** (switches 217, 83 matched, vs the old 10/104).
   `eval_run.id=46` (`cer_thai 0.1751`, `cue_boundary_error_rate 0.3904`,
   `passed=True`) is the current active baseline. (Note: `eval_run.id=45` in
   between is a failed intermediate run from this same session,
   `passed=False` — harmless, `get_last_passing_eval` skips it.)

**Strata coverage vs §1.2's three-part target:** production-style pure-Thai
shorts — have it (`Short1/2/3`, `orchestra_sections`). Real Thai-English
code-switch material — have it now (the 3 clips above + pre-existing
`Short2_D1`). **One noisy/hard clip — still missing.** Not done until that
lands.

**Due now, not deferred:** every phase gated on gold-set size — §4 (Engine A
large-v3 swap), §5 (DP cue split), §6 (Qwen3-ASR Engine B), §7 item 4
(GAP-5 bias terms) — was rejected on the old 5-clip corpus by margins the
handoff itself flagged as too small to trust (e.g. §4's Typhoon loss was
0.005 abs `cer_thai`; §5's DP-split loss was 0.0275 abs `cue_BER`). Re-probe
each against `eval_run.id=46` before trusting the old verdicts further, and
again once the noisy-clip stratum lands.

## Housekeeping remainder re-checked against stated triggers — 2026-08-05

Continuing the "Housekeeping pass" entry below (2026-08-05, first four items
done). Checked the three remaining §8 items instead of forcing action on them:

- **DeepFilterNet denoise** — trigger is "chunk-engine activation." Still
  hasn't fired (`config.yaml` still runs `faster_whisper` whole-file only).
  Confirmed `df.enhance` still fails to import in this venv
  (`ModuleNotFoundError: No module named 'df'` — `deepfilternet>=0.5.6` sits
  in `requirements.txt` unused). Left alone, correctly — no chunk engine to
  motivate the pin-vs-delete decision yet.
- **Editor GAP-7 "one-tap reason UI"** — turned out to be **already built**,
  predating this handoff: `transcribe/editor/static/index.html`'s reason-bar
  (click token → tag → `saveCorrections()` → `/jobs/{id}/save`) shipped in
  commit `9a618f8` (2026-07-15). `HANDOFF_CEILING_BREAK.md` §8 called it
  open; that was stale and is now corrected in that doc.
- **Merged-group corrected-state display — dropped, asked the user
  directly.** Grepped the full repo (schema.sql, store.py, editor) for any
  `merged_group`/`group_id` concept and found none, and no spec for this
  phrase exists anywhere in the repo or git history — it was a speculative
  note from an earlier planning session with nothing to hang it on
  (`diff.py`'s data model is strictly one-token-in → one-token-out by index,
  no merge/split concept at all). Asked the user whether to define it or
  drop it; **user confirmed: drop it, not a real need.** Closed, not due.
- **CutDeck real-Premiere XML import acceptance** — requires an actual
  Premiere Pro session against real footage (frame accuracy at the 60-min
  mark, audio linked, no offline media). Not something executable inside
  this session. Gave the user a concrete runbook (`cutdeck.plan` →
  `cutdeck.xml_export --job-id N` → import the resulting
  `<footage>/CutDeck/cd<job>_p<plan>.xml` into Premiere → check for an
  offline-media warning, audio/video linking, and frame accuracy) — still
  blocked on them running it and reporting back what Premiere does.

## Bias-index debt (Short4 candidates) probed and REJECTED (HANDOFF_CEILING_BREAK §7 item 4) — executed 2026-08-05

**Context:** last open item from the 2026-08-05 housekeeping pass (entry
further below), previously "blocked on the same missing gold-set audio as
§6/4.1" — that blocker no longer applies on this machine (RTX 4070 Ti, real
gold-set `.mp3`s present, same machine used for the Qwen3-ASR probes above).

**Setup:** none of the four candidates (`พรีเซนต์`, `เนี่ย`, `ชิบเป๋ง`,
`คบซ้อน`) had ever accumulated correction rows in `transcriber.db` (`0` matches
for all four against `store.get_correction_counts`), so `biasindex.
update_bias_index`'s normal promotion-by-occurrence path could never surface
them — they needed a direct `store.upsert_bias_term` (term_type/script via
the existing `_classify_term` heuristic → all four classified `loanword`/
`thai`; `added_by='manual'`, `weight=1.0`, honestly reflecting a single
historical observation rather than a counted correction). **Only `เนี่ย`
actually appears in the current 5-clip gold corpus** (3 occurrences, all in
`Bangkok_Festivals_orchestra_sections.json` / `Bangkok Festivals_CT6_
Short2_D1.json`) — the other three are specific to `Short4.mp3`, which was
used for ad hoc cue-F1 work in an earlier session but was never frozen into
`eval/goldenset/`. So this probe can only give a real verdict on one of the
four terms; the other three remain formally untested.

**Ran as a production gate, not `--experiment`** (matching `harness.py`'s
own docstring: "bias promotion" is one of the changes meant to legitimately
become the new baseline on a pass) — `python -m transcribe.eval.harness
--config transcribe/config.yaml --db transcriber.db` with the four terms live
in the bias index, gated against `eval_run.id=25` (`cer_thai 0.1415,
wer_latin 1.0452, BER 0.8169, cue_BER 0.3590`):

`cer_thai 0.1483` (**regression** — +0.0068 absolute / ~4.8% relative, past
both the 2% relative band and the 0.005 absolute floor), `wer_latin 1.0516`
(marginal regression), `BER 0.7917` (improved), `cue_BER 0.3532` (marginal
improvement). **`passed=False`.**

**Rolled back immediately**: `delete_bias_term` for all four terms,
confirmed `store.get_bias_terms(conn) == []`. No re-run needed to restore
the baseline — `get_last_passing_eval` filters on `passed=True`, so the
failed probe's `eval_run` row can never become the gate's comparison target;
`eval_run.id=25` is still the active baseline. `config.yaml` untouched (bias
index lives in `transcriber.db`, which is gitignored — this was a pure DB
operation, no code diff).

**Reading the result honestly:** this answers GAP-5's "does prompt biasing
measurably help at all" question with a real *no, not on this corpus* — not
because the terms are wrong (they're real vocabulary a human corrected
Whisper on), but because `initial_prompt` injection is a blunt instrument:
packing in terms absent from 4 of the 5 gold clips likely perturbed decoding
on the clips where they don't belong, and `cer_thai` (the primary Thai
signal, weighted by character count) is dominated by exactly the material
that got no benefit. BER/cue_BER moving the *other* direction just underlines
that these are small, correlated-noise-scale movements on a 5-clip corpus,
not a clean win/loss signal. **New standing finding for §9:** GAP-5 prompt
biasing does not clear the harness gate with this term set on this corpus.
Don't re-add these four (or reason from this result about biasing in
general) without §3.2's grown gold set — a corpus where the terms actually
appear across multiple clips is the minimum bar for a real read on whether
biasing helps.

## Qwen3-ASR span-granularity fix + null-confidence tiebreak investigated and REJECTED (HANDOFF_CEILING_BREAK §6/4.3) — executed 2026-08-05

**Context:** continuing §6/4.1's "next levers" list from the entry directly
below. This session ran on the RTX 4070 Ti machine with real gold-set audio
and a working `qwen-asr` install, so both open levers were actually
probeable instead of theorized.

**Lever 1 diagnosed first, before touching the reconciler at all:**
instrumented `_script_fallback` to log every real (ta, tb) disagreement pair
from a live `--engine-b qwen3_asr --experiment` harness run. Every single
logged pair showed Engine A's short (~2-5s, `cue_target_chars=42`) phrase
cue matched against ONE Qwen3-ASR token spanning up to 25s — the adapter's
`_split_long_span` call had no `max_span_s` override, so it inherited
`faster_whisper._LONG_SPAN_SAFE_S=25.0`. `align_hyp.py` matches each short A
cue against whichever B token's time window overlaps it, so every A cue
inside a long VAD segment was being compared against the SAME giant
multi-sentence B blob — not a real head-to-head, a granularity mismatch no
reconciler tiebreak logic could see past. This is a different and more
fundamental root cause than the "§4.3 confidence=None bias" theory the
entry below closed with.

**Fix:** added a `max_span_s` constructor param to `Qwen3ASREngine` (default
**8.0**, vs faster_whisper's 25.0), threaded into `_speech_spans_s`'s
`_split_long_span` call, exposed in `config.yaml`'s `engines.qwen3_asr`
block. Re-instrumented and re-ran: candidates are now genuinely comparable
in scale (confirmed in the log — real word-for-word and phrase-for-phrase
disagreements, including several where A correctly kept an English loanword
Latin, e.g. `A='กับ Jazz เพราะว่ามัน Symbolic'` vs a Thai-transliterating
B). Added `tests/test_qwen3_asr.py::test_long_span_is_capped_at_max_span_s`
+ `test_max_span_s_is_configurable`; suite 337 green.

**Re-probed with the fix** (`--engine-b qwen3_asr --experiment`): numbers
came back **byte-identical** to the pre-fix probe in the entry below
(`cer_thai 0.1415`, `wer_latin 1.0452`, `BER 0.8056`, `cue_BER 0.3617`,
switches 40/14). Root cause: `_script_fallback`'s null-confidence branch
falls through to `ca = ta.confidence or 0.0; cb = tb.confidence or 0.0`
whenever `ta.script` is `"mixed"` (common now that A's own candidates
correctly contain inline English words) — since Qwen3-ASR's `confidence` is
always `None` → `cb=0.0`, and A's real confidence in the instrumented log
ranged ~0.72-0.99, **A wins literally every head-to-head disagreement,
regardless of candidate size.** The span-cap fix makes the comparison real
for the first time, but doesn't change the outcome under the current
tiebreak — confirmed, not theorized.

**Lever 2, tested for real (not just reasoned about):** added a temporary
env-var-gated branch — if `tb.confidence is None` and `ta.confidence` is
below a threshold, prefer B (the "A is unsure enough to give B a look"
idea named in the entry below). Probed at threshold 0.75:
`cer_thai 0.1415→0.1614` (**regression, fails the gate**, `passed=False`),
`wer_latin 1.0452→1.0323` (marginal improvement), `BER 0.8056→0.8000`
(marginal improvement). **Rejected** — same trade-off class as the LLM
reconciler's round-2 rejection (2026-07-16 entry below): trusting B more
buys a small code-switch gain at a real Thai-accuracy cost. The
instrumented log explains why directly: the one row this threshold flips
(`A='กับ Jazz เพราะว่ามัน Symbolic' conf=0.723`) has B **transliterating**
"Jazz"/"Symbolic" into Thai script instead of preserving them — Qwen3-ASR's
lower-confidence-on-code-switch behavior in A doesn't correlate with A
being wrong here, it correlates with content that's genuinely hard to score
confidently but that A still gets right. Reverted immediately after
measuring; `_script_fallback` is byte-identical to before this session
(verified via `git diff`).

**Verdict:** `max_span_s=8.0` KEPT (real fix, zero regression, needed for
any future reconciler-tiebreak probe to mean anything) — `config.yaml`'s
`engines.qwen3_asr.max_span_s: 8.0` and the adapter change ship together.
`_script_fallback` UNCHANGED — both tested null-confidence tiebreak ideas
from §4.3 ("Latin content" implied by the entry below, and the low-A-
confidence threshold actually tested here) are now evidence-based
rejections, not open questions. `engine_b: passthrough` unchanged in
production config. **New standing finding for §9's rejection table:**
Qwen3-ASR does not clearly outperform Engine A on code-switch content on
this 5-clip corpus — it sometimes transliterates English loanwords into
Thai script rather than preserving them, which is a model-quality
observation, not a reconciler bug. Next real lever, if this is revisited:
§3.2's grown gold set (this corpus is one 5-clip sample and the one
low-confidence data point that mattered came from a single clip) — no
further reconciler-heuristic tuning without new evidence, per the same
discipline that closed the DP-cue-split and LLM-reconciler tracks.

## Qwen3-ASR internal VAD chunking fix + first real Engine B probe — NOT ACTIVATED (HANDOFF_CEILING_BREAK §6/4.1) — executed 2026-08-05

**Context:** this machine (RTX 4070 Ti, 12GB, `.venv` 3.11.9) turned out to
already have the gold-set audio (`transcribe/eval/goldenset/*.mp3`, present
since 2026-07-14/15 — the prior session's "blocked, no audio on this
machine" note was specific to a *different* machine). Installed `qwen-asr`
into the project `.venv` (dry-run showed no downgrades needed — this venv's
`transformers`/`huggingface_hub` were already at the versions the other
machine's system-Python install had landed on; only new additive packages:
`qwen-asr==0.0.6`, `gradio`, `accelerate`, etc. — full suite 334 green after
install). Ran the first-ever real harness probe with `--engine-b qwen3_asr
--experiment`.

**Bug found — the probe was initially meaningless, not a model verdict:**
the adapter (as built in the prior session, see the entry below) emits ONE
token per file spanning the whole clip at a placeholder `start_ms=0,
end_ms=0`, with the intent that the pipeline's forced-alignment pass would
fill in real timestamps later. That plan doesn't match the actual pipeline
order in `CLAUDE.md`: `align_hyp.py` (hypothesis-to-hypothesis alignment,
purely a temporal-window match, see its `_MATCH_PROX_MS=1500`/
`_token_overlap_ms`) runs **before** reconciliation; forced alignment runs
**after**. A zero-duration token at t=0 can only even be considered against
Engine A tokens starting in the first ~1.5s of a clip. First probe run came
back **byte-identical to the passthrough baseline on every single metric**
(`cer_thai 0.1415`, `BER 0.8169`, `cue_BER 0.3590`, exact match to 4
decimals) — confirmed via a standalone adapter call on `Short1.mp3` that the
model itself produces a real, coherent Thai transcript; the bug was purely
in how the adapter's output could never participate in `align_hyp.py`.

**Fix:** gave the adapter the same contract `faster_whisper`'s already
satisfies for a `prefers_whole_file=True` engine — do its own internal VAD
(reused `engines.faster_whisper._vad_speech_spans`, no new dependency; long
spans split via the existing `_split_long_span` with `overlap_s=0.0` since
this engine has no stitcher to dedupe an overlap-induced duplicate) and emit
one token per real speech span with a genuine span-derived `start_ms`/
`end_ms`, so `timestamps_final=True` now instead of `False`. Verified
directly on `Short1.mp3`: 4 tokens with real, distinct timestamps matching
VAD segmentation, vs. the old single 0–0 blob. `transcribe_batch()` now
delegates to `transcribe()` per input for the same fix (it's dead code in
production — `prefers_whole_file=True` means `run.py` never calls it — kept
for adapter-contract completeness). Updated `tests/test_qwen3_asr.py`
(timestamps_final assertions flipped to `True`, added a monkeypatched
multi-span test, made the fake model's `transcribe()` consume a queue
instead of always returning index 0 so per-input sequential calls work);
suite 335 green.

**Re-probed with the fix, `eval_run` vs baseline `id=25`:**

| Signal | Baseline | This probe | Delta |
|---|---|---|---|
| `cer_thai` | 0.1415 | 0.1415 | unchanged — no dilution |
| `wer_latin` | 1.0452 | 1.0452 | **unchanged** — no improvement |
| `boundary_error_rate` | 0.8169 | **0.8056** | improved |
| `cue_boundary_error_rate` | 0.3590 | 0.3617 | +0.0027, inside `regression_abs_floor` (0.005) |
| switches (hyp/matched) | 38 / 13 | 40 / 14 | small real movement |

`passed=True` per the harness gate (no metric regressed past tolerance),
and — critically — this is the **first time** an Engine B candidate run on
this gold set produced numbers different from the passthrough baseline,
confirming Engine B now genuinely participates in reconciliation. But it
does **not** clear §6's stated activation bar ("BER and wer_latin improve
AND cer_thai holds") — `wer_latin` is flat, not improved.

**Root-cause hypothesis for the flat `wer_latin` (not chased further this
session):** `reconcile.py`'s `_script_fallback` (lines 93–110) routes purely
on Engine A's own `ta.script` label — if `ta.script == "thai"` it always
picks A outright, and Qwen3-ASR honestly reports `confidence=None` (never
faked), so the confidence-tiebreak branch degrades to always favoring
whichever side has *a* confidence value, i.e. A. This is the exact same
structural bias diagnosed for `whisper_multi` in the 2026-07-16 entry below,
and HANDOFF_CEILING_BREAK.md §4.3 already named it as the expected next
failure mode ("Qwen3-ASR will likely report confidence=None too, so this
fires immediately"). The small BER gain most likely comes from solo
Engine-B slot insertions (align_hyp assigning a B token no A candidate
matched) rather than from winning real head-to-head disagreements.

**Verdict: NOT ACTIVATED.** `config.yaml`'s `engine_b: passthrough` is
unchanged — all of this was run via `--engine-b qwen3_asr --experiment`,
never touching the production default. Distinguish this from the four prior
Engine-B rejections (funasr/typhoon_rt/whisper_multi/re-tuned cue knobs):
those had real regressions; this one has zero regression and a small,
real, non-diluting improvement, just not enough to clear the bar on a
5-clip corpus with a known reconciler bias still in the way. Next levers,
in order: (1) §4.3's already-planned `_script_fallback` tiebreak for
null-confidence engines (length/completeness heuristic) — now finally
testable since a real Engine B exists — then re-probe; (2) §3.2's grown
gold set, still not done, to tell signal from noise on a corpus this small.

## Housekeeping (§8) + policy debts (§7) pass — HANDOFF_CEILING_BREAK.md — 2026-08-05

**Context:** §6/4.1 (Qwen3-ASR harness probe) is still blocked on missing
`transcribe/eval/goldenset/*.wav` on this machine — asked the user again,
they chose to work on unblocked tracks instead (§7, §8) rather than resolve
the audio question this session. That blocker is unchanged; see the entry
below for full detail.

**§8 housekeeping, done:**
- `CLAUDE.md`: removed the stray `>>>>>>> d405aac...` merge-conflict marker
  line above "Token granularity (5.4)" — no actual conflicting content on
  either side, just an orphaned marker.
- `scripts/make_gold.py` deleted. Confirmed it was a stale duplicate from an
  earlier commit (`9aecc1b`, CutDeck-era) with no references anywhere in
  code/docs/tests; `tools/make_gold.py` is the actively-used, everywhere-cited
  version (`from-srt`, draft→freeze workflow, `transcribe/srt_io.py` imports
  from it).
- Stale `transcribe.db`/`transcriber.db` duplication: checked and it's a
  non-issue — only `transcriber.db` (and an unrelated 0-byte `memory.db`)
  exist at repo root, both gitignored/untracked. No `transcribe.db` file
  exists to remove.
- Python-version docs: `CLAUDE.md`, `requirements.txt`, `setup.py` already
  correctly say 3.11.9 (a prior session already fixed this). Added a
  "Running tests" section to `transcribe/README.md` with the
  `.venv/Scripts/python.exe -m pytest tests/ -q` invocation and a note on why
  a bare-3.13-shell run shows the pycrfsuite failure, since no doc previously
  stated the correct invocation.
- Not touched (correctly out of scope per the handoff): DeepFilterNet denoise
  decision (due at chunk-engine activation), editor GAP-7 (due when editor
  next touched), CutDeck Premiere-import gate (tracked separately).

**§7 policy debts, decided (both are pure documentation — zero code change,
match existing default behavior, so no harness run was needed to ship them):**
- **Mai-yamok contraction without the mark** (`ดีดี` vs `ดีๆ`): decision
  recorded in `STYLE_GUIDE.md` §3a — **accept the CER tax, do not build a
  hypothesis-side contractor speculatively.** Reasoning: this project's prime
  directive is "nothing activates without the eval harness proving it," and
  the harness is exactly the thing currently blocked on this machine —
  building unverified normalization logic would violate the discipline every
  other STYLE_GUIDE decision was built to uphold. Trigger to revisit: once
  harness access returns, measure the actual doubled-syllable rate in raw
  hypothesis output before writing any contractor.
- **Colloquial vs. formal register** (`คนนึง` vs `คนหนึ่ง`): decision recorded
  in `STYLE_GUIDE.md` §8 — **transcribe the register actually spoken, on both
  gold and hypothesis sides, no canonicalization.** Same logic as §2's
  existing number-verbalization policy (write it as spoken, not as
  convention prefers) applied to the general colloquial/formal pair class,
  not a fixed list. `normalize.py` doesn't currently touch this and
  shouldn't start.
- **Number verbalization** (handoff item 3): already decided and documented
  in `STYLE_GUIDE.md` §2 from a prior session — no new work needed.
- **Bias-index debts** (handoff item 4, the four Short4 candidates + the
  GAP-5 with/without-bias-prompt harness comparison): **not done, blocked on
  the same missing gold-set audio as §6/4.1** — this item requires an actual
  harness run, which the documentation-only items above deliberately avoided
  needing. Carries forward to whichever session resolves the audio question.

## Qwen3-ASR Engine B adapter — BUILT + smoke-verified against real weights, HARNESS PROBE STILL BLOCKED (HANDOFF_CEILING_BREAK §6/4.1) — 2026-08-05

**Built:** `transcribe/engines/qwen3_asr.py` — `Qwen3ASREngine`, registered as
`"qwen3_asr"` in `engines/registry.py`'s lazy-load table. Wraps the `qwen_asr`
package's own `Qwen3ASRModel.from_pretrained(...).transcribe(...)` (not the HF
`transformers` pipeline the other adapters share — Qwen3-ASR ships its own
inference wrapper; usage confirmed against the live model card,
huggingface.co/Qwen/Qwen3-ASR-1.7B). `prefers_whole_file = True`.
`confidence` is always `None` (never faked, same discipline as every other
adapter). Per the handoff's explicit guidance to take the smaller diff first:
`timestamps_final=False` — no `Qwen3-ForcedAligner-0.6B` wiring yet, so the
pipeline's existing forced-alignment pass assigns real ms values; wiring the
aligner is a separate, later probe. `language_hint` ("th"/"en") maps to the
full names (`"Thai"`/`"English"`) the API expects; unmapped codes pass
through verbatim; `None` → auto-detect. Audio: reuses `inp.audio_path`
directly, or writes a temp WAV when only a decoded array is given (the
library wants a file path, unlike the HF-pipeline engines which accept raw
arrays) — temp file always cleaned up in a `finally`. `transcribe_batch`
batches by calling `transcribe()` once with a list (the library's own
`max_inference_batch_size`, set at load time, governs internal batching) —
deliberately does **not** reuse `engines/_batch.py`'s OOM-backoff helper,
since that helper is coupled to the HF pipeline's per-call `batch_size` kwarg
and retrying with a smaller external batch_size isn't actionable against
`qwen_asr`'s internal batching; an OOM here surfaces to the caller as a real
failure instead.

**Config:** `config.yaml` gained a commented-out-by-default `engines.qwen3_asr`
block (`model_id: Qwen/Qwen3-ASR-1.7B`, `max_inference_batch_size: 8`,
`max_new_tokens: 256`); `engine_b` stays `passthrough` — not activated.
`requirements.txt` gained a commented `qwen-asr>=0.1.0` line (package not
installed in this session's venv).

**New test file** `tests/test_qwen3_asr.py` (7 tests, mirrors
`test_phase4_typhoon.py`'s pattern: `qwen_asr` is never imported, the model is
faked via monkeypatching `eng._model`, so these run on any machine without the
real dependency) — registration, text→token mapping with `confidence=None`/
`timestamps_final=False`, empty-text yields no tokens, language-hint mapping,
batch ordering, empty-batch, unload. Full suite: **329 passed** (was 322 on
this venv; deselected `test_faster_whisper_cues.py`'s
`test_sentence_boundary_offsets_finds_the_split` — a pre-existing,
environment-only failure on Python 3.13 where `pycrfsuite` has no wheel, per
CLAUDE.md/§8 housekeeping note; not caused by this change and not present on
the project's real 3.11.9 venv).

**UPDATE 2026-08-05, same day, `qwen-asr` actually installed:** `pip install
qwen-asr` (0.0.6) succeeded on this machine's system Python 3.13 (no isolated
project venv exists here). **Side effect to know about:** it pulled in its
own `transformers`/`huggingface_hub` pins and *downgraded* the shared,
system-wide install — `transformers` 5.9.0 -> 4.57.6, `huggingface_hub`
1.16.4 -> 0.36.2 (memory record `env-and-gap5-verified.md` claimed 5.9.0
verified; that's now stale on this machine). Full suite re-run after the
downgrade: still 329 passed / 1 pre-existing deselect — no regression from
the downgrade itself, but it changes what "the venv" means going forward on
this box; flag if a future session hits a transformers-version-sensitive
issue elsewhere.

**API corrected against the real package, not just the model card.**
Introspecting the installed `qwen_asr` (`inspect.signature`/`getsource`)
turned up two things the model-card example didn't show, and both are now
built into the adapter:
1. `Qwen3ASRModel.transcribe(audio=...)` accepts an `(np.ndarray, sample_rate)`
   tuple directly (or a list of them) — no temp-WAV round-trip needed for
   pre-decoded audio. The adapter's original temp-file path was replaced;
   `_audio_arg` now returns the tuple directly, `inp.audio_path` (a string)
   still passed straight through.
2. `transcribe()` takes a `context: str` argument — a free-text prompt hint,
   broadcastable per-item on a batch. The adapter now wires
   `EngineInput.bias_terms` into it via `flywheel.inject.build_prompt`, the
   same GAP-5 budget-packing every other engine's bias injection uses. This
   wasn't in the original build; it's a real capability match, not
   speculative — confirmed against `Qwen3ASRModel.transcribe`'s actual
   `inspect.getsource`.
`tests/test_qwen3_asr.py` grew from 7 to 11 tests covering both (audio-tuple
shape, path-passthrough, bias-terms-to-context, empty-context default). Full
suite still green.

**Smoke-verified against real weights on the RTX 3070** (not just the fake
model in tests): `Qwen3ASRModel.from_pretrained("Qwen/Qwen3-ASR-1.7B", ...)`
downloads (~3.4GB, cached after) and loads in ~13s warm / ~58s cold,
**4.08GB VRAM allocated** — comfortably inside the 8GB ceiling as predicted.
A real `Qwen3ASREngine.transcribe()` call end-to-end (load → transcribe →
unload) against a 2s synthetic sine-tone clip returned a well-formed
`EngineResult` (`RecognizedToken(text='คุณ', ..., confidence=None,
script='thai')`, `raw={'language': 'Thai', ...}`, `timestamps_final=False`)
and `unload()` freed VRAM back to ~0.009GB. The Thai word on a pure tone is
expected LLM-ASR hallucination-on-silence, not an adapter defect — it proves
the plumbing (audio-tuple arg, language-hint mapping, context/bias arg,
token/EngineResult mapping, VRAM discipline) round-trips correctly against
the real model; it says nothing about accuracy.

**STILL BLOCKED — the actual harness probe (HANDOFF §4.1 steps a/b, §6
acceptance criteria).** Ran `harness.py` for real: it printed "no audio for
<name>.json, skipping" for all 5 gold-set entries and "goldenset is empty —
No eval_run recorded." **The gold-set `.wav` files are gitignored
(`transcribe/eval/goldenset/*.wav` etc.) and are not present anywhere in
this checkout** — `find` across the whole repo turns up zero audio files.
This blocks *any* harness probe on this machine right now, not something
specific to Qwen3-ASR (§4's Typhoon/Pathumma probes and §5's DP cue split
probe, both marked DONE in the handoff, must have been run on a different
checkout/machine that had the audio — see the handoff's own note that §4 was
"confirmed via nvidia-smi" on an RTX 4070 Ti, a different box). Next step
needs either: the gold-set audio copied onto this machine, or this adapter
handed to whichever machine already has it, before step (a) (`--experiment`
probe against `eval_run.id=25`) can run. Until then this phase's verdict is
unmeasured, same as before — "built and smoke-verified" is not "measured."

**2026-08-05, follow-up: asked the user where the audio lives — deferred,
not resolved.** Offered three options (local path to copy from / audio only
exists on the RTX 4070 Ti box / files need re-cutting from source media);
user chose to skip resolving it now and just record what's needed. **So:
before attempting any harness probe on this machine, settle one of these
first, next session** —
1. Get a local path to copy the 5 gold-set audio files
   (`Short1/2/3`, `Bangkok Festivals_CT6_Short2_D1`,
   `Bangkok_Festivals_orchestra_sections`) from, and copy them into
   `transcribe/eval/goldenset/`, matching each `.json`'s basename; **or**
2. Confirm the RTX 4070 Ti box (the one §4's Typhoon/Pathumma probes ran on)
   is the only place the audio exists, and run the Qwen3-ASR probe there
   instead of here; **or**
3. If the audio was never preserved anywhere, re-cut the gold set from
   original source media via `tools/make_gold.py` (draft → hand-correct →
   freeze, or `from-srt` if a hand-recut Premiere SRT exists) — this is the
   same schedule-critical authoring task HANDOFF_CEILING_BREAK.md §3.2
   already flags as NOT DONE for growing the gold set to 10-15 minutes, so
   it may be worth doing both at once.
Don't assume which of the three applies — ask again if still unclear.

## DP cue split probe — NOT ACTIVATED, close but regresses cue_BER (HANDOFF_CEILING_BREAK §5/§10.3) — executed 2026-08-04

**Driven by** the handoff's §5 diagnosis: `_group_words_into_cues`'s greedy fill
closes a cue "the instant `n_chars >= cue_target_chars`" and breaks wherever
that lands, measured F1-neutral against tuning `cue_space_min_*` in isolation
(2026-07-30 entry below) — "the blocker is the greedy fill itself."

**Built** (`transcribe/engines/faster_whisper.py`): the greedy function was
renamed to `_group_words_into_cues_greedy` (body byte-for-byte unchanged —
every pre-existing cue test still exercises it and all still pass) and
`_group_words_into_cues` now dispatches on a new `algorithm` param, gated by
a new `cue_split_algorithm: greedy|dp` config knob (`engines.faster_whisper`,
default `greedy`) threaded through the constructor and `transcribe()` exactly
like every other 2.3 cue knob. `algorithm="dp"` runs a new
`_group_words_into_cues_dp`: a classic subtitle line-breaking DP over
**every pythainlp word boundary** (not just Whisper's sporadic emitted
spaces, which is all the greedy path's space-break heuristic could see) as
candidate breaks, with the two STYLE_GUIDE §7 vetoes (mai yamok orphaning,
numeral split from its classifier) excluded from the candidate set outright
— an illegal break can never be chosen, not just a costly one. Sentence
boundaries (crfcut) and real silence gaps (>= `cue_gap_ms`) remain hard
splits, same "a cue must never cross either" invariant as greedy, dividing
the word stream into independent runs; within each run, DP minimises a cost
= deviation from `cue_target_chars` (asymmetric — quadratic once over,
mildly linear once under, see below) + a quadratic penalty for exceeding
`cue_max_ms`, discounted wherever Whisper itself emitted a space, with a
huge penalty for any cue under `cue_space_min_chars`/`cue_space_min_ms` (a
"runt"). New test file `tests/test_cue_split_dp.py` (13 tests: no-char-loss,
both §7 vetoes, sentence/gap hard splits still enforced, no runts, default
algorithm still resolves to byte-identical greedy output, config wiring).
Suite: **323 passed** (was 310; +13 new, +1 assertion added to
`test_cue_target_chars_config.py`'s existing wiring test).

**Probed via `harness.py --experiment`** (`cue_split_algorithm: dp` in
config.yaml, reverted after) against the metrics v3 baseline
(`eval_run.id=25`/`35` — re-ran the reverted config to confirm it reproduces
`id=25` exactly, confirming the revert is clean): `cer_thai 0.1415`,
`wer_latin 1.0452`, `boundary_error_rate 0.8169`, `cue_boundary_error_rate
0.3590`, `cue_count_delta -20`.

First attempt used a **symmetric** quadratic deviation cost
((chars-target)²) — this badly regressed cue_BER to **0.4554**
(`eval_run.id=28`) and worsened `cue_count_delta` to **-41**: a symmetric
cost makes DP prefer *merging* toward the target from both directions, so it
produced *fewer, longer* cues than the greedy fill, the opposite of what the
hand-recut references want. Diagnosed and retuned the cost to be
**asymmetric** (quadratic once a cue exceeds `cue_target_chars`, only a mild
linear cost when it undershoots — undershooting should be nearly free, since
the gold set wants more/shorter cues) and iterated the weights against the
live harness (`_DP_UNDERSHOOT_WEIGHT`/`_DP_OVERSHOOT_WEIGHT`/
`_DP_SPACE_DISCOUNT` in `faster_whisper.py`, comments there record the
reasoning):

| Attempt | `_DP_UNDERSHOOT_WEIGHT` | `_DP_SPACE_DISCOUNT` | `cue_BER` | `cue_count_delta` | `boundary_error_rate` | `eval_run.id` |
|---|---|---|---|---|---|---|
| symmetric (first) | n/a | 50 | 0.4554 | -41 | 0.8592 | 28 |
| asymmetric, v1 | 0.4 | 50 | 0.4170 | -7 | 0.8169 | 29 |
| asymmetric, v2 | 0.15 | 100 | 0.4137 | -5 | 0.8310 | 30 |
| asymmetric, v3 | 0.15 | 50 (+ `_DP_OVERSHOOT_WEIGHT=2.0`) | 0.4183 | -3 | 0.8310 | 31 |
| **asymmetric, best** | **0.08** | **50** | **0.3865** | **-3** | **0.8169** | 32 (reproduced at 34) |
| asymmetric, v5 (worse) | 0.05 | 70 | 0.4104 | -3 | 0.8310 | 33 |

**Verdict: NOT activated.** The best tuning found (`eval_run.id=32`/`34`,
`_DP_UNDERSHOOT_WEIGHT=0.08`, `_DP_OVERSHOOT_WEIGHT=2.0`,
`_DP_SPACE_DISCOUNT=50.0` — these are now the shipped constants, config
default stays `greedy`) gets close but still **regresses**
`cue_boundary_error_rate` (0.3865 vs 0.3590 baseline, +0.0275 absolute /
+7.7% relative) — past the harness's regression-tolerance gate
(`passed=False`). Read honestly: this is not a clean loss. Two of the three
other signals *improved* over the greedy baseline at this same setting —
`cue_count_delta` went from -20 to **-3** (DP's cue count is far closer to
the gold set's), and switch-point matching improved from 10/104 to
**13/104** matched — while `cer_thai` and `wer_latin` stayed **exactly**
identical to baseline on every single probe (0.1415/1.0452, bit-for-bit),
which is the expected and correctly-verified invariant: cue-splitting
changes only *where* text is cut into cues, never the text itself, so CER/WER
cannot move. Only the specific cue-F1 metric — which scores exact boundary
*timestamps* within `boundary_tol_ms`, not just cue count — still comes out
behind greedy's, suggesting DP is choosing *linguistically defensible but
differently-positioned* breaks than the specific hand-recut references
picked, not that it's structurally worse at segmentation. `cue_split_algorithm`
stays `greedy` in `config.yaml`; production behaviour is byte-identical to
before this session (confirmed: reverted-config harness run `eval_run.id=35`
reproduces `id=25` exactly on every gated metric).

**What's still open, same caveat as the §4 Engine A rejections:** this is
gated on the same 5-clip corpus §1.2 (gold-set growth) already flagged as too
small to arbitrate margins this fine — a 0.0275 absolute cue_BER gap on 5
clips is exactly the kind of result §1.2 exists to disambiguate from noise.
Don't hand-tune the DP weights further without new evidence; re-probe once
the gold set grows, or try scoring candidate breaks against `cue_BER`
directly instead of the char/duration proxy (the proxy-vs-actual-metric gap
is the likely reason count improved while F1 didn't). The DP code path,
tests, and config flag are all in place and correct — this entry is a
measured rejection, not unfinished work.

## Engine A large-v3 swap probes — REJECTED both (HANDOFF_CEILING_BREAK §4/§10.2) — executed 2026-08-04

**Driven by** the handoff's §2 external evidence: the published Typhoon ASR
paper table shows Typhoon Whisper Large-v3 and Pathumma-Whisper Large-v3 at
2–3× lower CER than Biodatlab Whisper **Large** on three Thai benchmarks —
and this repo runs the Thonburian **medium**, so the gap should be at least
that large if the published numbers reproduce here. Both are plain Whisper
large-v3 fine-tunes, convertible through the existing CT2 pipeline with zero
adapter code — a `ct2-transformers-converter` run plus a `model_id` YAML edit.

**Correction to the handoff doc:** its listed repo ID `scb10x/typhoon-whisper-large-v3`
does not exist on the Hub (401/repo-not-found on lookup) — the real repo is
`typhoon-ai/typhoon-whisper-large-v3`. `nectec/Pathumma-whisper-th-large-v3` was
correct as written. Pathumma's repo also lacks a `tokenizer.json` (only slow
tokenizer files) — `faster_whisper` silently falls back to the `openai/whisper-tiny`
tokenizer (wrong vocab) if that file is absent, so a fast tokenizer was generated
via `transformers.WhisperTokenizerFast.from_pretrained(...).backend_tokenizer.save(...)`
and copied into the CT2 output dir (confirmed `len(tokenizer)=51866`, matching
large-v3's Cantonese-token-expanded vocab) before probing.

Both converted cleanly (`int8_float16`, ~1.5 GB each, `models/typhoon-whisper-large-v3-ct2`
and `models/pathumma-whisper-th-large-v3-ct2`, both load fine via `faster_whisper` — this
session happened to run on an RTX 4070 Ti, 12 GB, but that's just this machine; the repo
targets whatever box runs it, and CLAUDE.md/handoff's "RTX 3070, 8 GB" is the conservative
floor to gate against, not a literal spec to keep updating per-machine) and were
probed via `harness.py --experiment` against the metrics v3 baseline
(`eval_run.id=25`: `cer_thai 0.1415`, `boundary_error_rate 0.8169`,
`cue_boundary_error_rate 0.3590`), `compute_type: int8_float16`, `batch_size: 4`,
same 5-clip gold set:

| Model | `eval_run.id` | `cer_thai` | `wer_latin` | `boundary_error_rate` | `cue_boundary_error_rate` | Verdict |
|---|---|---|---|---|---|---|
| Typhoon Whisper Large-v3 | 26 | 0.1731 | 1.0000 | **1.0000** (0/104 switches matched) | 0.5926 | REJECTED — worse on every gated signal |
| Pathumma Whisper Large-v3 | 27 | 0.1464 (within tolerance) | 1.0129 | 0.8615 | 0.5741 | REJECTED — BER/cue_BER regression |

Typhoon's BER of 1.0000 is a total failure on this gold set's Thai↔English
switch points, not a marginal miss — the hypothesis found real switches at
only 2 of 104 reference points and matched none of them. Pathumma is much
closer to baseline on `cer_thai` (inside the 0.005 abs-floor band) but still
regresses `boundary_error_rate` and `cue_boundary_error_rate` past the gate.

**Read honestly, per the handoff's own instruction (§4):** this is a major
finding about the gold set's domain, not a reason to doubt the published
benchmarks in general. The published table uses Na-Thalang normalization and
clean academic/TVSpeech test sets; this repo's 5-clip gold set is creator-style
Thai-English code-switch content with a deliberately divergent normalization
policy (§7 mai-yamok/colloquial). `typhoon-whisper-turbo`'s published numbers
already failed to reproduce here once (2026-07, CER 0.1336 vs 0.1069) — this is
the second and third time a published-SOTA Whisper fine-tune has lost to the
in-repo th-medium baseline on this specific corpus. Prime suspect per §7:
normalization-policy mismatch style-penalizing large-v3-lineage output before
any genuine accuracy comparison happens — but that's speculative pending the
§1.2 gold-set growth (still not done, still needs the user) to arbitrate
whether this is a real ranking or a 5-clip artifact.

**Production config: unchanged.** `engine_a` stays `faster_whisper` /
`models/whisper-th-medium-ct2`; both large-v3 CT2 conversions are kept on disk
(`models/typhoon-whisper-large-v3-ct2`, `models/pathumma-whisper-th-large-v3-ct2`,
~1.5 GB each) in case the grown gold set (§1.2) or a normalization-policy fix
(§7) changes this verdict later — don't re-download to re-probe.

Suite: **310 passed**, unchanged (no source code touched, config.yaml reverted
to baseline model_id/compute_type/batch_size after both probes — see its
in-file comment for the permanent record of this result).

## Metrics v3 — cue-structure signals (HANDOFF_CEILING_BREAK §3.1) — executed 2026-08-04

Suite: **310 passed** (+11 in new `tests/test_metrics_v3.py`).

**Driven by** `docs/HANDOFF_CEILING_BREAK.md` §3's "make the gate see what
matters before any engine swap" — the 2026-07-30 entry below found cue-F1
0.717/0.691 by hand on Short4 with no reusable code; this promotes it to a
first-class, regression-gated metric.

**The fix (metrics v3, `metrics.METRICS_VERSION = 3`):** tokens are already
phrase cues (5.4), so a token's `start_ms` already **is** a cue boundary — no
gold-schema change needed, the existing hand-recut-SRT gold JSONs already
carry it via `srt_io.parse_srt`. Added to `compute_metrics`/`EvalMetrics`:
1. `cue_boundary_error_rate` — F1@`boundary_tol_ms` between ref and hyp
   cue-start timestamps, matched and micro-F1-aggregated the same way as the
   existing switch-point BER (`_match_points`, generalized from the old
   switch-only `_match_switch_points`). Joins the regression-tolerance gate.
2. `overlapping_cues` — hard invariant, asserted 0, not a rate. The harness
   hard-fails the run whenever this is nonzero, **unconditionally**, even on a
   first run with no prior baseline (the real 2026-07-30 shipped instance —
   `42,740 --> 42,660` — is what this exists to catch mechanically).
3. Descriptive-only (recorded on `eval_run`, never gated): `cue_count_delta`,
   `shortest_cue_ms`, `nonzero_gap_count`.

`eval_run` gained the 5 matching columns (idempotent `_migrate`). Note:
`run_harness` does not call `init_db` on the caller's `db_path` — a
pre-existing `transcriber.db` needed one manual re-`init_db()` to pick up the
new columns before the harness could write to it; this is the same manual
step every prior `eval_run` column addition has required.

**Proven on the real gold set (2026-08-04):** `eval_run.id=25`,
`metrics_version=3`, `passed=True` (fresh baseline, first v3 run):
`cer_thai 0.1415`, `wer_latin 1.0452`, `boundary_error_rate 0.8169` (both
close to but not identical to the 2026-07-16 v2 numbers — run-to-run drift,
not a regression signal since this run *establishes* the v3 baseline),
**`cue_boundary_error_rate 0.3590`** (F1 ≈ 64%, first-ever measurement),
`overlapping_cues 0`, `cue_count_delta -20` (pipeline emits 20 fewer cues than
the hand-recut gold, summed over 5 clips — consistent with the greedy-fill
under-splitting problem §5/Phase 3 targets), `shortest_cue_ms 320.0`,
`nonzero_gap_count 17`.

**Still open (unchanged from HANDOFF_CEILING_BREAK §1.2, not a code task):**
growing the gold set to 10–15 minutes across three strata (production-style
pure-Thai shorts, real code-switch material, one noisy clip) — needs new
source clips from the user. `tools/make_gold.py from-srt` is the fastest path
once a hand-recut Premiere SRT exists for a new clip.

## Cue timing + sub-word seam dedup + space breaks — executed 2026-07-30

Suite: **216 passed** (was 214; +26 across `tests/test_cue_conform.py`,
`tests/test_cue_space_break.py`, `tests/test_stitch_subword_coincidence.py`,
minus the rewritten `test_cue_target_chars_config.py` capture test).

Driven by a **hand-recut reference SRT** for `Short4.mp3` (46.5s, pure Thai,
re-cut in Premiere Pro): 31 cues vs the pipeline's 22, `cer_thai 0.0448`. The
text was already 95.5% right — what the human actually rewrote was
segmentation and timing, which no metric in the harness measures.

**1. Cue-timing conform is now unconditional (`align_force.conform_cues`).**
The monotonic/no-overlap invariant lived *inside* `forced_align`, and
`run.py` skips Phase 7 whenever the engine reports `timestamps_final` — which
`faster_whisper` always does. So on the only active engine path the invariant
was enforced nowhere, and cues 20/21 shipped as `42,740 --> 42,660`
(overlapping) in `output/Short4.srt`. New Phase 7b runs on every path;
`forced_align` delegates to it (word-level behaviour unchanged — gap closing
is a cue policy and stays off there). `cue_max_close_gap_ms: 200` closes
timestamp-noise gaps that flicker burned-in subtitles.

**2. Stitch dedup now sees sub-word pieces (`stitch._coincident`).** The seam
stutter documented in `faster_whisper.py`'s `_LONG_SPAN_SAFE_S` block was
misdiagnosed there as an exact-text-matching problem needing edit distance.
It was not: the duplicates matched on text fine and were lost to the **IoU
gate**. Whisper's Thai output is sub-word — pieces run 20–80ms and combining
marks land at `start == end`, where IoU is structurally 0.0 and no threshold
can ever match. Measured at the 42–46s window seam: `'อะไร'` IoU 0.44, `'ก'`
0.43, `'ก'` (both zero-length) 0.00, `'จ'` 0.33. Centre-coincidence is
duration-scaled, so genuinely repeated Thai consonants (`แบบ`, `รักกับ` — 130ms
apart) are still kept, and the `ci != pci` cross-chunk guard still carries the
real safety.

**3. Whisper's own spaces are cue-break candidates.** Gated on
`cue_space_min_chars`/`cue_space_min_ms` plus STYLE_GUIDE §7 vetoes (mai yamok
must not be orphaned — Whisper emits `' ๆ'` as its own space-prefixed piece,
so this is the common case; numeral must stay with its classifier) and a
runt guard (both sides of the break must be viable — an early version shipped
a 140ms `'โอเค'` flash cue).

**Measured before → after on the reference clip:**

| | before | after | your SRT |
| --- | --- | --- | --- |
| `cer_thai` | 0.0448 | **0.0433** | — |
| overlapping cues | **1** | **0** | 0 |
| non-zero gaps | 6 (max 140ms) | **0** | 0 |
| shortest cue | 0.46s | **0.56s** | 0.56s |
| stitch dups removed | 27 | 36 | — |
| cue-start F1 @300ms | 0.717 | 0.691 | — |

Fixed in the transcript: `อะไรกก็ตาม`→`อะไรก็ตาม`, `ทรมานใจจ`→`ทรมานใจ`,
`ไกลกลไกกล`→`ไกลไกล`.

**Honest negative result on (3):** the space break is F1-neutral-to-slightly-
negative in isolation (a grid over `space_min_chars` × `space_min_ms` was flat
at 0.70–0.73 vs a 0.717 baseline). It breaks in linguistically correct places,
but the greedy `cue_target_chars` fill then just relocates the arbitrary
boundary into the following cue — net wash. **Do not tune these knobs further;
the blocker is the greedy fill itself.** Set both to a large number to disable.

**Still open, in impact order:**
- **Replace greedy cue fill with a cost-minimising split.** `_group_words_into_cues`
  closes a cue the instant `n_chars >= target_chars` and breaks at whatever word
  boundary it is standing on — measured exactly: the 42-char cue
  `เขาสามารถบอกได้ว่าไม่เป็นไรเธอมีแฟนแล้วฉัน` is *precisely* 42 codepoints and split
  `ฉัน | จะรอ`, subject from verb. Same mechanism gave `นะคะให้ | น้อง` and
  `พออยู่ | ด้วยแล้ว`. This is the real segmentation fix and (3) is its input signal.
- **Cue-structure metrics in `compute_metrics` (bump `METRICS_VERSION`).** On this
  clip `wer_latin` scored 0 Latin words and BER scored 0 switch points — two of
  three gate signals were inert, and segmentation error 0.31 is invisible. An
  engine swap could wreck timing on pure-Thai production content and pass clean.
  Overlap count belongs in as a hard assertion of 0, not a rate.
- **Mai-yamok contraction policy.** Whisper emits `ดีดี`/`ใหม่ใหม่` (and `จริงๆ`
  correctly two cues earlier — it is inconsistent). STYLE_GUIDE §3 fixes gold on
  attached-`ๆ` and refuses `ๆ`→expansion, but nothing does the contraction
  direction, so `cer_thai` pays for it forever. Same class: `คนนึง`→`คนหนึ่ง` is an
  unstated colloquial-vs-formal policy. Needs a decision, not code.
- Bias-index candidates from this clip: `พรีเซนต์`, `เนี่ย`, `ชิบเป๋ง`, `คบซ้อน`.
- Two `make_gold.py` copies exist (`tools/` and `scripts/`); both `transcribe.db`
  and `transcriber.db` sit at the repo root but only the latter is used.

## Metrics v2 — intra-cue switch points (BER un-blinded) — executed 2026-07-16

Suite: **184 passed** (was 176; +8 in `tests/test_metrics_v2.py`).

**The finding:** `metrics._switch_points` derived Thai↔Latin switches from the
token-level `script` field only. Tokens are phrase cues, so every real
code-switch sits *inside* a `mixed` cue — invisible by construction. The whole
gold set therefore scored `switches=0` regardless of content, BER was pinned
at a structural 0.0, and every "grow the gold set to unblock Engine B / the
LLM reconciler" plan was chasing a gate that could never fire. (The
code-switch clips added 2026-07-15 were already in the set — they just
couldn't register.) Second, smaller defect: corpus BER was a ref-weighted
mean, so hypothesis switches hallucinated on zero-switch samples carried
weight 0 and were never penalized.

**The fix (metrics v2, `metrics.METRICS_VERSION = 2`):**
1. Switch points walk every *character* of every token; an intra-cue switch's
   timestamp is linearly interpolated across the cue's `[start_ms, end_ms]`
   by char offset (same approximation on both sides). Digits/punct are
   script-neutral. Pure-script token streams behave exactly as v1.
2. Corpus BER = `1 − micro-F1` over summed matched/ref/hyp switch counts
   (`metrics.boundary_f1_error`; per-sample counts now on `EvalMetrics.
   hyp_switches/matched_switches`).
3. **Baseline partitioning:** `eval_run.metrics_version` column (additive
   `_migrate`, pre-existing rows default v1). `get_last_passing_eval` and
   `create_eval_run` default to the current `METRICS_VERSION` — a metric
   change starts a fresh baseline instead of tripping the gate against
   incomparable numbers (the old v1 baseline had BER 0.0 with zero weight; any
   real v2 score would have "regressed" forever). Bump the version on any
   future metric-definition change.

**Proven on the real gold set (2026-07-16):** migrated `transcriber.db`
(16 rows stamped v1), ran the production harness: `CER_thai 0.1451`
(unchanged from the 2026-07-15 baseline — Thai scoring untouched),
`WER_latin 1.0452`, **`switches=104 (hyp 38, matched 10)` → `BER 0.8592`**,
passed=True as the fresh v2 baseline. The system's real code-switch gap is
now visible and gated: Engine A finds barely a third of the reference
switches.

**First decidable Engine-B probe (same session):** `harness --engine-b
funasr` (experiment row, baseline untouched): **BER improved 0.7882 vs
0.8592** (hyp switches 66 vs 38, matched 18 vs 10 — the decorrelated engine
genuinely finds switches Engine A misses) but **WER_latin regressed 1.2258
vs 1.0452** → gate blocked, correctly. CER_thai 0.1451 unchanged. Verdict
recorded at the time: a decorrelated Engine B is worth having for BER;
funasr specifically is too inaccurate on Latin words.

**⚠ CORRECTION (same session, after probing the LLM reconciler): the above
verdict is WRONG — retracted, not just superseded.** Probing `--engine-b
funasr --llm-enabled` produced metrics **byte-identical** to the plain
funasr run above (down to hyp_switches/matched_switches), which meant the
LLM tiebreak fired zero times. Instrumenting `align_hyp.align()` directly on
a gold clip confirmed why: **0 of 52 slots had both an A and a B candidate**
— faster_whisper and funasr's outputs never overlap enough to be treated as
a disagreement at all. Inspecting funasr's raw output explained that:
`result["text"]` carries an explicit `<|yue|>` (Cantonese) tag, and every
"word" token is a CJK Unified Ideograph codepoint (e.g. `困` '困'), not
Thai script. Checked SenseVoiceSmall's own model card: it documents exactly
five supported languages — `zh, en, yue, ja, ko` — **Thai is not one of
them**. With `language="auto"` (`engines/funasr.py`), its language-ID
misdetects Thai speech as Cantonese and decodes Chinese-script garbage
throughout. **The "BER improved 0.7882" and "WER_latin regressed 1.2258"
numbers above were measuring that garbage — not a genuine Thai-code-switch
accuracy tradeoff.** They are not evidence that a decorrelated Engine B is
or isn't worth having; they are evidence that SenseVoiceSmall cannot
transcribe Thai. This also retroactively explains the *older*,
pre-2026-07-16 "byte-identical to passthrough" funasr result noted elsewhere
in this ledger/CLAUDE.md — consistent with zero real A/B overlap having
existed the whole time, for the same underlying reason. **funasr/
SenseVoiceSmall is retired as a Thai-code-switch candidate** (see
`engines/funasr.py`'s corrected docstring) — not gated pending more gold
data, structurally incapable regardless of gold-set size. Don't re-probe it
without a different underlying model. Tests unaffected (no test asserted the
old, wrong conclusion — this was a documentation/interpretation error, not a
code defect with a regression test to write).

**Second probe: typhoon_rt (same session, 2026-07-16).** Installed
`nemo_toolkit[asr]==2.7.3` cleanly on this 3.11.9 venv (the Py3.13 wheel risk
in the code comments doesn't apply here). First attempt crashed with
`CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH` on typhoon_rt's very first conv
forward — traced to a real, separate bug (see "PATH-scoping bugfix" entry
below) and fixed. Re-run after the fix: **all 5 clips transcribed cleanly**,
but the result is a clear regression across every signal: `CER_thai 0.1601`
(vs 0.1451 baseline), `WER_latin 1.1290` (vs 1.0452), `BER 0.8537` (vs 0.8592
— a marginal 0.6pp gain, far short of funasr's 0.71). switches hyp=60,
matched=12. **Verdict: typhoon_rt does not currently earn Engine-B activation
— worse than funasr on every axis except a negligible BER edge.** Plausible
causes not yet investigated: this specific NeMo release/checkpoint pairing,
audio preprocessing mismatch (16kHz mono float32 assumed but not verified
against what `typhoon-asr-realtime.nemo`'s manifest expects), or the model
being tuned for streaming/short-utterance input rather than the ~30s+ whole-
file spans this adapter feeds it. **Due when:** don't re-try without new
evidence (mirrors the typhoon-whisper-turbo Engine-A precedent) — either
diagnose why NeMo's own reference eval numbers don't reproduce here, or move
on to a Qwen3-ASR adapter / `--llm-enabled` probe instead.

**PATH-scoping bugfix (same session, real bug, not NeMo/typhoon_rt-specific):**
`engines/faster_whisper.py`'s `_register_cuda_dll_dirs()` prepended nvidia
pip wheels' bin dirs (incl. a CUDA-12 `cudnn64_9.dll`) onto process-wide
`PATH` so CTranslate2 could find `cublas64_12.dll` — but never reverted it.
Any NeMo-based engine (torch 2.13+cu130, a different CUDA generation) loaded
afterward in the *same process* inherited that prepended cuDNN and crashed on
its first conv forward with `CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH`.
Confirmed via a minimal repro: calling only `_register_cuda_dll_dirs()` (zero
CTranslate2 model loaded) was sufficient to break typhoon_rt; typhoon_rt
worked fine standalone. **Fix:** the function now returns the pre-mutation
PATH; `FasterWhisperEngine.load()` captures it, `unload()` restores it — the
mutation is now load()-scoped instead of process-lifetime. This was silent
and untested before because no test or eval run had ever loaded a CTranslate2
engine and a NeMo engine in the same process — Engine B has been
`passthrough` since typhoon_rt's adapter was built. Would have bitten anyone
activating typhoon_rt in production. Tests: `tests/test_faster_whisper_
path_scoping.py` (3 new; suite 187 green).

**Third probe: whisper_multi + the LLM reconciler (same session, 2026-07-16)
— the first genuine test bed, and a real diagnosed finding.** Unlike funasr,
`whisper_multi` (Whisper large-v3) genuinely supports Thai, so this was the
first candidate where the LLM tiebreak could actually be exercised on real
disagreements.

`harness --engine-b whisper_multi --llm-enabled` (Ollama serving
`qwen2.5:3b-instruct` locally): **CER_thai regressed sharply to 0.2323**
(vs 0.1451 baseline — a ~60% relative increase), `WER_latin 1.0903` (mild
regression vs 1.0452), `BER 0.8616` (not better than 0.8592). An isolation
re-run (`--engine-b whisper_multi`, no `--llm-enabled`) produced **byte-
identical** numbers — the LLM tiebreak made zero measurable difference here
too, same symptom as the retired funasr probe but a *different* root cause
(whisper_multi is not broken like funasr — align_hyp genuinely produces
overlapping A+B slots against it, 12 of 26 on a sample clip, several with
real text differences).

Instrumenting `reconcile._pick()`'s `llm_fn` directly on one clip (11 real
disagreements) explains why: **the LLM picked Engine A (index 0) on all 11
of 11 calls** — including cases where Engine B's text was visibly longer and
more complete than Engine A's truncated cue. A 100% rate across diverse,
non-trivial disagreements is not credible as genuine semantic judgment; it
reads as a positional/first-option bias in `qwen2.5:3b-instruct` under the
current prompt. Two compounding, real defects found along the way:
1. **Prompt staleness bug** (`llm_reconcile.py`'s `_PROMPT_TEMPLATE`): it
   still says *"Two Thai speech-recognition engines disagree on **one
   word**"* — but tokens have been phrase cues since 5.4 (CLAUDE.md), so the
   model is actually shown two full sentences while being told to expect one
   word. Never updated when token granularity changed.
2. **`_script_fallback` degrades to pure script-routing here for an
   unrelated reason:** `engines/whisper_multi.py` hardcodes
   `confidence=None` on every token (deliberate — the contract's "never fake
   a confidence" rule, correctly followed), which means
   `_script_fallback`'s confidence-tiebreak branch never fires against it.
   Since most disagreements here are both-Thai-script, the script-routing
   fallback then also trivially picks A every time. So on every reconciled
   ("both A+B") slot, *neither* path — LLM or fallback — ever selects
   Engine B; the only way whisper_multi's content enters the final
   transcript at all is via the 12 unmatched "only-B" solo slots that pass
   straight through un-reconciled, and that's what drives the CER_thai
   regression (whisper_multi's own segmentation/accuracy on those unmatched
   spans is worse, diluting rather than correcting Engine A's output).

**Verdict: whisper_multi + LLM reconciler rejected on the current gold set —
but unlike funasr/typhoon_rt, this is NOT evidence the architecture can't
work.** It's evidence the *current* prompt and local model provide no
discriminative signal, compounded by a null-confidence engine collapsing the
fallback to a routing rule that happens to always favor A on same-script
disagreements. **Due next (in order of cheapest-to-test):**
(a) fix the prompt's stale "one word" framing to describe phrase-cue
comparison: (b) test with per-call randomization of which candidate is
presented as "A" vs "B" to separate genuine judgment from positional bias —
if index 0 still wins ~100% after randomization, the bias is confirmed and a
larger/better local model is needed; (c) reconsider whether `_script_fallback`
should have a non-confidence tiebreak (e.g. length/completeness heuristic)
for exactly this null-confidence-engine case, since the contract correctly
forbids faking confidence but the fallback currently has no fallback *within*
the fallback when confidence is absent on one side.

**Fourth probe: prompt fix + position randomization (same session,
2026-07-16, item (a)+(b) above executed).** `llm_reconcile.py` rewritten:
`_PROMPT_TEMPLATE` now describes segment/phrase-level candidates (never says
"one word"), and `make_llm_fn` randomizes per call which of (ta, tb) is shown
as prompt slot 0 vs 1, remapping the model's answer back to ta/tb afterward.
Tests: `tests/test_phase3_llm_reconcile.py` (+2: prompt no longer claims
single-word, swap/no-swap mapping verified directly; suite 189 green).

**Re-instrumented on the same clip:** the degenerate lock-in is confirmed
gone — `llm_idx` now varies (7 of 11 calls picked Engine A, 4 picked Engine
B), where before the fix it was 11 of 11 Engine A. The fix does exactly what
it was built to do: a model with positional bias no longer manifests as
"always trust Engine A."

**But the corpus-level harness result got WORSE, not better — report this
honestly, not as a clean win:**

| Config | CER_thai | WER_latin | BER |
|---|---|---|---|
| baseline (passthrough) | 0.1451 | 1.0452 | 0.8592 |
| whisper_multi, broken prompt (pre-fix), llm-enabled | 0.2323 | 1.0903 | 0.8616 |
| whisper_multi, **fixed prompt + randomized**, llm-enabled | **0.3505** | 1.0387 | 0.8658 |

CER_thai got substantially worse after the fix (0.3505 vs 0.2323), WER_latin
improved slightly (1.0387 vs 1.0903), BER is essentially flat/marginally
worse. **Diagnosis: this is not a regression in the fix — it's the fix
correctly exposing that `qwen2.5:3b-instruct`'s judgment on real
disagreements isn't good enough to beat the naive heuristic of always
trusting the stronger engine.** Before the fix, the degenerate "always pick
Engine A" bug was *accidentally* a decent heuristic on this gold set, because
Engine A (faster_whisper) is empirically the stronger engine here (lowest
CER_thai of any config tried all session, 0.1451). Once the reconciler can
genuinely pick Engine B and does so ~36% of the time, and Engine B's picks
are not reliably better, overall accuracy drops. This is a **model-quality
problem, not a bias/wiring problem** — categorically different from, and now
cleanly separated from, the bug that was fixed.

**Verdict: `llm_enabled: true` stays off. The wiring, prompt framing, and
positional-bias defect are now all fixed and tested — do not revisit those.**
What remains is a genuine open question: is `qwen2.5:3b-instruct` too weak
for this task, or does the prompt need few-shot examples / more context
(surrounding tokens, not just the two candidates) to reason well? **Due
next:** try a larger local model (`qwen2.5:7b-instruct` is already referenced
in this file's own docstrings/tests as a plausible next step) before
concluding the LLM-tiebreak approach itself doesn't work — the current
result rules out the *specific* small model + minimal-context prompt tried
here, not the architecture.

**Known limitation (accepted):** intra-cue interpolation assumes uniform
character rate; on long cues the placement error can approach
`boundary_tol_ms` (300 ms). Both sides share the bias, so matches survive in
practice. **Due when:** if real A/B probes show BER noise swamping signal,
widen `boundary_tol_ms` or re-derive switch timestamps from
`engine_result.raw_words_json` word timings instead of interpolation.

**Environment finding (same session):** DeepFilterNet denoise is silently
dead on this venv — `df.enhance` imports `torchaudio.backend`, which
torchaudio 2.x removed, so `_apply_rolling_denoise` warns and returns the
raw audio whenever a chunk engine activates (`denoise: true` is a no-op).
Harmless today (the production engine is whole-file, denoise already skipped
by design), and possibly net-positive to leave dead (INFRA-6 in the 2026-06
audit questioned whether denoise helps at all). **Due when:** a chunk engine
is activated for production — either pin/patch DeepFilterNet for torchaudio
2.x, or measure a denoise-off baseline and delete the path.

## Four confirmed-issue fixes — executed 2026-07-15 (after the diff-srt pass)

Suite: **176 passed** (was 167; +9 new tests across three new files).

1. **Eval regression-baseline partitioning (integrity).** An A/B probe
   (`harness --engine-b X` / `--llm-enabled`) wrote a normal `eval_run`; if it
   passed, `get_last_passing_eval` would hand it to the next production run as
   the baseline. Fixed with an `eval_run.is_experiment` column (schema.sql +
   idempotent `_migrate` add): `run_harness(..., experiment=True)` marks the
   row, `get_last_passing_eval` excludes it, and the harness CLI implies the
   flag for `--engine-b`/`--llm-enabled` (plus an explicit `--experiment`).
   An experiment is still *judged against* the production baseline — it just
   can never *become* it. **Design note:** the alternative fix — filtering the
   baseline by the current run's `engine_pair`/`bias_hash` — was rejected
   deliberately: the flywheel gate exists to compare an engine swap or bias
   update AGAINST the previous config's baseline, so partitioning lineage by
   those columns would hand every swap/update an empty baseline and a free
   pass. Partition on intent (experiment vs production), not on config
   identity. Tests: `tests/test_eval_baseline_partitioning.py` (store-level
   exclusion + the baseline → passing-experiment → production round-trip).
   **Migration note:** any pre-existing `transcriber.db` (the live/local DB —
   gitignored, not shipped in the repo) predates the `is_experiment` column
   and must run `init_db()` once (idempotent `_migrate`, additive-only, no
   data touched) before the harness will run against it — it fails fast with
   `sqlite3.OperationalError: no such column: is_experiment` otherwise.
   **Confirmed on the real gold set (2026-07-15):** ran
   `python -m transcribe.eval.harness --config transcribe/config.yaml --db
   transcriber.db` after migrating — passed, cer_thai 0.1451 vs prior baseline
   0.1486 (improved), wer_latin/BER unchanged. No regression from this pass's
   four fixes. `switches=0` still holds (gold set has no code-switch samples
   yet), so BER/Engine-B activation remain unproven either way — unchanged
   from the pre-existing known gap.

2. **Stitch seam-window dedup.** `stitch()` compared each candidate only
   against `kept[-1]`, so an A-B-A' pattern (duplicate copies of a seam word
   separated by an intervening token from the other chunk) kept the duplicate.
   It now scans all recently-kept tokens whose span ends within
   `seam_window_ms` of the candidate's start (interiority/confidence
   tie-breaks unchanged; output re-sorted since an interior replacement can
   nudge ordering). Call sites thread the real overlap: `run.py` passes config
   `chunk_overlap_ms`, faster_whisper's long-span path passes its 4 s window
   overlap. Tests: `tests/test_stitch_seam_window.py`.

3. **Cue target width in config.** `_CUE_TARGET_CHARS` (42) was hardcoded
   while its siblings `cue_gap_ms`/`cue_max_ms` were config-driven — and
   `transcribe()` wasn't even passing it, silently always using the default.
   Now `engines.faster_whisper.cue_target_chars` in config.yaml → constructor
   kwarg → `_group_words_into_cues`. Named `cue_target_chars` (not bare
   `target_chars`) to match the `cue_*` kwarg family. Tests:
   `tests/test_cue_target_chars_config.py` (constructor override, default =
   module constant, capture test proving the value reaches the grouping,
   functional shorter-cues test).

4. **Engine-reuse state-bleed audit — CLEAN; don't re-investigate blind.**
   No `language_hint`/`bias_terms` bleed exists across chunks or jobs within a
   process. Checked (2026-07-15): `registry.get_engine` returns a fresh
   `cls(**kwargs)` per call, and nothing in `transcribe/` caches an engine
   instance (grep `get_engine|lru_cache|_ENGINE|engine_cache` — only run.py
   calls it); `run.py` engine instances live for exactly one `run_file` and
   are `del`'d, `bias_terms`/`bias_weights` are re-read from the DB per job,
   and language hints are per-call literals ("th" for A, None for B); every
   adapter builds its per-call kwargs *inside* `transcribe()`/
   `transcribe_batch()` (whisper_thai/whisper_multi: `generate_kwargs` +
   `prompt_ids` fresh each call; faster_whisper: `initial_prompt` + `common`
   dict fresh, and the OOM-halved `bs` is a local never written back to
   `self._batch_size`; funasr: `cache={}` fresh per call — the classic FunASR
   bleed vector — and hotword rebuilt per call; typhoon_rt holds only the
   model); `_batch.py` retries hand the HF pipeline fresh dict wrappers
   (fixed 2026-06-18) and never mutate `generate_kwargs`; `inject.build_prompt`
   uses `sorted()` (copies) and fresh `BiasTerm` objects, so the *shared*
   `bias_terms` list that rides in every chunk's `EngineInput` is never
   mutated. Two non-bleed observations recorded for posterity: (a)
   `language_hint` is *honored* only by faster_whisper — whisper_thai forces
   `"th"`, whisper_multi/funasr force auto-detect (each documented/deliberate);
   (b) whisper_* `transcribe_batch` builds its bias prompt from `inputs[0]`
   under a documented same-job assumption. **Due when:** any caller ever
   batches `EngineInput`s across jobs or bias sets in one `transcribe_batch`
   call — the `inputs[0]` prompt assumption then breaks silently.

## diff-srt flywheel path — executed 2026-07-15

The web editor's correction capture (diff.py) only matches original vs.
corrected tokens by `idx`, which breaks the moment a final NLE pass (Premiere
Pro: re-time, re-cut, merge, split cues) is fed back in — there was previously
no path for that at all, and `update_bias_index` had zero production call
sites (only tests called it, confirmed via grep).

Built: `transcribe/srt_io.py` (parse_srt relocated out of tools/make_gold.py,
which now re-exports it); `transcribe/flywheel/align_srt.py` (connected-
components-over-time-overlap grouping — handles merge/split/deletion/insertion
without special-casing each; a timebase-divergence guard measured as *matched
coverage* rather than raw min/max span, so a normal edit that adds a trailing
title/outro card doesn't false-positive as a wrong-file mismatch); promoted
`diff.py`'s `_extract_changed_span` to public `extract_changed_span` for reuse
(second concrete use). `scripts/learn_from_srt.py` CLI: prints a match/mismatch
summary before writing anything (mirrors make_gold's draft→freeze ceremony),
requires `--yes` or an interactive confirm, then writes corrections and (unless
`--no-promote`) calls `update_bias_index(..., run_regression_gate=True)` —
closing the promotion gap above. 19 new tests (`test_align_srt.py`,
`test_learn_from_srt.py`); full suite 167 green.

**Known simplification, not a bug:** a merged/split group's correction row is
owned by the group's *lowest* original `token_idx` (the `correction` table is
keyed one row per original token; there is no schema concept of a many-token
group). Reopening that job in the web editor will only show that one idx as
"corrected" — the other merged-away idxs still display raw text. **Due when:**
the web editor needs accurate per-idx corrected-state display for a job that
went through an SRT re-import — would need either a nullable
`group_token_idxs` JSON column (additive migration, low regret) or a separate
join table.

**Also deferred:** `update_bias_index`'s real GPU regression-gate path (run_harness
with pipeline_fn=None) is exercised only via monkeypatch in
`test_learn_from_srt.py` — the gate's own pass/rollback correctness is already
proven in `test_phase5_flywheel.py`, so this wasn't re-proven end-to-end on real
audio. **Due when:** the gold set grows enough to make a real `learn_from_srt`
promotion worth measuring (same gate as Engine B/LLM-reconciler, see the
2026-07-15 entry below).

## IMPLEMENT_IMPROVEMENTS.md pass — executed 2026-07-14

Fixed with tests (`tests/test_improvements_202607.py`, suite 116 green):
harness scratch-DB bias-index mirroring (eval was running prompt-less);
correction upsert per (job, token) + revert deletion (re-saves were stacking
duplicate rows and inflating flywheel counts); editor job view merges saved
corrections; empty corrected text never promoted as a bias term;
`get_last_passing_eval` filters kind + id tie-break; mai-yamok spaced-repeat
collapse; `sent_tokenize` import inside its best-effort try; exception lexicon
expanded; dead `_config()` removed from editor server.

**Environment truth (2026-07-14):** the working venv is **Python 3.11.9** —
`funasr` and `editdistance` import fine. The "no Py3.13 wheel" blocker recorded
below for FunASR/NeMo does not apply to this venv; Engine-B activation is
eval-gated only. CLAUDE.md/config comments still say 3.13 — update them when
Engine B lands.

**Update (2026-07-15): all six phases executed.** Gold set live (4 clips);
typhoon-whisper-turbo Engine A tried and reverted (lost the gate); decorrelated
Engine B (`funasr`) wired and eval-tested but left `passthrough` (correctly
gated — see below); LLM reconciler (`llm_reconcile.py`, local Ollama) wired and
gated off (`llm_enabled: false`); resumability/raw-word persistence
(`job_phase` + `engine_result` table) done; editor reason-tag/confidence/
corrected-state UI done. `pytest tests/` → 148 passed. Full detail and
resolution notes: IMPLEMENT_IMPROVEMENTS.md §2 (each phase now has a
**Resolution** block). **Remaining due-when:** Engine B / LLM-reconciler
activation is still gated on a gold set with real code-switch-heavy or
noisy material — the current 4 clips have `switches=0`, so the gate can't yet
prove either feature earns its runtime. Grow the gold set to make that call.

## HANDOFF_SPEED_AND_ROBUSTNESS — executed 2026-07-06

Phases 1–7 landed; full suite 97 green (`pytest tests/`). New acceptance tests:
`test_phase1_robustness`, `test_phase2_config`, `test_phase3_ingest`,
`test_phase4_typhoon`, `test_phase5_flywheel`, `test_phase6_evalperf`,
`test_phase7_makegold`.

- **P1 corruption:** loop-collapse defanged (digits/short-unit safe, logged);
  empty gold set no longer writes an eval_run (returns None, CLI exits non-zero);
  reconciler assert → `ReconcilerViolation` raise.
- **P2 config:** VAD threaded (was already) + Silero migrated to the `silero-vad`
  pip package (torch.hub fallback); flywheel constants threaded through
  `update_bias_index`/`build_prompt_ids`; per-engine `config["engines"][name]`
  kwargs (YAML-only engine/compute swap).
- **P3 speed:** faster-whisper now runs `BatchedInferencePipeline` with OOM-halving
  (`tools/bench_transcribe.py` added); ingest decodes **once**, skips denoise for
  whole-file engines, and emits `chunk_overlap_ms` overlap so stitch works.
- **P5 flywheel:** budgeted+weighted bias prompt with a CT2 token counter; harness
  is the single gate authority (returns `HarnessResult`, no self-comparison,
  `_passed_gate` deleted); sub-cue span diffing (`corrected_span` column) +
  ≤30char/≤6word promotion guard; `word_level_timestamps` → `timestamps_final`,
  raw per-word list kept in `EngineResult.raw["words"]`.
- **P6 hygiene:** rapidfuzz Levenshtein (pure-Python fallback); scratch-DB eval
  isolation (already in); `align_hyp` sliding-window linearization (property-tested
  vs brute force); `CREATE_NEW_CONSOLE` guarded by `sys.platform`.
- **P4 Engine B:** `typhoon_rt` NeMo adapter built + contract-tested (mock), `--engine-b`
  harness override added. **NOT activated** — see below.
- **P7 gold set:** `tools/make_gold.py` draft→freeze round-trip, end-to-end tested.

**Remaining (hardware / human, not code):**
- **P3 real-footage bench:** run `tools/bench_transcribe.py <5-min clip> --compare-sequential`
  on real Thai speech — record RTF (target ≥3× sequential) + confirm <1% batched-vs-
  sequential CER. Validated only on synthetic audio here (wiring proven on the 3070).
- **P4 NeMo Py3.13:** `nemo_toolkit[asr]` install on Python 3.13 is **unverified**
  (heavy C-dep tree; this is what killed FunASR). Do NOT install into the working env
  until activating; if it won't install, check the model's ONNX export / standalone
  inference path. Activation is eval-gated regardless (engine_b stays `passthrough`).
- **P4.3 two-pass `--draft` mode:** deliberately **not built** (YAGNI — a workflow
  luxury the handoff marks optional; build when a real fast-draft need appears).
- **P7 human step:** transcribe-and-correct 10–15 min of representative own footage
  (code-switch-heavy + noisy) so the eval-gated Engine-B / bias decisions can be measured.

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

- **GAP-4 chunk overlap (other half). ✅ DONE (2026-07-06).** `ingest.ingest`
  now emits `chunk_overlap_ms` (default 750) overlap between adjacent VAD chunks
  via `_materialize_chunks`, so stitch.py dedupes seam words instead of being a
  no-op. Only active when a chunk engine runs (whole-file engines skip chunking
  entirely). Tested in `test_phase3_ingest`.
- **GAP-5 prompt injection — GPU verification. ✅ DONE (2026-06-11).** Proven on
  the RTX 3070 with transformers 5.9.0: `get_prompt_ids` exists and the pipeline
  accepts `prompt_ids`; transcribe ran clean with and without bias terms.
  Residual: whether bias terms measurably *improve* accuracy is an eval question,
  not a wiring one — settle it once the gold set has real bias-sensitive samples.
- **GAP-2 VFR conform — this entry was STALE, re-checked and fixed
  2026-08-10.** The claim above ("no CFR-proxy transcode is implemented...
  XML export does not yet refuse") was already false by the time it was
  checked: `transcribe/timebase.py::conform_vfr` (real ffmpeg `-vsync cfr`
  transcode + re-probe) and `cutdeck/xml_export.py`'s VFR refusal +
  config-gated conform-and-substitute wiring were both built in commit
  `3ed175f` ("Phase 4 robustness") with their own test file
  (`tests/test_vfr_conform.py`) — this ledger entry just never got updated
  to reflect it. **But re-checking it for real (not just re-reading the
  code) surfaced a genuine live bug the existing unit tests never caught**:
  `cutdeck/plan.py`'s `CutPlan` JSON round-trip (`to_dict`/`from_dict`, what
  `save_plan`/`load_plan` use) never serialized `Timebase.is_vfr` at all — so
  a real VFR source's plan came back `is_vfr=False` the instant it was saved
  to the `cut_plan` table and reloaded, which is *exactly* what
  `xml_export.py`'s CLI (`main()`) always does (`propose_for_job` correctly
  sets `is_vfr` from the media row via `_timebase_from_media`, but nothing
  downstream of a save+reload ever saw it). Both the refusal check and the
  conform path were dead code on the only path that matters in production;
  every existing test exercised `to_xml()`/`conform_vfr()`/
  `_conform_vfr_enabled()` directly with a hand-built `Timebase`, never
  through the real DB round-trip, so this was invisible. **Fixed**:
  `to_dict`/`from_dict` now round-trip `is_vfr` (`from_dict` defaults it to
  `False` for legacy `plan_json` rows with no `is_vfr` key, so old DB rows
  don't crash). 5 new tests: JSON-level round-trip for both `True`/`False`,
  legacy-row default, a DB-store-level round-trip, and two `main()`-level
  integration tests (`tests/test_vfr_conform.py`) that save a real VFR plan
  to a real temp DB and drive the actual CLI — one proving it now correctly
  refuses without the config flag (the exact case that used to silently
  export instead), one proving it calls `conform_vfr` and exports against
  the conformed proxy path when `conform_vfr: true`. Full suite: **483
  passed** (was 478).
- **GAP-6 gold-set promote CLI. ✅ DONE (2026-07-06).** `tools/make_gold.py`:
  `draft` (from a corrected editor job via `--job-id`, or `--run` the pipeline) →
  hand-correct the `.draft.json` → `freeze` (validates schema/script/monotonic
  time, refuses to overwrite a frozen file without `--force`). End-to-end tested
  (`test_phase7_makegold`). **Human step remains:** author 10–15 min of real gold.
- **GAP-7 editor reason UI. ✅ DONE (2026-07-15, commit `9a618f8`).** Column + API + diff plumbing done; the one-tap tag
  UI in `static/index.html` shipped in the same commit (this entry was stale
  — corrected 2026-08-05). The "merged-group corrected-state display" idea
  formerly listed here as residual was checked with the user (2026-08-05) —
  no spec ever existed for it and it wasn't a real need; dropped, closed.
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

### HANDOFF_CUTDECK_WORDLEVEL.md (word-level cutting + rough-cut restructure)

Separate phase numbering from the Part B phases above — see the handoff file
for the full plan (Phases 0–6).

- **Word-timeline Phase 1 — DONE (2026-08-03).** `cutdeck/words.py`: `Word`,
  `words_from_pieces`, `words_for_job`, `timed_tokens` (char-timeline +
  `pythainlp.word_tokenize` reconstruction, factored out of
  `faster_whisper._group_words_into_cues` so there's one implementation).
  8 tests in `tests/test_cutdeck_words.py`.
- **Word-level cuts Phase 2 — DONE (2026-08-04).** `rules.filler_cuts` revived
  on the Word timeline instead of dead phrase-cue-token matching (F1 fixed);
  new `rules.repeat_cuts` (deterministic stutter/duplicate-word n-gram
  detector, segment-bounded, no LLM); `CutSpan.blade` (`BLADE_VAD`/
  `BLADE_WORD`) threaded through the merge/assemble/coalesce pipeline and
  serialized in the plan JSON; `xml_export.to_xml` emits an audio-only FCP7
  crossfade transition on word-blade junctions (VAD-blade junctions stay hard
  cuts). All three gated off by default (`cut.repeats_enabled: false`,
  `fillers_enabled` already false). 18 new tests in
  `tests/test_cutdeck_phase2.py`; full suite 248 collected, 247 green (the one
  failure is the pre-existing `pycrfsuite`-missing gap on this Python 3.13
  shell, unrelated). **Not yet done:** the XML crossfade is a plausible
  approximation (no source overlap/trim) pending Phase 3's real Premiere
  import acceptance — revisit fidelity once that passes.
- **Preview Phase 3 — DONE (2026-08-04).** `cutdeck/preview.py`: ffmpeg
  concat-demuxer stream-copy render of a plan's KEEP spans
  (`python -m cutdeck.preview --job-id N [--reencode] --out preview.mp4`),
  labelled approximate in both the output filename (`_approx` suffix) and the
  CLI print unless `--reencode`. `render_preview`/`keep_ranges_ms` are
  independently importable for future callers (review UI). 7 new tests in
  `tests/test_cutdeck_preview.py`, run against the real ffmpeg on PATH (a
  synthetic forced-keyframe `lavfi` clip, not mocked) — GOP-tolerance
  duration match, cut-shortening, `--reencode` frame accuracy, missing-ffmpeg
  clear-error, no-keep-spans ValueError. Full suite: 255 collected, 254
  green / 1 pre-existing unrelated failure (see above).
- **Segment-first rough cut Phase 4 — DONE (2026-08-04), opt-in.**
  `cut.rough_cut_mode: interval | segment` (default `interval`, byte-identical
  to before). `segment` mode builds keeps outward from segments instead of
  subtracting VAD silence out of the whole timeline: `rules.label_segments`
  (first real producer of the long-unused `Label` type) + `_segment_gap_cuts`
  replace rules 1+3 (silence cuts + min-clip merge) — a kept segment is an
  utterance by construction, so `apply_min_clip_merge`'s `dissolved_ms`/
  `_STANDALONE` machinery is never invoked in this mode at all. Verified
  against the three real-world bug fixtures that machinery exists for
  (tokenless blip between long silences, chained tokenless blips, short
  real-word islands either side of a pause) — segment mode reaches the same
  correct plans with zero merge/dissolve logic involved. 13 new tests in
  `tests/test_cutdeck_phase4.py`; full suite 268 collected, 267 green (same
  pre-existing `pycrfsuite` gap, unrelated). **Still open, per the handoff:**
  the real Premiere XML import acceptance — Phases 5–6 (dead-air wins,
  takes.py) stay blocked on it; `segment` mode itself stays opt-in until
  watched on real footage via `cutdeck/preview.py`, then the old `interval`
  path + `apply_min_clip_merge` become a deletion candidate in a follow-up
  commit (not done here, per the handoff's own instruction).

## Stitch fuzzy seam-text dedup (issue #8) — DONE (2026-08-20), scope is
## deliberately narrow and `_FUZZY_FRAGMENT_MAX_MS` recalibration needs real data

`transcribe/pipeline/stitch.py`'s duplicate detection only fired on exact
text match, so when two overlapping faster_whisper decode windows tokenized
the same Thai run at *different sub-word split points* (not just different
boundaries of the same text — see the pre-existing `_coincident` fix above,
2026-07-30), neither fragment deduped and both survived into the transcript
as a doubled-syllable stutter (`ผู้หญิง` → `ผหู้หญิญิง`). New
`_fuzzy_same_word()` supplements the exact-text gate: containment or a
boundary-anchored suffix/prefix overlap (`_MIN_FUZZY_OVERLAP = 2` chars),
gated by `_FUZZY_FRAGMENT_MAX_MS = 80` so at least one side must be as brief
as a genuine sub-word ASR piece — still behind the existing `ci != pci`
cross-chunk guard and `_iou`/`_coincident` temporal check. 9 tests in
`tests/test_stitch_fuzzy_seam_text.py`; full suite 554 green.

**Four independent correctness-gate rounds, four real defects found and
fixed in the same session** — the design's scar tissue is documented in both
the module comment above `_fuzzy_same_word` and the test file's docstring:

- Round 1 (generic SequenceMatcher ratio) false-merged distinct 2-char Thai
  particles sharing one character (`มา`/`นา` etc. — ratio 0.5,
  indistinguishable from a real split-point match).
- Round 2 (anchored overlap, no duration check) false-merged real,
  unrelated, correctly-decoded words sharing a 2+ char boundary morpheme
  (`หมา`/`มานะ`, `ขนม`/`นมสด`, `ตลาด`/`ลาดยาง`).
- Round 3 (`_FUZZY_FRAGMENT_MAX_MS = 150`) fixed that but was itself too
  tight, and — worse — was reasoned from a **misread citation**: raising it
  to 250ms to cover a "missed" ~200ms split-point duplicate was justified by
  pointing at this file's own cited `อะไร` (160ms) measurement, but that
  figure is the duration of an EXACT-text token from the pre-existing
  `_coincident` mechanism, not evidence about fuzzy-matched fragment
  durations. This codebase has never had a real measured example of a fuzzy
  split-point duplicate's duration.
- Round 4 confirmed the consequence of that misread: at 250ms, the round-2
  false-merge class was live across essentially the *entire* 0-250ms range
  for the documented dangerous word pairs — ordinary short-word speech, not
  a rare edge, directly contradicting the "narrowed to a brief/clipped
  residual" framing this ledger's previous version used.

**Resolution: stop inventing thresholds, reuse the one number this file
already has evidence for.** `_FUZZY_FRAGMENT_MAX_MS` is now 80ms —
`_COINCIDENT_MS`'s own established range for genuine sub-word ASR pieces
(20-80ms, cited from real clip measurements in the comment above
`_COINCIDENT_MS`). This is a real, deliberate narrowing of scope, not a
tuning compromise: a differently-split duplicate whose pieces both run
longer than 80ms (`test_longer_split_point_duplicate_is_a_disclosed_gap_not_a_bug`
documents this explicitly) will NOT be deduped by this path and may still
ship as a stutter. That is accepted: a missed cosmetic stutter (the user
already hand-recuts exported SRTs in Premiere) is cheaper than this path
silently dropping a real spoken word, which is what every wider value tried
here did to ordinary Thai word pairs. The round-2 false-merge class still
has a residual at this narrower cap too (a genuinely brisk <=80ms rendering
of a short real word can still collide — `test_fuzzy_same_word_helper`'s
last assertion documents this) but 80ms is genuinely brief for a 2-4
character word, not ordinary pace, unlike 150-250ms.

**Trigger:** `stitch()` logs every fuzzy dedup (`logger.debug`, texts +
durations) specifically so this stops being guesswork. Once a real job with
a long pause-free multi-window span (e.g. re-running job 35 / `Short1.mp3`
from issue #8, or any clip that logs `Long pause-split span decoded as N
overlapping window(s)`) has been processed with `logger.debug` enabled, pull
the `"Fuzzy seam dedup:"` log lines and use the real duration distribution
to (a) decide whether `_FUZZY_FRAGMENT_MAX_MS` should move at all, and (b)
check whether the round-2 residual has fired on real speech. **Do not tune
this threshold again from a synthetic example** — every prior round's
mistake, including the 250ms misread, came from reasoning about one
constructed example instead of a real distribution.
