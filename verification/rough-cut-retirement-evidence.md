# Rough Cut retirement evidence - 2026-10-11

Local source work is complete; real Premiere/GPU confirmation remains pending.
Contract: rough-cut-retirement.md. Scoped recipe: rough-cut-retirement.recipe.md.

Code baseline: `afa8dc76dd42446cf541698b9894f8be35c089db`, pushed to origin/master
on 2026-10-11. The checks below ran on the working source before that commit;
committing/pushing did not rerun them. `git ls-remote origin refs/heads/master`
matched the full local HEAD after push, and `git status --short` was empty.

## Changes and preserved behavior
- Shared services now live in cutdeck/helper.py, rough_cut.py, audio_extract.py and
  sequence_timing.py. Launchers, transcription/MCP clients and ClubFriday use them.
- Production FCP7 parsing/writing and the XML-file MCP tool are retired. Old XML
  prepared/ready jobs fail clearly. xml_bridge remains a compatibility launcher;
  xml_recut and cut_xml.ps1 give replacement instructions without processing files.
- JSON analysis retains range offsets, reference-track selection, duration guards,
  shared ASR ingest, speech protection and cut rules. XML samples are test fixtures only.
- Native apply compares new cuts' source audio snapshots before cloning, on both
  panel and agent paths. Changed sources clear the panel's stale result; wrong
  sequence identity stays resumable. Enumeration order is ignored.
- Fresh-handle recovery, source preservation and exact read-back remain covered.

## Observed checks
- Baseline before implementation: 1,067 Python tests passed, 2 skipped; all 635
  panel tests passed. The baseline excluded the live-Premiere test module.
- Before the native guard: seven changed-source cases failed their expected refusal.
- After: full Python suite 1,048 passed, 2 skipped, 8 live cases deselected, with
  16 subtests passed. Output: output/rough-cut-retirement-full-python.txt.
- Affected regressions: 349 Python tests passed, 2 skipped; all 644 panel tests passed,
  including the Adobe API source check. Output: output/rough-cut-retirement-regressions.txt.
- Frozen native golden bytes are unchanged. Real ffmpeg extraction and subprocess
  JSON analysis ran; GPU ASR was stubbed in the relevant tests.
- Three scratch mutations were caught: bypass source checking (seven native refusals),
  remove In/Out cut clipping, and omit the captured source from CLI output. JSON
  definitions are beside this file; output/rough-cut-*-challenge.txt retains results.
- Scoped verify-loop baseline, run --strict and status returned VERIFY-STATE: green:
  2 mapped features, 2 passing checks, no unproven features or orphan tests.
  State: .verify-evidence/rough-cut-retirement/.verify-state.json.
- verify.py tests --strict passed. Its scanner does not itemize JavaScript cases;
  their execution and caught guard mutation supply the behavioral evidence.
- Scoped source bytes match the workspace. Helper and compatibility-launcher --help,
  git diff --check, and context_budget --check-handoff passed (zero structural gaps).

## Limits and next step
Node v22.16.0 and Python 3.13.4 ran these offline checks. The recorded GPU environment
remains Python 3.11.9; its ASR accuracy and model residency were not exercised.
Offline fakes do not prove Premiere transactions, stale-handle semantics or playback.
Older saved JSON cut lists without snapshots retain their previous identity checks;
start a fresh job to get the new source guard. The snapshot compares captured audio
metadata, not source-file contents or every video/effect change during analysis.
No deployment, packaging, live project editing or stored-data rewrite was performed.

Reload the panel, restart the helper for cutdeck-6, and run a fresh Rough Cut on the
previously failing sequence. Check playable audio, exact read-back, retained original,
and refusal after changing source audio while analysis is running.
