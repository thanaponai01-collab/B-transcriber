# Commands and runtime

Working directory for all rows: E:/Me/5.Claude/Transcriber_v2 (Git root).
Observed: Python 3.13.4, Node v22.16.0. setup.py requires Python >=3.11;
CLAUDE.md and SYSTEM_SPEC.md specify Python 3.11.9 for the GPU environment.
Root .venv is absent from the initial directory inventory; dependency lockfile
is not supplied by requirements.txt (minimum versions only).

| Command | Prerequisites / source | This foundation pass |
|---|---|---|
| `python -m pytest tests/test_clubfriday.py -q -p no:cacheprovider` | pytest, FastAPI/TestClient and backend imports; clubfriday/README.md | 13 passed |
| `node --test tests/clubfriday_quotes.test.cjs tests/clubfriday_panel.test.cjs` | Node; existing panel/quote tests | 3 panel checks passed; quote module file loaded without separate reported cases |
| `python -m clubfriday.server --port 8010` | FastAPI/uvicorn; loopback quote UI; clubfriday/server.py | not launched |
| `python -m cutdeck.helper` | websockets, ffmpeg, ASR model/GPU for jobs; CLAUDE.md | not launched |
| `python -m uvicorn transcribe.editor.server:app --host 127.0.0.1 --port 8000` | finished jobs/database, FastAPI; CLAUDE.md | not launched |
| `python -m transcribe.pipeline.run FILE --config transcribe/config.yaml` | source media, ffmpeg, CT2 model, GPU runtime; CLAUDE.md | not run |
| `python -m transcribe.eval.harness --config transcribe/config.yaml` | gold media, model/GPU; CLAUDE.md | not run |
| `python -m pip install -r requirements.txt` then `python -m pip install -e .` | dedicated Python 3.11.9 environment; CLAUDE.md | not run; current selected tests import successfully |

Start ClubFriday.cmd prefers root .venv when present, otherwise PATH python.
Launchers may open local services; they were read without launching them.
No database initialization, deployment, external writes, live project edits or CI run.
Verification helpers are installed plugin scripts, not project runtime dependencies.
