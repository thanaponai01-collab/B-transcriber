# ARCH-DESIGN
- at: d565736
- question: Cut & Sync (sync_plan, nativeSync, rough-cut analysis): why do both fail silently, and what makes the next fix cheaper?
- yardstick: name the rejecting gate in the Sync report (2 modules: cutdeck, uxp); choose the track/stream the analysis reads (4 files: workflow.js, sequence_model.py, xml_audio_extract.py, sync.py); honor clip speed in the analysis (3 files); sources: this session's two failure reports + git log of sync_plan.py / xml_audio_extract.py
- status: open
- verdict: messy in places
- context: the helper stays the audio analyst and the panel stays the only Premiere writer; no change to the job protocol or to stored job files.

## Finding 1: Every Sync rejection reads "matched no other clip"
- where: cutdeck/sync_plan.py:242
- cost: 5 distinct `return None` rejection paths in `_try_place` (sync_plan.py:136,144,160,170,188) collapse into one reason string; 1 of 11 recorded plan_sync runs was rejected and the user saw "matched nothing" with no cause (took a 43 s replay and 3 debug scripts to find it)
- badge: strong
- evidence: proven, replayed job 3d52bbd5 through plan_sync; the gate that rejected it was the fine-window count

## Finding 2: Two ffmpeg audio readers, neither can choose a stream
- where: cutdeck/sync.py:71
- cost: 2 copies of "read one file's audio" with different seek semantics (`-ss` before `-i` at sync.py:72-74, after `-i` at xml_audio_extract.py:102); 0 call sites pass a stream index; the panel sends only the file path (uxp/cutdeck/workflow.js:47) and premierepro.txt has no stream or channel-map member to read one from
- badge: strong
- evidence: traced, opened both readers; recorded OBS files carry 4 audio streams (ffprobe) and the analysis always reads stream 1

## Finding 3: The analysis reads one track and ignores clip speed, but cuts every track
- where: cutdeck/xml_audio_extract.py:85
- cost: the analysed audio is one reference track (sequence_model.py:75 `reference_track`); the cuts apply to all tracks (nativeCut.js:83 `applyPlan`); a retimed clip is decoded at 1x. 0 of 6 recorded cut jobs showed speech inside cuts, so the harm is not yet counted
- badge: worth exploring
- evidence: traced, both ends read; replay of all six recorded jobs found at most 2.5% of loud windows inside cuts, none forming a speech-length run

## Finding 4: Recorded jobs are the best fixtures and no test uses them
- where: tests/test_cutdeck_sync_plan.py:15
- cost: the sync bug needed 2.6 h files to appear; the synthetic tests used 25 s of silence. `output/premiere` is git-ignored, so the real jobs cannot be replayed by anyone else
- badge: speculative
- evidence: suspected, deletion test ambiguous: a scrubbed fixture might only move the size problem

## Decision 1: What the panel says about which audio a clip carries
- options: panel sends a stream index | helper picks the stream itself
- forces: Premiere exposes no stream index to the panel (no API found in premierepro.txt); `sequence_model.py:78` rules out guessing by loudness; the recorded files hold identical mic audio on streams 1 and 2, so no live case is failing
- door: two-way, parked: no move until a real file puts the speech on a non-first stream
- evidence: traced, grep of premierepro.txt for stream / channel map returned nothing

## Decision 2: Clip speed in the analysis
- options: refuse a retimed clip in the analysis | resample its audio to timeline length
- forces: the smallest thing that is honest is a refusal (matches `nativeCut` refusing on speed, nativeCut.js:36); resampling is new audio code nobody has asked for
- door: two-way
- evidence: traced, `AudioClipTrackItem.getSpeed` is declared (premierepro.txt:61) and nativeCut.js:36 already calls it

## Move 1: Make Sync say which gate rejected a clip
- cost: 5 rejection paths, 1 message; each unexplained failure costs a replay session
- pays: "find why Sync placed nothing": read the report instead of writing debug scripts
- files: cutdeck/sync_plan.py:136; cutdeck/sync_plan.py:188; cutdeck/sync_plan.py:242; uxp/cutdeck/timeline/nativeSync.js:303
- owner: `_try_place` names the cause; `formatReport` prints it
- callers: `_try_place` is called once (sync_plan.py:232); `formatReport` is called once (nativeSync.js:385)
- door: two-way, land it and go
- proof: `python -m pytest tests/test_cutdeck_sync_plan.py tests/test_cutdeck_plan_sync_bridge.py -q` passes with a new test asserting the unmatched reason names the rejecting gate; `node --test tests/cutdeck_native_sync.test.cjs` passes
- effort: S
- after: nothing

## Move 2: One owner for reading a file's audio
- cost: 2 ffmpeg readers with different seek behaviour; any stream or seek fix is made twice
- pays: "choose or fix the stream the analysis reads": 2 files → 1
- files: cutdeck/sync.py:71; cutdeck/xml_audio_extract.py:101
- owner: one function in cutdeck/sync.py that both callers use (`extract_mono_audio` already exists, so no new module)
- callers: extract_mono_audio (sync.py:52) and the ffmpeg call in extract_mixdown (xml_audio_extract.py:101)
- door: two-way, land it and go
- proof: `python -m pytest tests/test_cutdeck_sync_audio.py tests/test_cutdeck_xml_audio_extract.py -q` passes unchanged; the recorded-job replay loop gives the same loud-in-cuts numbers as before
- effort: S
- after: Move 1

## Move 3: Refuse a retimed clip in the analysis
- cost: a clip at other than 100% speed is decoded at 1x and its silences land in the wrong place, silently
- pays: "honor clip speed": a silent wrong cut becomes a named refusal before any edit
- files: uxp/cutdeck/workflow.js:48; cutdeck/sequence_model.py:34; cutdeck/sequence_model.py:152; cutdeck/xml_audio_extract.py:85
- owner: `from_panel_json` validates speed; `check_reference_audio` refuses
- callers: readAudioTracks (workflow.js:40), from_panel_json (sequence_model.py:152), check_reference_audio (xml_bridge.py:458)
- door: two-way, land it and go
- proof: `node --test tests/*.cjs` and `python -m pytest tests/test_cutdeck_sequence_json.py tests/test_cutdeck_xml_audio_extract.py -q` pass with a new case where speed is 200 and the analysis refuses
- effort: S
- after: nothing
