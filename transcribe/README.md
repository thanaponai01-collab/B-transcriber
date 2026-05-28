# Thai-English Code-Switch Transcription System — v1

Batch transcription pipeline for Thai-first, English-seamless code-switching
content. Dual ASR engines → hypothesis alignment → select-only reconciler →
normalization → forced alignment → correction web editor → self-improving
flywheel.

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Install package in editable mode
pip install -e .

# 3. Initialize the database
python -c "from transcribe.db.store import init_db; init_db()"

# 4. Run on an audio file
python -m transcribe.pipeline.run path/to/audio.wav --config transcribe/config.yaml

# 5. Start the web editor
uvicorn transcribe.editor.server:app --host 127.0.0.1 --port 8000
# Open http://127.0.0.1:8000/static/index.html

# 6. Run the eval harness
python -m transcribe.eval.harness --config transcribe/config.yaml
```

## Repository layout

```
transcribe/
  contracts.py         Engine Contract dataclasses — the durable interface
  config.yaml          Engine choices, thresholds, paths
  db/
    schema.sql         Single source of truth for the schema
    store.py           All DB access
  engines/
    base.py            Abstract Engine
    mock.py            MockEngine for testing
    registry.py        Name → adapter (config-driven)
    whisper_thai.py    Engine A — Thai-specialist Whisper
    funasr.py          Engine B — FunASR SenseVoiceSmall
  pipeline/
    ingest.py          Denoise + VAD → speech chunks
    align_hyp.py       Hypothesis-to-hypothesis alignment
    reconcile.py       Select-only reconciler
    normalize.py       Script-boundary spacing + Thai cleanup
    align_force.py     Forced alignment → final timestamps + SRT/VTT
    run.py             Full pipeline orchestrator
  eval/
    harness.py         Runs pipeline over golden set, records metrics
    metrics.py         WER + code-switch boundary error rate
    goldenset/         Frozen audio + ground-truth transcripts
    README.md          Golden set format + boundary labeling rules
  editor/
    server.py          FastAPI backend
    static/            index.html frontend
  flywheel/
    diff.py            Raw ASR vs corrected → correction pairs
    biasindex.py       Corrections → bias terms + regression gate
```

## Engine bootstrapping

Engines are selected by running the eval harness over candidate models.
Results recorded in `eval_run` table. Active choices live in `config.yaml`.

Current engines (verified against 8GB VRAM sequential-load budget):
- **Engine A** (`whisper_thai`): `biodatlab/whisper-th-medium-combined`
- **Engine B** (`funasr`): `FunAudioLLM/SenseVoiceSmall`

To swap an engine: add an adapter in `engines/`, register it, update `config.yaml`,
re-run the harness — it is rejected automatically if WER regresses.

## Adding golden set samples

See `eval/README.md` for the audio+JSON format required by the harness.
