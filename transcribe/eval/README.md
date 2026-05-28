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

## Code-switch boundary labeling rules

A **boundary** is a transition between a Thai-script word and a Latin-script
word (or vice versa) within one utterance.

- A loanword written in **Thai script** (คอมพิวเตอร์) is **Thai** — not a boundary.
- A brand or term written in **Latin script** inside Thai speech **is** a boundary.
- Consecutive Thai words have no boundary between them; consecutive Latin words
  have no boundary between them.

**Boundary error rate** = WER computed only over words within 2 positions of
a boundary. This is the metric that matters; plain WER hides code-switch failure.

## Running the harness

```bash
python -m transcribe.eval.harness --config config.yaml --db transcriber.db
```

Results are printed and written to the `eval_run` table.
