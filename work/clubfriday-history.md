# ClubFriday helper

Separate local quote editor; existing helper owns Thai ASR. Exact words, editable line breaks,
at most three lines, timeline timestamps, persistent quote selections. No graphics automation.

| Slice / proof command and expected result | Status | Commit |
| --- | --- | --- |
| Live SRT import and placement: `Project.importFiles` imported `Edditing-a2ccc4ee-transcript.srt` into `CutDeck/ClubFriday`. UI drag + New caption track / Source timecode created C1 in original Edditing. Readback: 1 track, 203 items, first 9.4094 s, last 426.1590667 s; In/Out remain 9.4094/426.2258. One 1 ms ASR cue at 75.889 s was omitted by Premiere. Thai subtitle visible at 15 s; `Project.save()` returned true. API insert/overwrite on test copy were no-ops; automatic timeline placement is not implemented. | proven 2026-10-06 | uncommitted |
| Project-folder SRT: Python tests (9 passed) verify both exports exist in sibling `CutDeck/ClubFriday`; driver tests and API checker pass. Live project path read from Premiere, old range exported as `G:/Me/Works/20261006 - CFD 96/4. PROJECTS/1. PREMIERE PRO/CutDeck/ClubFriday/Edditing-a2ccc4ee-transcript.srt` (24,285 bytes); browser shows saved path. | proven 2026-10-06 | uncommitted |
| Full-range SRT: `python -m pytest tests/test_clubfriday.py tests/test_cutdeck_driver_commands.py -q` (9 passed) includes every cue with absolute timing even with no selected quotes; JS syntax check passes. Live 00:09.409–07:06.226 helper job `c018a692517f463099685973d1cfc333`: 204 cues exported from browser; file verified against all saved cue texts and range bounds. Main evidence: `output/clubfriday/a2ccc4ee0ca44155a3dd0cb93e7b57c4/full-transcript.srt`, `output/clubfriday-full-srt-proof.png`. Native import attempt interrupted by user input; no timeline insertion claimed. | proven 2026-10-06 | uncommitted |
| SRT export: `python -m pytest tests/test_clubfriday.py tests/test_cutdeck_driver_commands.py -q` (9 passed) proves exact Thai text, layout, timing, order and empty/overlapping refusal; `node --check clubfriday/static/app.js` passes. Live button exported current edited quote at 43:33.013–43:38.533; file text equals saved lines with UTF-8 BOM. Main evidence: `output/clubfriday/d6d2ca33fc7b45ba945d68adc5005831/selected-quotes.srt`, `output/clubfriday-srt-proof.png`. Premiere import/conversion not yet tested. | proven 2026-10-06 | uncommitted |
| `python -m pytest tests/test_clubfriday.py tests/test_cutdeck_driver_commands.py -q` (7 passed), `node --test tests/cutdeck_driver.test.cjs tests/clubfriday_quotes.test.cjs` (17 passed), `node tools/adobe/check-api.mjs` (39 files OK): range capture, offsets, persisted quotes, Thai breaks and error cases | proven 2026-10-06 | uncommitted |
| Live Premiere Edditing 39:08.613–43:56.467: helper job `965a35b46ad342f69367cec7468508cc` produced 114 cues; saved 3-line quote, clipboard equals line 3, timestamp audio plays, quotes survive server restart. Evidence: main `output/clubfriday/d6d2ca33fc7b45ba945d68adc5005831/session.json` and `output/clubfriday-proof.png` | proven 2026-10-06 | uncommitted |

Installed the separate window and launchers into `E:/Me/5.Claude/Transcriber_v2`.
Its server runs on 127.0.0.1:8010; the existing helper and panel provide range capture and ASR.

Deferred: styled graphic insertion | current UXP text API rejects writes | due when a real text-write probe passes.
