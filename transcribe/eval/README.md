# Eval Harness

## Golden set format

Place files under `goldenset/`. Each sample is a pair:
- `<id>.wav` (or `.mp3`, `.flac`) — the audio file
- `<id>.json` — ground-truth transcript in this format:

```json
{
  "tokens": [
    {"text": "สวัสดี", "start_ms": 0,   "end_ms": 500,  "script": "thai"},
    {"text": "ครับ",   "start_ms": 500, "end_ms": 900,  "script": "thai"},
    {"text": "Hello",  "start_ms": 1000,"end_ms": 1400, "script": "latin"}
  ]
}
```

`script` must be one of: `thai`, `latin`, `other`, `mixed`.

`start_ms` is required on gold tokens — the switch-point metric is temporal.
`end_ms` should be present too: a switch *inside* a `mixed` cue gets its
timestamp interpolated across `[start_ms, end_ms]` (without `end_ms` it
degrades to the cue's start time).

## Metrics

Each signal is measured on the unit that is actually well-defined (see
`../../STYLE_GUIDE.md` §1 and `metrics.py`):

| Metric | Unit | Notes |
| --- | --- | --- |
| **`cer_thai`** | character | **Primary Thai signal.** Character error rate over the concatenated Thai-script stream. Tokenization-free, so it does not depend on newmm vs attacut — your gold set stops being a moving target. |
| **`wer_latin`** | word | **Primary Latin signal.** Word error rate over Latin/digit runs, **case-insensitive**. |
| **`boundary_error_rate`** | timestamp | **Code-switch signal.** `1 − F1` of reference Thai↔Latin switch *timestamps* matched to hypothesis switches within `boundary_tol_ms` (default 300 ms). A positional metric would reward right-words/wrong-place; this does not. |
| **`wer`** | word | Coarse, tokenizer-sensitive sanity number. **Not** a gate. |

The regression gate (default tolerance 2%) trips if **any** of `cer_thai`,
`wer_latin`, or `boundary_error_rate` worsens beyond tolerance vs the last passing
production run **of the same `METRICS_VERSION`** (`eval_run.metrics_version`).
Scores computed under different metric definitions are incomparable, so the first
run after a metric-definition change establishes a fresh baseline rather than
being gated against numbers an older rule produced.

## Code-switch boundary labeling rules

A **switch point** is a transition between a Thai-script word and a Latin-script
word (or vice versa) within one utterance.

Since metrics **v2**, switch points are derived **character-by-character inside
every token** — tokens are phrase cues, so real switches usually happen *inside*
a `mixed` cue, which the v1 token-script rule could never see (BER sat at a
structural 0.0 with `switches=0` no matter how much code-switch gold existed).
An intra-cue switch's timestamp is linearly interpolated across the cue's
`[start_ms, end_ms]` span by character offset — an approximation (uniform char
rate), but the same approximation on both sides of the comparison. Digits and
punctuation are script-neutral: `หน้า 2 ครับ` contains no switch. The corpus
number is a **micro-F1** (matched/ref/hyp counts summed over all samples, one F1
at the end), so switches hallucinated on monolingual clips are penalized — a
ref-weighted mean would have given them weight zero.

- A loanword written in **Thai script** (คอมพิวเตอร์) is **Thai** — not a switch.
- A brand or term written in **Latin script** inside Thai speech **is** a switch.
- The labeling test is *how the word was pronounced*, not what it means
  (STYLE_GUIDE.md §4).

## Normalization is applied to BOTH sides

The harness passes `config` to `compute_metrics`, which runs the same
`normalize()` over the gold set and the hypothesis before scoring. A policy
change (e.g. Thai-digit mapping) therefore can never desync gold from hyp.

## Running the harness

```bash
python -m transcribe.eval.harness --config config.yaml --db transcriber.db
```

Results are printed and written to the `eval_run` table
(`cer_thai`, `wer_latin`, `boundary_error_rate`, `wer`).
