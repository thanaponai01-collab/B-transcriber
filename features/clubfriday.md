# ClubFriday features

## ClubFriday quote workspace
- what: Capture a marked range, review transcript cues, persist quotes and export selected or full-range SRT beside the owning Premiere project.
- cli: `python -m clubfriday.server` @ clubfriday/server.py :: main
- route: `/` @ clubfriday/server.py :: home
- route: `/api/premiere` @ clubfriday/server.py
- route: `/api/sessions` @ clubfriday/server.py
- route: `/api/sessions/{session_id}` @ clubfriday/server.py
- route: `/api/sessions/{session_id}/audio` @ clubfriday/server.py
- route: `/api/sessions/{session_id}/quotes` @ clubfriday/server.py
- route: `/api/sessions/{session_id}/quotes.srt` @ clubfriday/server.py
- route: `/api/sessions/{session_id}/transcript.srt` @ clubfriday/server.py
- click: `#refresh` @ clubfriday/static/index.html
- click: `#start` @ clubfriday/static/index.html
- click: `#add` @ clubfriday/static/index.html
- click: `#save` @ clubfriday/static/index.html
- click: `#export` @ clubfriday/static/index.html
- click: `#export-transcript` @ clubfriday/static/index.html
- trace: `api` @ clubfriday/static/app.js > `quotes` @ clubfriday/server.py > `write_json` @ cutdeck/ai_backend.py
- trace: `export_srt` @ clubfriday/server.py > `quotes_srt` @ clubfriday/server.py > `export_path` @ clubfriday/server.py
- verify: ClubFriday quote workspace
- needs: live range capture needs helper :7891, Premiere panel, ffmpeg, source media and ASR model; tests replace helper/extractor and write only under tmp_path.
- effect: session JSON and range WAV under output/clubfriday; SRT under owning project/CutDeck/ClubFriday.
- status: traced: browser save/export handlers and backend timing/persistence/export read end to end; 13 backend tests passed on 2026-10-11. Browser and real ASR unverified.
