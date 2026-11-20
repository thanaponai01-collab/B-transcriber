# SubtitleDesk features

## SubtitleDesk quote workspace
- what: Capture a marked range, review transcript cues, persist quotes and export selected or full-range SRT beside the owning Premiere project.
- cli: `python -m subtitle_desk.server` @ subtitle_desk/server.py :: main
- route: `/` @ subtitle_desk/server.py :: home
- route: `/api/premiere` @ subtitle_desk/server.py
- route: `/api/sessions` @ subtitle_desk/server.py
- route: `/api/sessions/{session_id}` @ subtitle_desk/server.py
- route: `/api/sessions/{session_id}/audio` @ subtitle_desk/server.py
- route: `/api/sessions/{session_id}/quotes` @ subtitle_desk/server.py
- route: `/api/sessions/{session_id}/quotes.srt` @ subtitle_desk/server.py
- route: `/api/sessions/{session_id}/transcript.srt` @ subtitle_desk/server.py
- click: `#refresh` @ subtitle_desk/static/index.html
- click: `#start` @ subtitle_desk/static/index.html
- click: `#add` @ subtitle_desk/static/index.html
- click: `#save` @ subtitle_desk/static/index.html
- click: `#export` @ subtitle_desk/static/index.html
- click: `#export-transcript` @ subtitle_desk/static/index.html
- trace: `api` @ subtitle_desk/static/app.js > `quotes` @ subtitle_desk/server.py > `write_json` @ cutdeck/ai_backend.py
- trace: `export_srt` @ subtitle_desk/server.py > `quotes_srt` @ subtitle_desk/server.py > `export_path` @ subtitle_desk/server.py
- verify: SubtitleDesk quote workspace
- needs: live range capture needs helper :7891, Premiere panel, ffmpeg, source media and ASR model; tests replace helper/extractor and write only under tmp_path.
- effect: session JSON and range WAV under output/subtitle_desk; SRT under owning project/CutDeck/SubtitleDesk.
- status: traced: browser save/export handlers and backend timing/persistence/export read end to end; 13 backend tests passed on 2026-10-11. Browser and real ASR unverified.
