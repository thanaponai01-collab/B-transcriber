# B-Transcriber System Audit Report
### Problems · Gaps · Improvement Suggestions
*Based on full codebase review — June 2026*

---

## Executive Summary

The architecture is structurally sound and ahead of most production ASR pipelines. The contract layer, select-only reconciler, normalization-as-shared-truth, and regression-gated flywheel are all genuinely well-designed. None of those need to be rethought.

What will bite you in real daily use is different: the system is currently running as a **single-engine pipeline with no gold set, no cross-engine signal, no second engine planned, and a code-switch problem that isn't solved by the current model choice**. The infrastructure is ready; the operational and accuracy problems are what block real-world use.

---

## Part 1 — Critical Blockers (the system cannot be called production-grade without these)

---

### BLOCKER 1 · No gold set exists — the entire eval system is inert

**What the code says:** `eval/harness.py` reads from `eval/goldenset/*.json`. The eval is fully built and correct.

**What actually exists:** The `goldenset/` directory is empty. There are zero samples.

**Why this is the most critical gap:** Every safety mechanism in the system depends on the eval harness — the regression gate, the flywheel gate, the engine swap validation, the bias term promotion. None of these can fire without a gold set. Without it, you have no way to know if a change makes the system better or worse. You are operating completely blind.

**What it means in practice:** Any engine swap, any VAD threshold change, any normalization rule addition — all of these must be done on feel and intuition rather than measurement. The system was designed around the principle that nothing enters production without measurable improvement. Currently nothing can be measured at all.

**What needs to happen:** Record or select 10–15 minutes of your own footage containing real Thai-English code-switching. Run the pipeline on it. Open the editor, listen to the audio, and hand-correct every wrong token. Then promote that corrected job to the gold set. This is a human task that cannot be automated. Until it exists, everything else in this report is secondary.

---

### BLOCKER 2 · Engine B is `passthrough` — the reconciler has no second hypothesis to work with

**What the config says:** `engine_b: passthrough`. The null engine returns nothing. The reconciler has no B candidates for any slot. Every token comes from Engine A only, tagged `source_engine: a`.

**Why this breaks the design:** The entire reconciler architecture — the agreement signal, the confidence merge on matching tokens, the LLM tiebreak on disagreement, the `source_engine` provenance in the DB — exists to exploit two independent hypotheses. With passthrough, all of that is dead code. The system is producing exactly what Engine A alone would produce, just with much more infrastructure running around it.

**The deeper problem:** `whisper_multi` (Whisper large-v3) was the intended Engine B, but it was never measured. The TODO ledger says "Engine B re-introduction is eval-gated. Due when: a real bias-sensitive gold set exists." That is the right discipline — but it means Engine B is deferred behind Blocker 1. The consequence is that the system cannot learn anything from cross-engine disagreements until the gold set exists.

**What needs to happen:** Build the gold set first (Blocker 1). Then measure whether adding a second engine actually lowers `cer_thai`. Only promote Engine B if it does.

---

### BLOCKER 3 · Both engine choices are Whisper — the reconciler's core assumption is violated

**What the current config offers:** Engine A is `faster_whisper` running `biodatlab/whisper-th-medium-combined`. Engine B (when it is eventually enabled) is `whisper_multi` running `openai/whisper-large-v3`.

**Why this is architecturally wrong:** Two Whisper variants trained on similar data make correlated errors. When both models are confused by the same Thai pronunciation, the same loanword, or the same noisy audio segment, they produce the same wrong output. The reconciler sees agreement and marks the token `source_engine: both` with high confidence — but confidence here means "both engines were equally wrong." The agreement signal is false positive. The reconciler cannot distinguish genuine confidence from correlated failure.

**The principle the system was designed on:** Two engines only add value if they fail differently. Decorrelation requires different training data, different architectures, or different vendor origins — not just different model sizes from the same family.

**What needs to happen:** The second engine, when introduced, must be from a different family. The best current candidates are Typhoon ASR Real-time (FastConformer-Transducer, 115M, non-Whisper architecture, CPU-capable, fits the 3070) or a cloud engine (Gemini, GPT-4o-Transcribe) that brings genuinely independent training. Either of these would produce decorrelated errors and make the reconciler meaningful.

---

## Part 2 — Accuracy Problems (directly affecting transcription quality)

---

### ACCURACY 1 · Code-switching is not solved by the current model

**The core problem:** `biodatlab/whisper-th-medium-combined` was trained as a Thai specialist. It does well on monolingual Thai. When English appears mid-sentence — which is constant in Thai content creator, business, and tech speech — the Thai specialist tends to either drop the English word, phonetically Thai-ify it, or misfire the language detection. `whisper-large-v3` handles multilingual content but was not specifically trained for Thai-English intra-sentential switching.

**What intra-sentential switching looks like in practice:** "ผมอยากจะ share screen ให้พวกคุณดู" — the words "share screen" are English but embedded in a Thai sentence. Neither a Thai specialist nor a general multilingual model was built to expect this pattern at the word level.

**The research finding:** The 2026 state of the art for code-switching specifically is LLM-decoder models (Fun-ASR, Qwen3-ASR, Gemini 3 Pro) because the language model backbone understands context, proper nouns, and domain terminology. The transcription is no longer a pure acoustic mapping but a semantically-aware prediction. Standard Whisper-family models are acoustic-only decoders and have no semantic understanding of when a Thai sentence is about to switch scripts.

**Current mitigation in the system:** The `_script_fallback` in the reconciler routes Thai-script disagreements to Engine A and Latin-script to Engine B. This is a sensible heuristic but it only helps when a disagreement exists between two engines. With passthrough, there is no disagreement. And even with two engines, if both are Whisper, they fail the same way.

**What needs to happen:** Once Engine B is introduced, it should be a model that handles code-switching well at the intra-sentential level. The `_script_fallback` routing is correct logic; it just needs two genuinely different engines behind it to be useful.

---

### ACCURACY 2 · Normalization is incomplete against the canonical Thai standard

**What the system does:** `normalize.py` handles Thai digit conversion (๐-๙ → 0-9), mai-yamok canonicalization, Thai-Latin boundary spacing, and PyThaiNLP cleanup. The exception lexicon covers common brand names. This is solid groundwork.

**What is missing:** The Typhoon ASR team (the current state-of-the-art Thai ASR group) identified normalization as matching the impact of model scaling in their January 2026 paper. Their canonical standard specifically handles two Thai-specific ambiguities that your normalizer does not address:

First, **context-dependent number verbalization.** The same digit string "10150" is spoken differently depending on whether it is a postal code (nueng-sun-nueng-ha-sun, character by character) or a quantity (nueng-muen-nueng-roi-ha-sip). The current normalizer converts Thai numerals to Arabic digits but does not handle the reverse — what a model might produce verbally that should be written as digits. This creates a scoring artifact where a model that speaks "สิบ" and a model that writes "10" are both correct but get penalized against each other.

Second, **mai-yamok expansion context.** The current code canonicalizes mai-yamok to the attached form `wordๆ` and explicitly does not expand it, which is the right call for normalization. But the gold-authoring policy in STYLE_GUIDE.md needs to be explicit about which form models should produce, because currently if two engines produce "เร็วๆ" and "เร็วเร็ว" they will score as different when they mean the same thing.

**What needs to happen:** Align the normalization rules with the Na-Thalang 2025 canonical guideline, which is now the community standard for Thai ASR benchmarking. The exception lexicon also needs expansion — it currently covers social media apps but lacks common Thai tech/business vocabulary (LINE OA, Shopee, Lazada, Grab, บาท/฿, common Thai department stores, government abbreviations like กสทช).

---

### ACCURACY 3 · VAD thresholds are wrong for Thai soft sentence-final particles

**The config today:** `vad_threshold: 0.5`, `vad_min_silence_ms: 300`.

**The problem:** Thai speech has sentence-final particles (ครับ, ค่ะ, นะ, นะครับ) that are acoustically soft and short. They are phonetically real and semantically important — they are not silence, but at threshold 0.5 Silero VAD frequently cuts them off. The result is transcription cues that are missing their final particle, which changes the register of the speech (cutting ครับ turns formal speech into abrupt speech) and breaks boundary detection metrics.

**The fix that was already identified in memory:** Threshold 0.35, min_silence 500ms were the values proven to work for Thai. The current config.yaml is at 0.5/300 — the previous fix did not persist into the repo, or was reverted. The config has drifted back to default values.

**What needs to happen:** Reset to `vad_threshold: 0.35` and `vad_min_silence_ms: 500` in config.yaml. Test on a clip that contains sentence-final particles to confirm they survive VAD chunking.

---

### ACCURACY 4 · Chunk boundary words are lost with no overlap

**The problem:** `ingest.py` emits non-overlapping VAD chunks. `stitch.py` is built and wired in but is currently a no-op because the chunks share no overlap window. Words that happen to be spoken at the exact moment Silero VAD makes a cut — which happens whenever a speaker pauses mid-sentence — are vulnerable to being assigned to the wrong chunk or split across two chunk offsets.

**Why this matters for Thai:** Thai speech often has short pauses mid-sentence that do not represent semantic boundaries. Silero VAD will cut there, and the word at that boundary will have a timestamp offset applied from one chunk but may have been partially heard by the adjacent chunk's context window.

**The TODO status:** This is documented in TODO_LEDGER.md as a known gap. The stitch infrastructure exists and is correct. The fix is in ingest.py — emit 500–1000ms of overlap between adjacent VAD chunks. This is not a major engineering task; it is one parameter change in how chunks are built, but it requires verifying that the stitch deduplication logic handles it correctly end-to-end.

---

## Part 3 — Infrastructure and Operational Gaps

---

### INFRA 1 · Job resumability does not exist — a crash on a long file costs everything

**The problem:** `run_file()` is a single atomic transaction. If the pipeline fails halfway through a 60-minute file — an OOM, a network hiccup during model loading, a PyThaiNLP segfault — the job is marked `failed` and there is no checkpoint. You must start over from the beginning.

**The impact in real use:** For a 60-minute recording at roughly 1.5–2× real-time processing speed, a crash 45 minutes in costs 45 minutes of GPU time. For a content creator processing daily footage, this is the difference between the system being usable and being abandoned.

**What needs to happen:** Store the completion status of each phase (ingestion done, Engine A done, Engine B done) per job. On re-run of a failed job, detect what phases completed and resume from the last good checkpoint. The DB schema already supports this — `job.status` could be extended to track phase-level completion, or a separate `job_phase` table added.

---

### INFRA 2 · VFR source footage will silently produce wrong frame numbers in XML export

**The problem:** The timebase module correctly probes for VFR and sets `is_vfr=1` on the media record. The config has `conform_vfr: false`. CutDeck Phase 2 (XML export) is next on the build plan. The problem is that when XML export is built, there is no enforcement preventing it from running against a VFR original. Phone footage (the most common source format for Thai content creators) is almost always VFR.

**The consequence:** A clip that appears to cut at 00:01:23:14 in Premiere Pro will actually cut at a different frame if the source is VFR and the frame math assumed CFR. Over a 30-minute timeline, this can drift by multiple seconds — meaning every cut is in the wrong place.

**What needs to happen:** Before XML export is built, add a hard guard: if `media.is_vfr = 1` and no conformed CFR proxy exists, XML export must refuse to run and emit a clear error. The transcription itself is fine — it operates on audio. Only the frame-based XML export is affected. The conform path (ffmpeg CFR transcode) exists in the spec and needs to be implemented before any XML is exported.

---

### INFRA 3 · Gold-set authoring has no tooling and no CLI

**The problem:** The eval harness reads from `eval/goldenset/` and the format is documented, but there is no `make_gold.py` or promote-from-job CLI. To create a gold sample you must manually write a JSON file matching the exact schema the harness expects. This is error-prone enough that people will avoid doing it.

**Why this compounds Blocker 1:** Even once the motivation to build the gold set exists, the friction of manual JSON authoring will delay it. The correct flow is: run pipeline on audio → open editor → correct tokens → one CLI command promotes the corrected job to a frozen gold sample. That CLI does not exist.

**What needs to happen:** A `make_gold.py` tool that takes a completed, human-corrected job ID, exports its corrected tokens as a properly-formatted gold JSON, pairs it with the source audio, and writes it to `eval/goldenset/`. A freeze confirmation step should be included — once a sample is in the gold set, it should not change without explicit intent.

---

### INFRA 4 · The editor has no reason-tagging UI despite the backend being ready

**The problem:** The editor schema has a `reason` column in the correction table. The API accepts `reason` in the save payload. `diff.py` carries `reason` through to the correction record. The one-tap reason tag UI in `static/index.html` is not built. The TODO ledger documents this.

**Why this matters for the flywheel:** The reason tag (misheard, spelling, code-switch boundary, name/term, style) is what turns the correction database from "a list of things the model got wrong" into "a structured understanding of why it got them wrong." Without reason data, the flywheel can only promote terms that appear frequently. With reason data, you could detect that all code-switch boundary errors happen at the same acoustic pattern, or that all name/term errors are for the same class of proper nouns.

**What needs to happen:** Add the one-tap reason selector to the editor's token UI. It should be visible when a token is selected for editing — a small set of labelled buttons, not a text field. The data path already exists; this is purely a frontend task.

---

### INFRA 5 · The bias term injection prompt budget is not enforced

**The config:** `flywheel.bias_prompt_budget: 200` exists in config.yaml.

**The problem:** `flywheel/inject.py` exists in the codebase but `run.py` does not call it. The `bias_terms` list is passed directly to the engine as a raw list. The engine joins them with spaces into `initial_prompt`. For Thai, each character is a separate token — a list of 20 Thai terms could already exceed the 200-token budget. Beyond the budget, terms are silently truncated by the Whisper tokenizer. The highest-weight, most important bias terms may be the ones lost.

**What needs to happen:** Call `inject.py`'s `build_prompt()` in `run.py` before passing bias_terms to the engine. This ensures the budget is respected, highest-weight terms are packed first, and the engine's initial_prompt never silently loses terms. Currently the bias flywheel could be accumulating terms that never actually reach the model.

---

### INFRA 6 · DeepFilterNet denoise runs file-wide but writes to temp files per window

**The problem:** `ingest.py`'s rolling denoise implementation writes each 2-second window to a temp `.wav` file, calls DeepFilterNet on it, then reads it back. For a 10-minute file this is 300 temp file writes and reads. The model is also initialized inside `init_df()` and then passed around — but if `init_df()` is called once and the model is loaded once, that is correct. The temp file I/O is the inefficiency.

**Secondary issue:** DeepFilterNet operates at its own internal sample rate, which may differ from 16kHz. The code has a resample step after enhancement, which is correct. But writing to `.wav`, denoising, and reading back introduces two additional codec round-trips per window on top of the resampling. For real content creator use, this makes denoise a significant runtime cost with no measurement of whether it actually helps.

**What needs to happen:** Profile whether DeepFilterNet actually improves `cer_thai` on your specific footage type before keeping it in the default path. Content creator footage recorded in a room is usually not the high-noise environment DeepFilterNet was designed for. If it helps, switch to in-memory tensor processing instead of temp file I/O. If it does not help measurably on your gold set, consider making it opt-in rather than the default.

---

## Part 4 — Model and Architecture Improvements (once blockers are resolved)

---

### MODEL 1 · The best available Thai model is not in the stack

**Current Engine A:** `biodatlab/whisper-th-medium-combined` via CTranslate2.

**The state of the art (January 2026):** Typhoon ASR Real-time (typhoon-ai/typhoon-asr-realtime) is a 115M-parameter FastConformer-Transducer model that achieves comparable accuracy to Whisper large-v3 at 45× lower computational cost. It is CPU-capable, runs on the 3070 well within the 8GB VRAM budget, is fully open (Apache license), and is designed specifically for Thai. It is also hallucination-resistant by architecture — the Transducer decoder cannot produce text that has no acoustic support, unlike Whisper's encoder-decoder which can loop on silence.

**Why this matters:** The current engine was selected because it was the best available Thai Whisper model. Typhoon ASR Real-time is not a Whisper model — it is a different architecture family, which also makes it an excellent decorrelated Engine B candidate. If Engine A stays Whisper-family and Engine B is Typhoon (Conformer-Transducer), the two engines fail differently and the reconciler produces a genuine signal.

**Important caveat:** Typhoon uses the canonical Na-Thalang 2025 normalization standard. If Engine A produces output in a different normalization convention, the reconciler's text-matching in `align_hyp.py` will score them as different (Jaccard similarity will be lower) even when they transcribed the same audio correctly. Normalization alignment between engines is required before the reconciler can work at full strength.

---

### MODEL 2 · Fun-ASR-Nano is now available and handles Thai with diarization

**What changed:** As of June 2026, Fun-ASR-Nano supports Thai among 31 languages, runs on llama.cpp/GGUF as a self-contained binary with built-in VAD, quantizes down to ~484MB, and now includes speaker diarization. Python 3.13 compatibility via the GGUF runtime path may resolve the previous wheel availability problem that blocked `funasr.py`.

**Why this is relevant to the system:** Fun-ASR-Nano represents a path to three currently-deferred features in a single model: decorrelated Engine B (different architecture, different training data), code-switch handling (trained multilingual, not Thai-specialist), and speaker diarization (currently nullable `speaker_id` in the schema, deferred to v2). If the GGUF path works on Python 3.13, this could resolve multiple deferred items simultaneously.

**What needs to happen:** Test whether Fun-ASR-Nano's GGUF runtime resolves the Python 3.13 wheel issue that blocked `funasr.py`. If it does, this becomes a strong Engine B candidate — genuinely decorrelated from Whisper and better at code-switching.

---

### ARCH 1 · The `_script_fallback` heuristic has a hidden failure mode

**What the reconciler does on disagreement without LLM:** Route Thai-script tokens to Engine A and Latin-script tokens to Engine B. This assumes Engine A is always the Thai specialist and Engine B is always the multilingual generalist.

**The hidden problem:** `ta.script` is the script classification of Engine A's token. If Engine A hallucinated a Thai-looking output for what was actually English speech, the fallback routes to Engine A — confirming the hallucination. The fallback trusts Engine A's script detection of its own output, which is circular reasoning. An engine that confidently produces the wrong script for a word will have that wrong answer selected by the fallback.

**A better approach:** The fallback should use the script of the audio segment, not the script of Engine A's output. The audio's most likely script can be estimated from the surrounding tokens' consensus. Alternatively, weight by confidence when both engines have confidence values, and only use the script heuristic as a tiebreaker when confidence is unavailable for both.

---

### ARCH 2 · The LLM reconciler is wired but has no defined model, prompt, or rate-limit handling

**What exists:** `reconcile.py` accepts an `llm_fn` callable that returns an index (0 or 1). `run.py` calls `reconcile.reconcile(slots, bias_terms=bias_terms)` with no `llm_fn` argument — so `llm_fn` is always None and the LLM path never executes. The reconciler falls through to `_script_fallback` on every disagreement.

**What is missing:** No actual LLM integration is wired. No model is specified. No prompt is defined. No rate limiting or cost budget exists. No fallback behavior for API timeout is implemented beyond the try/except in `_pick()`.

**Why this matters:** The LLM reconciler is the system's most powerful accuracy tool — it is the only mechanism that can reason about semantic context when two engines disagree. Without it, disagreements on ambiguous code-switch boundaries always go to the heuristic, which is wrong on exactly the hardest cases.

**What needs to happen:** Define the prompt (short context window — just the two candidate tokens plus the surrounding 2–3 tokens from each engine for context, ask for index 0 or 1), wire a concrete LLM client (Anthropic API is already implied by the memory context), add a token budget guard, and add cost-per-job logging so you can see what the reconciler is costing per minute of audio.

---

## Part 5 — CutDeck Gaps (the rough-cut system)

---

### CUTDECK 1 · Phase 2 (XML export) is not built — the most critical external interface

**Status from TODO ledger:** Phase 0 and Phase 1 are done. Phase 2 (FCP7 XML export) is "next."

**Why this is the highest risk item in the CutDeck build:** XML round-trip into Premiere Pro is the only part of the system that depends on an external tool behaving correctly. Every other component is self-contained. The XML format has quirks around timebase representation, sequence duration, and clip linking that cannot be validated without an actual Premiere import test on a real 29.97 file. The longer this is deferred, the more other code gets built on top of assumptions about how XML works — and if the XML is wrong, everything built on top of it is wrong.

**The correct build order:** Build the minimal XML that imports a single cut cleanly into Premiere before building any more of the CutDeck logic. One clip, correct timebase, correct frame count, Premiere accepts it. Then expand.

---

### CUTDECK 2 · VFR guard is required before XML export exists

**Connected to INFRA 2 above.** The XML export must refuse to run on VFR sources. This guard needs to be in place before the first line of XML export code is written, not added later as a patch. Otherwise the first Premiere test will be against a VFR phone clip and the frames will be wrong, making debugging ambiguous — is the XML format wrong, or is the VFR frame math wrong?

---

### CUTDECK 3 · The `cut_correction` table and Phase 3 flywheel are not designed

**Status:** The `cut_plan` table exists. The `Label` type in `cutdeck/contracts.py` exists but is unused. The Phase 3 correction capture (human edits to a CutPlan flowing back as training corrections) is documented as deferred until after Phase 2.

**The gap this creates:** When a human reviews the exported rough cut in Premiere and changes the cut points, there is currently no path to bring those changes back into the system. The flywheel only exists for transcription corrections, not for cut decisions. The CutDeck system will not learn from use until the round-trip path is built.

---

## Summary — Priority Order

**Do first (unblocks everything else):**
1. Build the gold set — 10–15 minutes of hand-corrected footage in `eval/goldenset/`
2. Fix VAD thresholds back to Thai-tuned values (0.35 / 500ms)

**Do second (accuracy wins on real footage):**
3. Add Typhoon ASR Real-time or Fun-ASR-Nano as a decorrelated Engine B, gated by gold set CER measurement
4. Align normalization to the Na-Thalang 2025 canonical standard
5. Add chunk overlap in ingest.py to stop losing words at VAD boundaries

**Do third (make the system production-durable):**
6. Build gold-set authoring CLI (`make_gold.py`)
7. Wire the LLM reconciler with a concrete model and prompt
8. Fix bias term injection to use `inject.py` with the prompt budget
9. Add job resumability for long files
10. Add editor reason-tag UI

**Do fourth (CutDeck path to Premiere):**
11. Build Phase 2 XML export with VFR guard before any other CutDeck work
12. Test XML import in Premiere on a real 29.97 file before expanding
