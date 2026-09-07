# MAINT_LOG

Append-only intervention history. Owner: `evolve-maintain`. One entry per
intervention: `ID | date | class | symptom | root cause (evidence tag) |
treatment | blast radius | strengthened-by | follow-ups`. Audience is the
next maintainer, likely a future AI model with no chat history — write so
that model can pattern-match a new symptom against past root causes in one
read.

---

## MAINT-001 | 2026-08-20 | Fix | doubled-syllable stutter at overlapping decode-window seams (issue #8)

**Symptom:** on a long pause-free audio span, faster_whisper decodes it as
multiple overlapping windows (`_LONG_SPAN_SAFE_S`/`_LONG_SPAN_OVERLAP_S` in
`transcribe/engines/faster_whisper.py`); the two windows sometimes tokenize
the same Thai syllables at *different sub-word split points* in the overlap
zone, producing a visible doubled-syllable stutter in the shipped transcript
(`ผู้หญิง` → `ผหู้หญิญิง`, evidenced against job 35, `Short1.mp3` — see issue
#8 for the full correction table and seam-alignment evidence).

**Root cause (proven, trace-only diagnosis + regression-test evidence):**
`transcribe/pipeline/stitch.py`'s `stitch()` only ever dropped a duplicate
when both windows produced **exact matching text** for the same word
(`same_word = tok.text.strip() == ptok.text.strip()`). This is a distinct
mechanism from the 2026-07-30 `_coincident` fix (same file): that fix closed
the case where two windows agree on a piece's *text* but disagree on its
*timestamp* by a few ms. Issue #8 is the case where the windows disagree on
the *text itself* — because they chose a different sub-word boundary — so
the exact-text gate never even reached the temporal check, and both
non-identical fragments survived to concatenate.

**Treatment:** added `_fuzzy_same_word()` to `stitch.py`, consulted only
alongside the existing temporal check (`_iou`/`_coincident`) and the existing
cross-chunk guard (`ci != pci`) — additive, never a replacement for the
exact-text path. Went through **four** rounds of independent `correctness-gate`
review inside this same session, each finding a real defect in the version
before it (full detail in `TODO_LEDGER.md`'s matching entry and in
`stitch.py`'s own comment above `_fuzzy_same_word`):

1. Similarity-ratio version (SequenceMatcher >= 0.5) → false-merged distinct
   2-char Thai particles sharing one character (`มา`/`นา` etc).
2. Anchored-overlap version (containment / suffix-prefix match >= 2 chars,
   no duration check) → false-merged real, unrelated words sharing a 2+ char
   boundary morpheme (`หมา`/`มานะ`, `ขนม`/`นมสด`, `ตลาด`/`ลาดยาง`).
3. Duration-capped version (`_FUZZY_FRAGMENT_MAX_MS = 150`) → fixed (2), but
   failed to dedupe a constructed longer split-point duplicate (both sides
   ~200ms) — a false negative on the bug the fix exists to catch.
4. Raising the cap to 250ms to cover that case was **reasoned from a
   misread**: the `อะไร` 160ms figure cited to justify it is the duration of
   an EXACT-text token from the pre-existing `_coincident` mechanism, not
   evidence about fuzzy-matched fragment durations — this codebase has no
   real measured example of the latter. Round 4 confirmed the actual
   consequence: at 250ms the round-2 false-merge class was live across
   essentially the *entire* 0–250ms range for the documented dangerous word
   pairs, i.e. ordinary short-word speech, not a rare edge.

**Final treatment (round 5): stop inventing thresholds.**
`_FUZZY_FRAGMENT_MAX_MS = 80` reuses the one duration figure this file
already has real evidence for — `_COINCIDENT_MS`'s own established 20-80ms
range for genuine sub-word ASR pieces (cited from real clip measurements).
This is a deliberate scope narrowing, not a compromise value: a
differently-split duplicate whose pieces both run longer than 80ms is **not**
caught by this path and may still ship as a stutter (accepted and disclosed
— `test_longer_split_point_duplicate_is_a_disclosed_gap_not_a_bug` locks
this in as intentional). The round-2 false-merge class still has a residual
at 80ms too (a genuinely brisk <=80ms real short word can still collide —
`test_fuzzy_same_word_helper`'s last assertion documents it) but 80ms is
genuinely brief for a 2-4 character word, unlike the 150-250ms range round 4
showed was ordinary pace.

**Blast radius:** `transcribe/pipeline/stitch.py` only (`_fuzzy_same_word`
new; `same_word` widened; `_prefer()` untouched — confirmed unchanged by all
four gate rounds). No contract, schema, or config change. Runs pre-existing
in the pipeline (`stitch()` is already called post-engine, pre-align_hyp);
no new call sites.

**Strengthened-by:** `tests/test_stitch_fuzzy_seam_text.py` (10 tests) — the
original issue mechanism (truncated-prefix and different-split-point
duplicates, both at genuine sub-word scale), a dedicated regression test per
gate round's false-merge finding, one test that locks in the round 3/4
false-negative as an intentionally accepted gap rather than silently
reopening it, and one (`test_brief_zero_gap_real_words_can_still_collide`,
added after a round-5 gate finding) that exercises the accepted round-2
residual through `stitch()` itself rather than only at the helper level.
Full suite 555 green (was 545 pre-intervention).
**Observability debt closed in the same changeset:** `stitch()` now logs
(`logger.debug("Fuzzy seam dedup: ...")`) every dedup the fuzzy path (as
opposed to exact-text) caused, with both texts and durations — this is what
the recalibration follow-up below actually needs and what all five gate
rounds had to work around by constructing synthetic examples instead.

**Round 5 gate result: `GATE: pass`.** An independent correctness-gate run
confirmed the issue #8 mechanism and the round-2 false-merge class (at
realistic durations) are both correctly handled, ran a mutation
spot-check (disabling the fuzzy path, removing the duration gate, and
loosening `_MIN_FUZZY_OVERLAP` each broke the suite, confirming the tests
are sensitive to the mechanisms that matter), and found one residual
worth closing: the already-disclosed "brief real word can still collide"
edge was only exercised at the `_fuzzy_same_word` helper level, not proven
reachable through `stitch()` itself. Closed in the same session — see the
new test above and the module comment above `_FUZZY_FRAGMENT_MAX_MS`.

**Follow-ups:** `TODO_LEDGER.md` — "Stitch fuzzy seam-text dedup (issue #8)"
entry carries the recalibration trigger: once a real job with a long
pause-free multi-window span has been processed with the new debug log
enabled, pull the `"Fuzzy seam dedup:"` lines and use the real duration
distribution to decide whether `_FUZZY_FRAGMENT_MAX_MS` should move at all,
and check whether the round-2 residual has fired on real speech. Do not tune
this threshold again from a synthetic example — every prior round's
mistake, including the 250ms misread, came from reasoning about one
constructed example instead of a real distribution.

`MAINT MAINT-001: resolved(Fix, proven)`

---

## MAINT-002 | 2026-08-25 | Fix | UXP spike18 panel loaded but never painted (issue #18)

**Symptom:** `uxp/spike18_split_probe/` loaded into Premiere Pro (v26.3.2.2
Debug) via UXP Developer Tool with zero console errors, but the panel body
never rendered — confirmed via DevTools that the DOM was fully populated and
layout computed a real (non-zero) box model, and that even a zero-dependency
test page (`<body style="background:red">` + inline `<h1>`, no CSS/JS)
painted nothing.

**Root cause (proven — via a live control test the director ran):** that
evidence chain only proved the plugin's HTML/CSS/JS weren't the cause; it
was initially misread as proof the *host* was at fault (documented, then
superseded, in the spike's own `README.md`). The actual test that
disambiguates — Adobe's own official sample panel
(github.com/AdobeDocs/uxp-premiere-pro-samples) on the identical install —
rendered fine, ruling the host out. Diffing `manifest.json` against Adobe's
two current live sample manifests found real schema divergences:
`preferredDockPosition: "floating"` is not a field in the current schema
(zero hits searching the whole sample repo); the real fields are
`preferredFloatingSize`/`preferredDockedSize`. `manifestVersion` was the
string `"5"` instead of the real bare number `5` — apparently accepted by a
laxer/legacy parser that skipped real validation, which is consistent with
a plugin that loads but never paints. Fixing `manifestVersion` to the real
number turned on strict validation, which then correctly rejected the
plugin outright (`Expected atleast a single entry in the icons list`) —
confirming the diagnosis rather than being a new problem: both real Adobe
samples declare populated `icons` arrays (top-level and per-entrypoint)
that this manifest never had.

**Treatment:** `manifest.json` — `manifestVersion` back to the bare number
`5`; `preferredDockPosition` replaced with `preferredFloatingSize` +
`preferredDockedSize`; added a populated top-level `icons` array and an
entrypoint `icons` array, both pointing at a new placeholder
`icons/icon.svg`. Confirmed live: panel now loads and paints.

**Blast radius:** `uxp/spike18_split_probe/manifest.json` and a new
`icons/icon.svg` only — throwaway spike scope, nothing wired into
`cutdeck/`, `bridge.py`, or `mark_export.py`. Two earlier same-day commits
(`a1668d4` manifest host-id fix, `06a52c9` CSS flex-sizing fix) were real,
independently-correct fixes that did not resolve this symptom — this was a
third, distinct manifest defect, not a redo of either.

**Strengthened-by:** nothing automated (a UXP panel has no test harness in
this repo) — evidence is the live reload the director ran, confirming both
load (no more validation error) and paint.

**Follow-ups:** `icons/icon.svg` is a throwaway placeholder — replace with a
real icon before this graduates past spike status. The split-logic
questions issue #18 exists to answer (clone/trim call order, single-
transaction undo behavior) are now unblocked but still fully untested — see
`uxp/spike18_split_probe/README.md`.

`MAINT MAINT-002: resolved(Fix, proven)`

---

## MAINT-003 | 2026-08-26 | Fix | every CLI exits 1 on a Thai path after fully succeeding

**Symptom:** `python -m cutdeck.xml_export --job-id N` wrote the XML, flipped
`cut_plan.status` to `exported`, then died with `UnicodeEncodeError` and exit
code 1 while printing its own success line. Same shape in
`scripts/export_job.py` (the daily SRT export), `cutdeck.preview`,
`cutdeck.plan --dry-run`, and `cutdeck.sequence_mixdown --dry-run`. The user
sees a traceback and a failing exit code for work that completed; a wrapper
script reading the exit code concludes the export never happened and may retry
or abort. This is a **false failure report**, not a cosmetic print bug — that
distinction is the whole severity, because the artifact and the DB commit are
both already durable by the time the crash fires.

**Root cause (proven — reproduced, then re-reproduced through the real CLI):**
plain `print()` of a media-derived path. Every real footage folder in this
project is Thai (`โหน(หลัง)กระแส`, `คชาภา EP24`, `พุธทอล์คพุธโทร`), and on
Windows a *redirected* stdout — a pipe, `> log.txt`, a CI capture — inherits
the ANSI code page rather than UTF-8. On this machine `sys.stdout.encoding` is
`cp1252` whenever `isatty()` is false, and cp1252 cannot represent Thai at all.
A Windows *console* stdout is fine, which is why this survived: it only fires
when output is captured, which is exactly when a human is least likely to be
watching. `store.update_cut_plan_status` commits at `store.py:616`, before the
print — confirming the work is durable and only the announcement dies.

Not a new class in this repo: `transcribe/eval/harness.py` hit the identical
wall on Thai cue-legality detail text (2026-07) and grew a private
`_safe_print`. That fix was never lifted out of the harness, so every CutDeck
exporter written since re-met the same defect.

**Treatment:** new `transcribe/console.py` owning `safe_print` — a leaf module
with no project imports, the same shape as `transcribe/timebase.py`, so both
`transcribe.*` and `cutdeck.*` can import it without new coupling. Placed
there rather than in whichever module hit it first, per CLAUDE.md's own rule
for shared concerns. `harness._safe_print` is now an alias to it, so there is
one implementation.

`safe_print` degrades in three steps: normal `print()` → UTF-8 bytes written
straight to the stream's binary buffer → lossy `errors="replace"`. Step 2 is
the deliberate part and differs from the harness original: the message is
almost always **a path the user must then go find in Premiere's import
dialog**, so a `???`-mangled path is printed-but-useless. It knowingly bypasses
the stream's declared encoding, which is defensible only because cp1252 cannot
carry the text under any encoding-faithful alternative — the real choice is
readable or unreadable, not faithful or unfaithful. It deliberately does *not*
call `sys.stdout.reconfigure()`: that mutates process-global state a library
does not own and is unsupported on Windows console streams.

**Blast radius:** 6 files. New `transcribe/console.py`; call sites swapped in
`cutdeck/xml_export.py` (3), `scripts/export_job.py` (2), `cutdeck/preview.py`
(1), `cutdeck/plan.py` (1), `cutdeck/sequence_mixdown.py` (1); harness
de-duplicated. No behavior change on ASCII output or on a UTF-8 stream — those
still take step 1 verbatim. Nothing in the pipeline, contracts, DB, or the
emitted XML/SRT bytes is touched (all file writes were already
`encoding="utf-8"` and were never the problem).

**Strengthened-by:** `tests/test_console_safe_print.py`, 7 tests. Six pin the
degradation steps against a real `cp1252` `TextIOWrapper` — including
`test_earlier_text_output_is_not_reordered_behind_the_raw_write`, which guards
a genuine bug in step 2 (bypassing the text wrapper reorders output unless the
wrapper is flushed first), and `test_plain_print_really_does_crash_on_thai`,
which keeps the others from silently going vacuous if a future Python stops
raising. The seventh runs the real `cutdeck.xml_export` CLI in a subprocess
with a Thai `--out` path and `PYTHONIOENCODING=cp1252` forced, asserting exit
0. Forcing the env var rather than inheriting it means the failing condition
reproduces on any host, not only a cp1252 Windows box. **Verified
non-vacuous:** reverting the one-line fix makes that test fail with the
reported `UnicodeEncodeError`; restoring it passes. Full suite 674 green
(667 + 7).

**Follow-ups:** the two `--dry-run` JSON prints (`plan.py`,
`sequence_mixdown.py`) are covered as a **latent** instance, not a reproduced
one — `dumps()` is `ensure_ascii=False` by design, but every span `reason` in
`cutdeck/rules.py` is currently ASCII vocabulary (`silence`, `filler`,
`min_clip_merge`), so no Thai reaches that stream today. It will the moment a
reason embeds a matched word. Not a new risk introduced here; recorded so the
coverage claim is not read as stronger than it is.

`MAINT MAINT-003: resolved(Fix, proven)`

---

## MAINT-004 | 2026-08-26 | Fix | Thai media paths in ffprobe/ffmpeg stderr destroy the error message

**Symptom:** found while verifying MAINT-003's fix, not reported separately.
Running any ffprobe/ffmpeg-backed path against Thai footage dumped
`Exception in thread Thread-N (_readerthread) ... UnicodeDecodeError: 'charmap'
codec can't decode byte 0x81` to the console, and `cutdeck/preview.py`'s render
failure then reported literally `ffmpeg failed (...): None`.

**Root cause (proven — reproduced with a stand-in child process, both before and
after):** `subprocess.run(..., text=True)` with no `encoding=` decodes the
child's output with the *locale* codec. ffmpeg and ffprobe emit UTF-8; this
machine's locale is cp1252. cp1252 leaves five byte values undefined (0x81,
0x8D, 0x8F, 0x90, 0x9D), and Thai `ก` is `E0 B8 81` — so any path containing one
of the most common letters in Thai kills the stderr reader thread.

**Severity is narrower than it first looks, and the narrowing is the finding.**
stdout is read on its own thread and survives intact, which was verified
directly: a valid Thai-path 29.97 file still probes as `30000/1001`, and
`probe_frame_size` still returns real dimensions. **No frame rate or frame size
was ever silently wrong.** What is lost is `.stderr` — it becomes `None` — so
the failure path reports nothing usable. Below the crash threshold the damage is
quieter still: Thai that happens to avoid those five bytes decodes as mojibake
rather than raising.

**Treatment:** `encoding="utf-8", errors="replace"` on the four shipping
subprocess call sites — `cutdeck/xml_export.probe_frame_size`,
`transcribe/timebase._ffprobe`, `transcribe/timebase.conform_vfr`,
`cutdeck/preview._run`. `tools/engine_sharpener.py` has the same pattern at
three sites and was deliberately **not** changed: it runs `<exe> -version` and
`git -C <repo>` only, never a media path, so it cannot reach the defect.

**Blast radius:** 4 call sites, 4 files, no signature or behavior change on
ASCII paths. Nothing about what gets written to disk changes.

**Strengthened-by:** 4 tests appended to `tests/test_console_safe_print.py`.
`test_locale_decoding_really_does_destroy_thai_stderr` pins the defect itself
(asserting `stdout` survives and `stderr` is None) so the paired fix test cannot
go vacuous; a parametrized `test_ffprobe_callers_pin_their_decoding` reads the
shipping functions' source and fails if either stops pinning its encoding. Full
suite 747 green.

**Follow-ups:** none open. The `errors="replace"` choice means a genuinely
malformed non-UTF-8 byte from ffmpeg degrades to U+FFFD rather than raising —
correct for a diagnostic stream, and the alternative (raising) is the behavior
being removed.

`MAINT MAINT-004: resolved(Fix, proven)`
