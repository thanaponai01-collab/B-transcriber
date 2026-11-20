<!-- context-paths: subtitle_desk/server.py, subtitle_desk/static/app.js, cutdeck/ai_backend.py, cutdeck/audio_extract.py, uxp/cutdeck/main.js -->
# Architecture

Rough Cut's current native analysis/edit flow and recovery rules are mapped in
[Rough Cut](rough-cut.md), traced and tested offline on 2026-10-11. The historical
native-cut handoff includes superseded XML input and split designs.
The shared helper, analysis, extraction and timing now have independent modules;
FCP7 input/output is retired. New cut plans validate source audio before native edits.

## SubtitleDesk path

SubtitleDesk owns quote sessions and exports; the shared CutDeck helper owns ASR jobs.
This as-is module view was traced on 2026-10-11.

```mermaid
flowchart LR
  browser["subtitle_desk/static/app.js"] --> server["subtitle_desk/server.py"]
  server --> backend["cutdeck/ai_backend.py"]
  server --> audio["cutdeck/audio_extract.py"]
  server --> sessions["output/subtitle_desk session files"]
  server --> srt["Project CutDeck/SubtitleDesk SRT"]
  backend --> helper["cutdeck/helper.py websocket helper"]
```

| Arrow | Source evidence |
|---|---|
| Browser -> server | subtitle_desk/static/app.js:7, 135, 143, 153: fetch/save/export |
| Server -> backend | subtitle_desk/server.py:139, 230: submit job and poll result |
| Server -> audio | subtitle_desk/server.py:74: extract_mixdown with zero padding |
| Server -> sessions | subtitle_desk/server.py:111: atomic write_json persistence |
| Server -> SRT | subtitle_desk/server.py:289, 306: BOM/CRLF writes |
| Backend -> helper | cutdeck/ai_backend.py:54: localhost websocket exchange |

## Boundaries and placement
- subtitle_desk/: API/UI, session lifecycle, timeline offset, quote rules and exports.
- cutdeck/: shared sequence model, source-audio extraction and helper client/jobs.
- uxp/cutdeck/: Premiere bindings/imports; Adobe API rules remain in CLAUDE.md.
- tests/test_subtitle_desk.py uses fake helper/extractor and temp project/session files.
- Browser assets belong in subtitle_desk/static; tests in tests; shared helper behavior
  in cutdeck. Generated audio/session/evidence belongs under ignored output/.
- Source extraction uses ffmpeg, numpy and soundfile; it omits Premiere effects,
  transitions and gain automation (cutdeck/audio_extract.py module contract).

## Coverage gaps
- Helper -> ASR engines -> SQLite is outside this traced flow; consult SYSTEM_SPEC.md
  and features/transcribe.md, then read the actual chain before changing it.
- Editor :8000, CLI jobs, evaluation, MCP and other panel workflows are inventoried
  in FEATURES.md but not fully traced here. No hosted CI directory was present.
- Mermaid syntax inspected; renderer not run. Whole-system wiring remains partial.
