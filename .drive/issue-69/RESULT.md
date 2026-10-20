2026-10-20: FasterWhisper last_speech_timestamp reset & silent segment gate (Issue #69)

Cause proven:
1. BatchedInferencePipeline.transcribe marks compression_ratio_threshold, log_prob_threshold, and no_speech_threshold as Unused Arguments, allowing segments scored as silent garbage (no_speech_prob > 0.6 and avg_logprob < -1.0) into downstream tokenization.
2. BatchedInferencePipeline retains mutated last_speech_timestamp across transcribe calls, corrupting timestamps when subsequent windows start at 0.0s.

Treatment:
1. Reset self._pipeline.last_speech_timestamp = 0.0 before every BatchedInferencePipeline.transcribe call in FasterWhisperEngine._decode.
2. Filter out silent segments in FasterWhisperEngine._words_of where no_speech_prob > no_speech_threshold and avg_logprob < log_prob_threshold.
3. Expose threshold overrides in FasterWhisperEngine.__init__ and wire them to common decode options and _words_of calls.

Evidence:
- tests/test_faster_whisper.py: 4 passed.
- Scoped drive stage prove: 28 passed.
- Engine regression suite (VERIFY.md): 95 passed.
- Full pytest suite: 1102 passed, 2 skipped, 0 failures.
- Node test suite: 689 passed, 0 failures.
- RUN.json status: complete.
