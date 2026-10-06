# ClubFriday quote workspace

A separate local window for selecting Thai advice quotes and preparing up to three lines
for the existing styled Premiere graphic. Uses the running CutDeck helper for transcription.

1. Start the CutDeck helper and open its updated Premiere panel.
2. Run `Start ClubFriday (Hidden).vbs` (or `python -m clubfriday.server`).
3. Open http://127.0.0.1:8010.
4. Mark In/Out on the intended Premiere sequence. Click **Read Premiere**, choose the
   dialogue track (or leave the first active track), then **Transcribe In / Out**.
5. Select consecutive transcript sentences and **Add selected quote**. Click a timestamp
   to listen to the source audio. Correct the exact wording in the quote editor.
6. Choose one to three lines and **Suggest breaks**, then review the layout. Use
   **Copy line 1/2/3** to paste into the separate text layers of your duplicated graphic.
7. **Save quotes** to keep edits. Reopen them through **Saved ranges**.
8. **Export selected quotes as SRT** saves your current edits and exports only the selected
   quotes, in timeline order, preserving up to three lines and exact Thai text. Import the SRT
   into Premiere and put its caption clip at sequence start (00:00), not at the range's In mark:
   its timestamps already include the timeline offset. Select the resulting captions and use
   **Graphics and Titles > Upgrade Caption to Graphic**. Apply your style afterwards; conversion
   does not reproduce the original graphic's separate layers, quotation marks or effects.

For captions covering all speech in the marked range, click **Export full transcript as SRT**
after transcription finishes. Quote selection is unnecessary. Import that SRT into Premiere
and place it at sequence start (00:00); all phrases retain their absolute timeline timestamps.
To cover a whole episode, mark the whole episode
before transcribing. A saved range can be reopened and exported without another transcription.

From a stopped system: run `Start CutDeck (Hidden).vbs` in the project root, open the CutDeck
panel in Premiere, run `Start ClubFriday (Hidden).vbs`, then open http://127.0.0.1:8010.

Both SRT exports save beside the owning `.prproj` file, under `CutDeck/ClubFriday/`,
as `<sequence>-<session id>-transcript.srt` or `-quotes.srt` (UTF-8 with BOM).
The UI shows the saved path; exports no longer create extra browser-download copies.
Older saved ranges resolve their project path from the matching open Premiere project.
New ranges remember the project location, so exports can work while the panel is disconnected.
Repeated exports update the same file. Save the Premiere project before first exporting.
Overlapping quote selections and empty lines must be corrected before export.

Sessions, source-range WAVs, snapshots and quotes live in `output/clubfriday/<id>/`.
Audio extraction preserves the reference track's clip positions, source In/Out and gaps;
it does not render Premiere EQ, transitions, speed changes or gain automation. Use normal-speed
master clips. Transcript timestamps are in the Premiere timeline's absolute seconds.
No speaker identification, quote ranking, graphic creation or Premiere markers are performed.

The backend binds only to 127.0.0.1. `/api/sessions` captures through the fixed read-only
`read_audio_range` Premiere command, extracts only the marked range, then submits its WAV
through the helper's existing `submit_transcribe` protocol. ASR runs in the helper's GPU lane.

Validation:

```
python -m pytest tests/test_clubfriday.py tests/test_cutdeck_driver_commands.py -q
node --test tests/cutdeck_driver.test.cjs tests/clubfriday_quotes.test.cjs
```
