# HANDOFF — CutDeck: word-level cutting + rough-cut restructure

**For:** Claude Code, working in `Transcriber_v2`.
**Hardware:** RTX 3070, 8 GB VRAM. Python 3.11.9 venv. Windows host.
**Prime directive:** a false cut is much worse than a missed one. Keep-precision is the metric that must stay near 1.0; cut-recall is negotiable.
**Discipline:** every phase ends with the full suite green (**224 collected** at time of writing, 2026-08-03) plus the new acceptance tests listed per task. Read `CLAUDE.md`, `IMPLEMENT_CUTDECK.md` §B, and `TODO_LEDGER.md` before touching anything. Update `TODO_LEDGER.md` as phases complete.

---

## Context: what this handoff is

CutDeck Phases 0–2 are built (`cutdeck/{contracts,segment,rules,plan,xml_export}.py`). Two things are true at once: the rough cut works, and **every word-level feature in the spec is structurally unbuildable today**. This handoff closes that, then fixes the design flaw that has already produced three rounds of real-world bugs in the min-clip merge.

Goal for the user: remove filler words, stuttered/duplicated words, and repeated takes — and make the dead-air rough cut better in more situations.

### The three findings this plan is built on

**F1 · The filler rule is dead code.**
`rules.filler_cuts()` (`cutdeck/rules.py:120-128`) matches `t.text.strip()` against the lexicon, but since token granularity 5.4 `store.get_tokens()` returns **phrase cues**, not words. Real row from job 29:

```
token idx 4   35740–39310   'หนึ่งนะเพราะว่าหาย ไป เดือน นึง นะ เพราะ ว่า'
```

No token will ever `== "เอ่อ"`. Setting `fillers_enabled: true` today cuts exactly nothing. The bug is masked because the config default is `false`.

**F2 · Raw word timings exist but are sub-word fragments.**
`engine_result.raw_words_json` holds 10,087 entries for job 29 — but they are character pieces, not words:

```
{'text': 'เท', 1520–2120}  {'text': 'ส', 2120–2420}  {'text': 'ต', 4990–5210}  {'text': '์', 5210–5210}
```

So `get_tokens()` cannot simply be swapped for raw words. The char-timeline + `pythainlp.word_tokenize` regrouping that turns those pieces into real words **already exists** — buried inside `transcribe/engines/faster_whisper.py:_group_words_into_cues` (`:250-279`), engine-specific and unreachable from `cutdeck/`.

**F3 · `rules.py` never looks at segments.**
`build_cut_spans()` consumes silences and tokens only. `plan._attach_segments()` (`plan.py:64`) is decorative bookkeeping applied *after* the spans are already decided. The spec's core rule — *"semantic layers (2–3) decide what to cut; Layer 0 decides where the blade lands"* (`IMPLEMENT_CUTDECK.md` §B.1) — is inverted in the implementation: interval arithmetic decides *what*, and nothing decides *where* beyond fixed padding. This is the root cause of the min-clip merge complexity (Phase 4).

---

## PHASE 1 — `cutdeck/words.py`, the word timeline (enabling layer)

**STATUS: DONE and wired (2026-08-03).** `cutdeck/words.py` built with `Word`,
`words_from_pieces`, `words_for_job`, plus a `timed_tokens()` helper factoring
out steps 1-3 (char timeline → pythainlp word boundaries → span mapping).
`transcribe/engines/faster_whisper.py:_group_words_into_cues` now calls
`cutdeck.words.timed_tokens` for those steps instead of duplicating them —
one implementation of Thai word-timeline reconstruction, as specified.

Acceptance tests: `tests/test_cutdeck_words.py` (8 new, all green). Full
suite: 231 passed / 1 pre-existing failure (`test_sentence_boundary_offsets_finds_the_split`,
`ModuleNotFoundError: pycrfsuite` — confirmed present before this change too
via `git stash`; this shell runs Python 3.13, not the documented 3.11.9 venv,
and `pycrfsuite` isn't installed here. Unrelated to this work — not fixed).

**One correction to this handoff's own acceptance text, found while
building:** "`words_from_pieces` on the literal job-29 fragment list
`[('เท',1520,2120),('ส',2120,2420)]` yields one `Word('เทส', 1520, 2420)`"
does not hold. `pythainlp.word_tokenize` splits `เทส` (a transliteration of
"test", not a dictionary word) right back into `['เท', 'ส']` even when
presented as one contiguous run — confirmed directly:
`word_tokenize('เทส', keep_whitespace=True) == ['เท', 'ส']`. So
`words_from_pieces` correctly returns **two** `Word`s for that input, not
one. The `_group_words_into_cues` test *does* see one merged unit — because
cue-grouping (steps 4+) merges adjacent words into a phrase cue regardless of
word boundaries — which is presumably what produced the one-`Word` intuition
in the original spec. Every other acceptance criterion (monotonic/non-overlapping
spans inside source-piece bounds, Latin/Thai separation, `words_for_job`
degrading to `[]` on NULL/missing) holds as written and is tested. Phase 2+
should not assume `words_from_pieces` merges non-lexicon transliterations
into single tokens.

Nothing else in this handoff is buildable without it. Do this first.

**Build:** `cutdeck/words.py`

```python
@dataclass(frozen=True)
class Word:
    text: str
    start_ms: int
    end_ms: int
    confidence: Optional[float]

def words_from_pieces(pieces: list[tuple[str, int, int, float | None]]) -> list[Word]
def words_for_job(conn, job_id: int, engine_slot: str = "a") -> list[Word]
```

- `words_from_pieces` is the lift of the char-timeline + `word_tokenize` logic from `_group_words_into_cues` steps 1–3 (`faster_whisper.py:250-279`): build a per-character timeline where each char inherits its source piece's span and confidence, join to full text, segment with `pythainlp.word_tokenize(keep_whitespace=True)`, map each token back to `(start, end, mean confidence)` via the char timeline.
- `words_for_job` reads `engine_result.raw_words_json` via `store.get_engine_result` and feeds it through. Returns `[]` when the engine reported no raw words (chunk engines — see `run.py:146-156`) so every caller degrades to the current behaviour rather than crashing.
- Pure post-processing on `(text, start, end, conf)` tuples — **no model-specific logic**, so it stays behind the engine contract and works for any engine that ever populates `raw_words_json`.

**Then refactor `_group_words_into_cues` to call it** for steps 1–3, keeping its own cue-grouping (steps 4+) untouched. One implementation of Thai word-timeline reconstruction, not two.

**Acceptance:**
- `words_from_pieces` on the literal job-29 fragment list `[('เท',1520,2120),('ส',2120,2420)]` yields one `Word('เทส', 1520, 2420)`.
- A Latin run and a Thai run in one piece list come back with Latin words intact and spaces preserved.
- Word spans are monotonic and non-overlapping; every word's span is inside the union of its source pieces' spans.
- `words_for_job` on a job with `raw_words_json = NULL` returns `[]`, no exception.
- **Regression:** existing cue tests (`tests/test_cue_conform.py`, `tests/test_cue_space_break.py`, `test_cue_target_chars_config.py`) still green after the `_group_words_into_cues` refactor — byte-identical cue output on the same input is the bar.

---

## PHASE 2 — word-level cuts: fillers, stutters, and the blade contract

**STATUS: DONE and wired (2026-08-04).** All three mechanisms built and
config-gated off by default, per config block below.

- `cutdeck/rules.py`: `filler_cuts(words, silences, cfg, job_id=None)` now
  takes `list[Word]` (Phase 1 timeline), not phrase-cue tokens. Calling
  `build_cut_spans(tokens, ...)` without `words=` (the pre-Phase-2 call shape)
  cuts nothing and logs a WARNING naming the job, instead of silently doing
  nothing (that silence is what hid F1 for two months). New
  `repeat_cuts(words, segments, cfg)` — deterministic n-gram (1..
  `repeat_max_ngram`, default 4) stutter/duplicate-word detector, never
  crosses a segment boundary, gated on `repeat_max_gap_ms` (default 600),
  guards single-character units and `ๆ`-suffixed reduplication. Both wired
  into `build_cut_spans` (grew `words`/`segments`/`job_id` params) and
  `plan.propose_for_job` (now calls `words_for_job` + `segment_tokens` and
  passes both through).
- `cutdeck/contracts.py`: `CutSpan.blade` (`BLADE_VAD` | `BLADE_WORD`),
  default `BLADE_VAD`. Filler/repeat cuts emit `BLADE_WORD`; silence cuts stay
  `BLADE_VAD`. Propagated through `_merge_overlaps`/`_assemble`/`_coalesce`
  (a merge is word-blade if either half was). Serialized in
  `plan.to_dict`/`from_dict` (old JSON without the key defaults to
  `BLADE_VAD`). New `CutConfig` fields: `repeats_enabled` (false),
  `repeat_max_ngram` (4), `repeat_max_gap_ms` (600), `word_blade_crossfade_ms`
  (20) — all read via `from_yaml`.
- `cutdeck/xml_export.py`: `to_xml` takes `word_blade_crossfade_ms` (default
  20ms, read from config in the CLI) and emits an FCP7 `<transitionitem>`
  audio crossfade (`Cross Fade (0dB)`) on both audio tracks at every junction
  between two exported keep-clips whose omitted cut had `blade=BLADE_WORD`;
  VAD-blade junctions stay hard cuts, and the video track never gets a
  transition. **Caveat, stated in the module docstring on the helper:** this
  is an approximation — no source overlap/trim is applied (the real Premiere
  XML round-trip is still unverified, see Phase 3 below), so it's a
  plausible, testable crossfade marker for review-UI attention, not a
  Premiere-verified audio crossfade. Revisit once Phase 3's real import
  acceptance passes.

Acceptance tests: `tests/test_cutdeck_phase2.py` (18 new — filler-on-words,
old-path-warns, repeat n-gram/gap/segment-boundary/mai-yamok guards,
determinism, blade round-trip incl. old-JSON default, XML crossfade
presence/absence). `tests/test_cutdeck_phase1.py`'s old token-driven filler
tests were updated to assert the new "old path" contract (zero cuts + warning)
rather than removed, since that behavior is itself now an acceptance
criterion. Full suite: 248 collected, 247 passed / 1 pre-existing failure
(`test_sentence_boundary_offsets_finds_the_split`, `pycrfsuite` missing on
this Python 3.13 shell — present before this change too, unrelated, see
Phase 1 status above).

Three separate mechanisms. They are not one feature and must not share a code path.

### 2.1 Revive `filler_cuts()` on the word timeline

**Change:** `cutdeck/rules.py` — `filler_cuts(words, silences, cfg)` takes `list[Word]` instead of phrase-cue tokens. Matching logic is unchanged (always-safe subset cuts unconditionally; contextual entries only when isolated by ≥ `contextual_isolation_ms` of silence on both sides). `build_cut_spans()` grows a `words` parameter; `plan.propose_for_job()` supplies `words_for_job(conn, job_id)`.

When `words` is empty (no raw words for the job), `filler_cuts` returns `[]` and logs a WARNING naming the job — silently doing nothing is what hid F1 for two months.

**Acceptance:** a fixture word timeline containing `เอ่อ` mid-phrase produces exactly one cut spanning that word's timings and no others; the same phrase presented as a single phrase-cue token (the old path) produces zero cuts *and* logs the warning; `fillers_enabled: false` still returns `[]` without touching the timeline.

### 2.2 New: `rules.repeat_cuts()` — stutter and duplicated words

The user's "duplicate words" case: `ไป ไป ไป`, `เดือน นึง เดือน นึง`. **Deterministic, no LLM.**

**Build:** `cutdeck/rules.py`

```python
def repeat_cuts(words: list[Word], segments: list[Segment], cfg: CutConfig) -> list[_RawCut]
```

- Within a single segment (never across a segment boundary — a repeat across an utterance break is a *retake*, Phase 6's job), scan for an n-gram of length `n = 1..cfg.repeat_max_ngram` (default 4) immediately followed by an identical n-gram.
- Keep the **last** occurrence, cut the earlier ones. Matches `keep_last_take: true` — the last attempt is the clean one.
- Gate on `cfg.repeat_max_gap_ms` (default 600): if the repeats are separated by more than that, it is deliberate emphasis or a real retake, not a stutter. Leave it.
- Guard against legitimate reduplication: never cut when the repeated unit is followed by `ๆ` (mai yamok — `_may_break_at_space` in `faster_whisper.py:302` has the same guard), and never when the unit is a single character.
- Config-gated: `cut.repeats_enabled`, default `false` until an eval baseline exists (same discipline as fillers).

**Acceptance:** `ไป ไป ไป` yields two cuts covering the first two occurrences and keeps the third; `เด็ก ๆ` yields zero cuts; a repeat spanning a segment boundary yields zero cuts; repeats separated by 900 ms yield zero cuts; determinism — identical input yields byte-identical output.

### 2.3 The blade contract — where a mid-speech cut lands

**This is the risky part of the whole handoff and must be explicit in the contract, not implicit.**

Silence cuts snap to VAD boundaries. A stutter has **no silence between the repeats**, so Layer 0 has nothing to offer and a hard splice mid-speech is audible.

**Change:** `cutdeck/contracts.py` — add to `CutSpan`:

```python
blade: str = BLADE_VAD    # BLADE_VAD | BLADE_WORD
```

- `BLADE_VAD` — the current behaviour, boundary came from a VAD silence edge. Trustworthy.
- `BLADE_WORD` — boundary came from a word timestamp inside continuous speech. Filler and repeat cuts emit this.
- Word-blade edges are nudged to the local energy minimum within the inter-word gap (±40 ms search window) rather than taken raw from the timestamp.
- `xml_export.py` emits a short audio crossfade (default `cut.word_blade_crossfade_ms: 20`) on word-blade edges only. VAD-blade edges stay hard cuts, exactly as today.
- Serialize `blade` in `plan.to_dict`/`from_dict`. The review UI (Phase 6 of the original spec) colours word-blades differently so human attention goes to the risky cuts; the flywheel learns padding per blade type, because word-blades and VAD-blades have genuinely different correct padding.

**Acceptance:** a plan containing both blade kinds round-trips through `dumps`/`loads` unchanged; an old plan JSON without the `blade` key loads with every span defaulting to `BLADE_VAD`; XML export emits a crossfade on word-blade edges and none on VAD-blade edges; `assert_contiguous_exhaustive` unaffected.

---

## PHASE 3 — `cutdeck/preview.py`, the feedback loop

**STATUS: DONE and wired (2026-08-04).** `cutdeck/preview.py` built: `keep_ranges_ms(plan)`
(pure — extracts `(start_ms, end_ms)` for every KEEP span in timeline order) and
`render_preview(plan, media_path, out_path, reencode=False, ffmpeg_bin="ffmpeg")`, which
extracts each keep span with `ffmpeg -ss/-to -c copy` into a temp dir, then joins them via
the concat demuxer (`-f concat -safe 0 -c copy`) — a single `shutil.copy` short-circuit
when there's only one keep span. `--reencode` swaps `-c copy` for `libx264`/`aac` on the
per-segment extraction, trading speed for frame-accurate cuts.

- CLI: `python -m cutdeck.preview --job-id N [--plan-id N] --out preview.mp4 [--reencode] [--ffmpeg-bin ...]`
  — mirrors `xml_export.py`'s `--plan-id`/`--job-id` store-lookup pattern exactly (same
  `get_cut_plans_for_job` → `load_plan` → `get_job` → `get_media` chain).
- Stream copy is keyframe-imprecise. **Labelled approximate in both places**, as specified:
  the CLI appends `_approx` to the output filename by default (only `--reencode` keeps the
  name clean) and the final print line says `APPROXIMATE (stream-copy, keyframe-imprecise)`
  plus a pointer to `xml_export.py` + Premiere for the real frame-accuracy check.
  `FfmpegNotFoundError` is checked via `shutil.which` **before** any subprocess call, so a
  missing binary is a one-line `SystemExit` message, never a traceback.

Acceptance tests: `tests/test_cutdeck_preview.py` (7 new, all green) — run against the
**real ffmpeg on PATH** (`/c/ffmpeg/ffmpeg-8.1.1-essentials_build`, confirmed present in
this shell) rather than mocked, using a synthetic `lavfi testsrc`+`sine` clip with keyframes
forced every 0.5 s so the GOP tolerance in the acceptance criteria is a real measurement, not
an assumption:
- `keep_ranges_ms` extracts only KEEP spans, in order.
- All-KEEP plan reproduces source duration within one GOP (500 ms here).
- A plan with a 2 s cut renders a file shorter by 2 s ± one GOP.
- Missing/bogus `--ffmpeg-bin` raises `FfmpegNotFoundError` with a clear message, no traceback.
- No-keep-spans plan raises `ValueError`.
- Single-keep-span plan takes the `shutil.copy` path (no concat) and produces a valid file.
- `--reencode` lands the same 2 s cut within 100 ms (frame-accurate vs the GOP-bound
  stream-copy case), proving the two code paths are genuinely different, not just
  differently labelled.

Full suite: 255 collected, 254 passed / 1 pre-existing failure (`test_sentence_boundary_offsets_finds_the_split`,
`pycrfsuite` missing on this Python 3.13 shell — present before this change too, unrelated,
see Phase 1 status above).

**Also still open, unchanged by this handoff:** the real Premiere import acceptance. Flag it
to the user again — Phases 4–6 of the original spec (flywheel, eval gate) stay blocked until
it passes. Phase 3 makes the *rough cut* watchable; it does nothing for the XML round-trip.

---

## PHASE 4 — segment-first rough cut (the structural fix)

**The min-clip merge is fighting the silence pass, and its complexity is the proof.** `apply_min_clip_merge` (`rules.py:215-313`) is ~100 lines carrying `dissolved_ms` accumulators, `_STANDALONE` island protection, `_far_is_protected`, and a drop-instead-of-merge fallback — accreted across three rounds of real-world bug fixes (commit b820856 plus the 2026-08-03 comments). That is the signature of a repair pass cleaning up after a pass that lacked the information to decide correctly.

The live config makes it worse: `min_silence_ms: 250` with `min_clip_ms: 1200` means the silence pass shatters the timeline into fragments and the merge pass must then reassemble it, deciding case-by-case how much dead air to re-admit.

**Change:** invert the pass order in `rules.build_cut_spans`. Build keeps from **segments** (Layer 2), not from interval-subtraction leftovers:

1. Group words into utterances — `segment.segment_tokens`, already built, currently unused by `rules.py` (F3).
2. Decide keep/cut **per utterance** (rules now; `takes.py` in Phase 6). This is the `Label` contract type that has sat unused since Phase 1.
3. Trim the space *between* kept utterances to padding. Space *inside* a kept utterance is pace — leave it, except for explicit word-level cuts from Phase 2.

A kept clip is then an utterance by construction. A sub-`min_clip_ms` keep is a genuinely short utterance — keep it as-is. No merging, no dissolve caps, no protected islands: **most of those 100 lines delete.** This also makes §B.1's layering true instead of aspirational.

**Risk and mitigation:** this changes the output of a working, tested pass. Do it *after* Phase 3 so the change can be watched, not just diffed. Keep `apply_min_clip_merge` and its tests intact behind `cut.rough_cut_mode: interval | segment` (default `interval`) until the segment path is proven on real footage; delete the old path in a follow-up commit, not this one.

**Acceptance:** every existing `tests/test_cutdeck_phase1.py` invariant still holds under both modes (contiguous, exhaustive, no keep clip overlaps a cut, determinism); under `segment` mode, the three bug fixtures that drove the `dissolved_ms`/`_STANDALONE` machinery produce correct plans **without** any dissolve-cap logic being consulted; a plan built in `segment` mode never contains a KEEP span that is not backed by at least one segment.

---

## PHASE 5 — two cheap wins on dead air

Both use data already in the DB. No new dependencies.

### 5.1 Token-less speech spans

VAD marks breaths, lip smacks, coughs and camera noise as **speech**, so they survive as kept pace forever. This is the largest remaining gap between "silence removal" and a real rough cut.

**Change:** `cutdeck/rules.py` — a kept span with no token midpoint inside it and duration > `cut.min_nonspeech_ms` (default 400) is dead air VAD misclassified. Cut it. `_has_token` already exists (`rules.py:203`) and does exactly the midpoint test needed.

Guard: only applies to spans covered by a VAD **speech** span (otherwise it is already handled by the silence rule), and never to a span carrying a word from the Phase 1 timeline.

**Acceptance:** a fixture with a 700 ms speech-classified span containing no tokens is cut; the same span containing one token is kept; a 200 ms token-less span is kept (below threshold).

### 5.2 Adaptive silence threshold

A fixed 250 ms floor ignores that pacing varies within and between takes.

**Change:** compute the distribution of inter-speech gaps for the job; cut gaps above `cut.silence_percentile` (default 60), **floored at `min_silence_ms`** so the threshold can only ever get more conservative, never more aggressive, than today's config. Config-gated `cut.adaptive_silence: false` by default.

**Acceptance:** on a job whose gaps are uniformly 300 ms, adaptive mode cuts no more than fixed mode; on a job with a bimodal gap distribution, the threshold lands between the two modes; with the flag off, output is byte-identical to today.

---

## PHASE 6 — `cutdeck/takes.py`: repeated takes and restarted sentences

The only module in this handoff needing an LLM, and deliberately last. Spec is already written — `IMPLEMENT_CUTDECK.md` §B.3 `takes.py` — and **is not superseded by this handoff**; build it as written. Notes that changed since it was authored:

- The Jaccard>0.55 prefilter operates on **segments**, which after Phase 4 are the real keep/cut atoms — the classifier now slots into a pass that already thinks in segments rather than bolting onto interval arithmetic.
- Retake markers (`cut.retake_markers`, already in `config.yaml:189`) are a **deterministic pre-pass in `rules.py`**. The LLM only resolves *how far back* the retake reaches. Do not let it decide *whether* a marker is a marker.
- The select-only discipline is non-negotiable: ids must be a subset of input ids, every id covered, assertion-enforced, no timecodes in the decision space, never rewrites text. Mirror `pipeline/reconcile.py`.
- **Heed the LLM reconciler result** (`CLAUDE.md`, 2026-07-16): `qwen2.5:3b-instruct` was not good enough to beat a degenerate heuristic on the transcriber's tiebreak task, and positional bias had to be fixed before that was even measurable. Randomize candidate order in the prompt from day one, and gate activation on the eval harness — not on it looking sensible in a spot check.

**Acceptance:** as specified in §B.3 — hallucinated-id assertion raises with a mock LLM; duplicate-take fixture keeps exactly the last take; eval gate still green.

---

## Ordering rationale

| Phase | Why here |
|---|---|
| 1 · `words.py` | Hard prerequisite. Nothing word-level exists without it. |
| 2 · fillers + stutters + blade | The user's actual ask. Small once Phase 1 lands. |
| 3 · `preview.py` | Makes Phases 4–5 verifiable instead of blind. |
| 4 · segment-first | Structural fix; deletes complexity. Needs Phase 3 to be watchable. |
| 5 · dead-air wins | Cheap, additive, easier to judge once 4 is stable. |
| 6 · `takes.py` | Only LLM work; benefits from Phase 4's segment atoms. |

Phases 1–2 are the self-contained slice that delivers word and duplicate removal. They are testable against job 29's existing `raw_words_json` with **no pipeline re-run**.

## Config additions (one block, all default-off)

```yaml
cut:
  repeats_enabled: false        # 2.2 — stutter/duplicate-word removal
  repeat_max_ngram: 4
  repeat_max_gap_ms: 600
  word_blade_crossfade_ms: 20   # 2.3 — mid-speech splice softening
  rough_cut_mode: interval      # 4 — interval | segment
  min_nonspeech_ms: 400         # 5.1 — token-less speech span
  adaptive_silence: false       # 5.2
  silence_percentile: 60
```

Every new behaviour ships off. Turn each on only after the eval harness (`IMPLEMENT_CUTDECK.md` §B.3 `eval/`) has a baseline for it — keep-precision is the gate.
