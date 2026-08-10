"""Engine — faster-whisper (CTranslate2) backend.

Same Whisper checkpoint family as whisper_thai, but run through CTranslate2 instead
of HuggingFace transformers: typically 3-4x faster and lower VRAM at equal accuracy,
which is why it's the default Engine A on the 8GB card. Needs a CT2-converted model
dir (produced once by `ct2-transformers-converter`, see README); it cannot load a raw
HF checkpoint.

CTranslate2 exposes the real Whisper anti-hallucination knobs the HF pipeline buried:
condition_on_previous_text=False stops loops propagating across windows, and the
compression/log-prob/no-speech thresholds drop garbage segments outright.
"""

from __future__ import annotations

import gc
import logging
import os
import sys
from pathlib import Path

from transcribe.contracts import EngineInput, EngineResult, RecognizedToken, detect_script
from transcribe.engines.base import Engine
from transcribe.engines.registry import register
from transcribe.flywheel.inject import BiasTerm, build_prompt

logger = logging.getLogger(__name__)


def _register_cuda_dll_dirs() -> str:
    """Make the pip nvidia-*-cu12 wheels' bundled DLLs (cublas64_12.dll,
    cudnn64_9.dll, ...) loadable by CTranslate2 on Windows. Returns the PATH
    value from before mutation, so the caller can restore it later.

    Those wheels drop their DLLs under site-packages/nvidia/<pkg>/bin, which is
    never on PATH. torch works around the equivalent problem for its own
    (bundled, different-version) CUDA libs by registering torch/lib itself, but
    that's a separate cublas64_13.dll — CTranslate2 needs the CUDA-12 one.
    CTranslate2 resolves it via a bare LoadLibrary call deep inside its native
    code (lazily, on first GPU op) rather than through Python's import
    machinery, so os.add_dll_directory() does not cover it (that only affects
    extension-module imports and ctypes loads) — PATH is the search list a bare
    LoadLibrary call actually consults, so that's what has to be extended.
    Without this, load fails with 'cublas64_12.dll is not found or cannot be
    loaded' even though the DLL is present in the venv.

    CALLER MUST RESTORE PATH ON unload(): this prepends a CUDA-12 cuDNN
    (cudnn64_9.dll) ahead of everything else on PATH, process-wide. A
    same-process engine loaded afterward that resolves its OWN cuDNN via
    Windows' DLL search order — e.g. NeMo/PyTorch (torch 2.13+cu130, a
    different CUDA generation) — can have Windows hand it THIS prepended
    cudnn64_9.dll instead of the one it actually linked against, producing
    'CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH' on its very first conv forward
    pass. Reproduced 2026-07-16: typhoon_rt (NeMo) works standalone but
    crashes the same way after only calling this function — no CTranslate2
    model even needs to load — confirming the PATH mutation itself, not GPU
    residency, is the cause. This makes the mutation load()-scoped instead of
    process-lifetime: see FasterWhisperEngine.unload().
    """
    if sys.platform != "win32":
        return os.environ.get("PATH", "")
    original_path = os.environ.get("PATH", "")
    nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if not nvidia_root.is_dir():
        return original_path
    bin_dirs = [str(p) for p in nvidia_root.glob("*/bin")]
    path = original_path
    for bin_dir in bin_dirs:
        if bin_dir not in path:
            path = bin_dir + os.pathsep + path
    os.environ["PATH"] = path
    return original_path


# Converted once via ct2-transformers-converter (see README). Repo-root-relative so
# it resolves regardless of the caller's cwd.
_DEFAULT_MODEL = str(Path(__file__).resolve().parents[2] / "models" / "whisper-th-medium-ct2")

# Phrase-cue grouping. ponytail: fixed heuristics — break on a speech gap, or once a
# cue reaches target length/duration. Tune here if cues read too long/short; gap_ms
# matches the pipeline's segment.gap_ms default (700 ms), target_chars/target_ms are
# subtitle-line sizing.
_CUE_GAP_MS = 700
_CUE_TARGET_MS = 4000
_CUE_TARGET_CHARS = 42

# Whisper inserts spaces into Thai (which has none) roughly at breath/clause
# boundaries — a free segmentation signal from the acoustic model that cue
# grouping used to discard, buffering whitespace as cue-interior only. Measured
# against a hand-recut reference SRT, every space Whisper emitted inside a cue
# was a place the human either split or would have, had the cue been longer.
# So a space is a break candidate — but only once the cue already carries enough
# text to stand alone, otherwise short interjections ("โอเค โอเค") shatter into
# one-word cues. Both minima must be met.
_CUE_SPACE_MIN_CHARS = 12
_CUE_SPACE_MIN_MS = 700

# HANDOFF_CEILING_BREAK §5: "greedy" is the original fill above, unchanged and
# still the production default. "dp" is the cost-minimising split
# (_group_words_into_cues_dp) — probe it via config.yaml's
# engines.faster_whisper.cue_split_algorithm, gated with --experiment, before
# ever flipping this default.
_CUE_SPLIT_ALGORITHM = "greedy"

# DP cost weights (_group_words_into_cues_dp). Initial heuristics, not tuned —
# same "principled floors, not tuned values" status as the greedy knobs above
# until the harness has an opinion. Size cost is deliberately asymmetric:
# quadratic once a cue exceeds target_chars (mirrors the greedy path's hard
# "close it now" trigger — an oversized cue gets punished hard), but only
# mildly linear when a cue undershoots (measured 2026-08-04: a symmetric
# quadratic here made DP prefer merging toward the target from BOTH
# directions, producing *fewer, longer* cues than the hand-recut references
# want — cue_boundary_error_rate regressed 0.3590 -> 0.4554 vs the greedy
# baseline on the first probe. The gold set wants more, shorter cues, i.e.
# undershoot should be nearly free). A Whisper-emitted space is worth
# discounting like a ~7-char improvement; overflowing target_ms by a full
# extra second costs as much as a wildly oversized cue.
_DP_UNDERSHOOT_WEIGHT = 0.08
_DP_OVERSHOOT_WEIGHT = 2.0
_DP_SPACE_DISCOUNT = 50.0
_DP_OVERFLOW_UNIT_MS = 100
_DP_OVERFLOW_WEIGHT = 4.0
_DP_RUNT_PENALTY = 1_000_000.0

_SR = 16000

# Whisper's encoder hard-caps a single decode window at ~30s. A speech run longer
# than this with no pause anywhere near the cap forces faster-whisper's own VAD to
# split "aggressively" mid-utterance with no overlap — decode quality collapses
# right at that seam (observed: several seconds of garbled/missing text at the
# cut). Any span longer than _LONG_SPAN_SAFE_S gets split into our own overlapping
# windows instead (see _split_long_span), decoded separately, and stitched back
# together — the same seam-recovery trick chunk engines get from
# config.yaml's chunk_overlap_ms, applied here to this whole-file engine's rare
# long-pause-free-run case.
# Tuning note: shrinking _LONG_SPAN_SAFE_S (e.g. to 15-20s) recovers a decode-
# quality drop that can still happen *within* a single 25s window on very dense
# speech, but widening the overlap that comes with it exposes stitch.py's dedup
# to more words in the ambiguous zone — Thai has no word boundaries, so two
# independent decodes of the same audio often tokenize it slightly differently,
# producing visible stutter (e.g. "ที่ี่เกี่ี่ยว") across many seams. Verified
# empirically: 25s/4s stutter-free with one small residual gap on a hard passage;
# 15-20s recovers that gap but stutters broadly.
#
# Update (2026-07-30): that stutter turned out NOT to be a text-matching problem
# — the seam duplicates matched on text fine and were lost to stitch.py's IoU
# gate, which is structurally 0.0 for the zero-length combining-mark pieces
# Whisper emits for Thai. stitch.py now also accepts centre-coincident
# duplicates (_coincident), which fixed the observed stutter at 25s. Re-probing
# a shorter _LONG_SPAN_SAFE_S is now worth doing, but measure it — the residual
# artifacts here are the model stuttering inside one window, which no amount of
# seam handling can fix.
_LONG_SPAN_SAFE_S = 25.0
_LONG_SPAN_OVERLAP_S = 4.0

# Truncated-tail recovery: faster-whisper occasionally stops generating well
# before a window's audio actually ends (early EOS on a hard passage), then
# stretches the *last* word's end-timestamp out toward the window boundary to
# fill the gap — so several real seconds of dropped speech show up as one
# absurdly long "word" instead of an obvious hole. _TRUNCATION_TAIL_MS is how
# long a single word's span has to be to count as suspicious.
# _TRUNCATION_LOOKBACK_MS bounds how far back _find_safe_cut searches for a
# genuine inter-token pause to cut on. See _recover_truncated_tail.
#
# Update (2026-08-10, TODO_LEDGER.md incident investigation): this used to
# also require the suspicious word's end to land within 500ms of the
# window's own end ("stretched all the way to the boundary") before
# attempting recovery. Confirmed on real production audio that this was too
# strict — several genuine content-loss cases had a suspicious word ending
# 1.5-4s *short* of the window boundary (the model produced a stray fragment
# then simply stopped, without reaching for the boundary at all), and were
# silently skipped. Redecoding the same passage as a differently-windowed
# clip recovered real, coherent speech at every one of those spots. The
# recovery attempt is now gated only on the word's own suspicious duration
# plus there being meaningful leftover audio to redecode (checked below via
# the tail-audio length) — not on how close it lands to the window edge.
_TRUNCATION_TAIL_MS = 1500
_TRUNCATION_LOOKBACK_MS = 2500


def _is_cuda_oom(e: Exception) -> bool:
    """True for a CUDA out-of-memory error, however the stack surfaces it."""
    try:
        import torch
        if isinstance(e, torch.cuda.OutOfMemoryError):
            return True
    except Exception:
        pass
    return "out of memory" in str(e).lower()


def _vad_speech_spans(audio, threshold: float, min_silence_ms: int) -> list[tuple[float, float]]:
    """Real speech spans (in seconds) with NO max-duration cap.

    We deliberately don't use faster-whisper's vad_filter=True path for this —
    its internal VadOptions defaults max_speech_duration_s to the encoder's
    chunk_length and splits long runs "aggressively" at that boundary if no
    silence is nearby. Detecting spans uncapped lets the caller decide how to
    split anything too long, with overlap, instead of an arbitrary hard cut.
    """
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    opts = VadOptions(threshold=threshold, min_silence_duration_ms=min_silence_ms)
    ts = get_speech_timestamps(audio, opts)
    return [(t["start"] / _SR, t["end"] / _SR) for t in ts]


def _merge_contiguous_spans(spans: list[tuple[float, float]],
                             max_gap_s: float = 0.05) -> list[tuple[float, float]]:
    """Merge adjacent VAD spans separated by a (near-)zero reported gap.

    Root cause of a 2026-08-06 production incident (TODO_LEDGER.md, "recurring
    mid-word truncation / dropped-content bug"): faster_whisper.vad's own
    get_speech_timestamps pads each speech chunk by speech_pad_ms (400ms) on
    both sides, and when the real silence between two consecutive chunks is
    under 2*speech_pad_ms (800ms) it splits that silence evenly onto both
    sides instead — so the *reported* gap between the two returned spans is
    exactly 0 for ANY real pause shorter than ~800ms (a routine breath or
    clause boundary in conversational speech), indistinguishable in the
    output from "no pause at all". `_transcribe_batched` used to treat every
    VAD span as a fully independent decode: `_split_long_span`'s overlap+
    stitch only reconciles windows *inside* one span, so a zero-gap pair of
    spans got a hard, unrecovered seam right where real speech continued.
    Confirmed on the real incident audio: redecoding straight across one such
    seam (as a single window) recovered a ~4s utterance that was completely
    missing from production output. Merging first means the seam disappears
    before windowing ever happens, and the existing overlap+stitch +
    _recover_truncated_tail machinery covers it like any other internal
    boundary. A genuine pause (>=~800ms real silence) still reports a nonzero
    gap here and is left as a separate span, unchanged.
    """
    if not spans:
        return spans
    merged = [spans[0]]
    for start, end in spans[1:]:
        prev_start, prev_end = merged[-1]
        if start - prev_end <= max_gap_s:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))
    return merged


def _split_long_span(start_s: float, end_s: float,
                      max_span_s: float = _LONG_SPAN_SAFE_S,
                      overlap_s: float = _LONG_SPAN_OVERLAP_S) -> list[tuple[float, float]]:
    """Chop a speech span longer than max_span_s into overlapping sub-windows,
    each safely under Whisper's ~30s encoder limit. Returns [(start_s, end_s)]
    unchanged if the span is already short enough."""
    if end_s - start_s <= max_span_s:
        return [(start_s, end_s)]
    stride = max_span_s - overlap_s
    windows = []
    pos = start_s
    while True:
        win_end = min(pos + max_span_s, end_s)
        windows.append((pos, win_end))
        if win_end >= end_s:
            break
        pos += stride
    return windows


def _sentence_boundary_offsets(text: str) -> list[int]:
    """Character offsets in `text` where pythainlp's crfcut model believes a new
    sentence begins (offset 0 excluded — the first token always starts a cue
    regardless). crfcut is a CRF trained to segment *unpunctuated* running
    text, which is what Whisper's raw Thai output is (no periods/commas) —
    this is the intended use case, not a punctuation-based fallback.
    Best-effort: any failure (missing optional dependency, model fetch
    issue) degrades to no forced sentence breaks rather than raising, since
    the gap/length heuristics below still produce usable cues on their own.
    """
    try:
        from pythainlp.tokenize import sent_tokenize
        sentences = sent_tokenize(text, engine="crfcut", keep_whitespace=True)
    except Exception:
        logger.warning("Sentence tokenization unavailable — cues will not be "
                        "forced to start on sentence boundaries", exc_info=True)
        return []
    offsets = []
    pos = 0
    for sent in sentences:
        if pos:
            offsets.append(pos)
        pos += len(sent)
    return offsets


def _group_words_into_cues(words, gap_ms=_CUE_GAP_MS, target_ms=_CUE_TARGET_MS,
                           target_chars=_CUE_TARGET_CHARS,
                           space_min_chars=_CUE_SPACE_MIN_CHARS,
                           space_min_ms=_CUE_SPACE_MIN_MS,
                           algorithm=_CUE_SPLIT_ALGORITHM,
                           lexicon=None):
    """Group Whisper word-pieces into subtitle-length phrase cues.

    Dispatches to one of two cue-boundary strategies (HANDOFF_CEILING_BREAK
    §5): the original greedy fill (default, unchanged — see
    `_group_words_into_cues_greedy`) or the cost-minimising DP split
    (`algorithm="dp"`, see `_group_words_into_cues_dp`). Kept as separate
    functions rather than branching deep inside one, so the greedy path stays
    provably untouched (every pre-existing test below still exercises it
    byte-for-byte) while the DP path is probed via `--experiment` per the
    handoff's A/B discipline. `config.yaml`'s `engines.faster_whisper.
    cue_split_algorithm` is the switch; delete the loser once the harness
    decides (handoff §5: "keep the greedy path behind a config flag for one
    release for A/B, then delete").

    `lexicon` (a `transcribe.thai.atoms.BreakLexicon`, HANDOFF_THAI_BREAK_ATOMS.md):
    both paths glue break-atoms before splitting, so STYLE_GUIDE §7's
    unsplittable units are illegal to break by construction, not by a veto
    check at each break decision point. `None` falls back to
    `default_lexicon({})` — the four base rules, no exception-lexicon terms.
    """
    if algorithm == "dp":
        return _group_words_into_cues_dp(
            words, gap_ms=gap_ms, target_ms=target_ms, target_chars=target_chars,
            min_chars=space_min_chars, min_ms=space_min_ms, lexicon=lexicon)
    return _group_words_into_cues_greedy(
        words, gap_ms=gap_ms, target_ms=target_ms, target_chars=target_chars,
        space_min_chars=space_min_chars, space_min_ms=space_min_ms, lexicon=lexicon)


def _group_words_into_cues_greedy(words, gap_ms=_CUE_GAP_MS, target_ms=_CUE_TARGET_MS,
                           target_chars=_CUE_TARGET_CHARS,
                           space_min_chars=_CUE_SPACE_MIN_CHARS,
                           space_min_ms=_CUE_SPACE_MIN_MS,
                           lexicon=None):
    """Group Whisper word-pieces into subtitle-length phrase cues at real word boundaries.

    `words` is a list of (text, start_ms, end_ms, confidence) — confidence is the
    source word-piece's probability, or None if the engine didn't report one.
    Whisper word-pieces for spaceless Thai are sub-word and only sporadically
    carry a leading space, so they cannot be used to find word boundaries — a
    long spaceless run would never break. Instead we rebuild the full text with
    a per-character timeline, segment it with pythainlp (Latin/whitespace
    preserved), glue the result into break-atoms (HANDOFF_THAI_BREAK_ATOMS.md —
    STYLE_GUIDE §7's unsplittable units, e.g. `ทะเลาะกัน`, `ผู้หญิงคนนั้น`,
    merged into one indivisible token), and group whole atoms into cues. Every
    boundary this loop can choose is therefore legal by construction — no veto
    check is needed at the break decision points below.

    A cue must never start mid-sentence: a long sentence can still be split into
    several cues (on a silence gap >= gap_ms, or once target_ms / target_chars is
    hit, same as before), but a cue break is also forced at every sentence
    boundary crfcut finds, so a cue never opens with the tail of one sentence
    fused to the head of the next. Sentence detection on raw ASR output (no
    punctuation, colloquial speech) is inherently imperfect — treat it as a
    heuristic that reduces mid-sentence cue starts, not a guarantee. A boundary
    crfcut places inside an atom is snapped outward to the atom's start
    (`snap_boundary_offsets`) rather than treated as license to split it.

    A space Whisper itself emitted inside Thai is a third break signal (see
    _CUE_SPACE_MIN_CHARS): it marks a breath/clause boundary the acoustic model
    heard, and breaking there beats breaking wherever the character budget
    happens to run out. It applies only once the cue holds space_min_chars AND
    space_min_ms, so short interjections stay whole.

    Returns list of (text, start_ms, end_ms, confidence) — confidence is the mean
    of the constituent atoms' probabilities, or None if none carried one.
    """
    from cutdeck.words import timed_tokens
    from transcribe.thai.atoms import default_lexicon, glue_atoms, snap_boundary_offsets

    # 1-3. per-character timeline -> real word boundaries -> mapped time spans.
    # Shared with cutdeck/words.py (CutDeck Phase 1) so there is exactly one
    # implementation of Thai word-timeline reconstruction, not two.
    full_text, raw_timed = timed_tokens(words)
    if not full_text:
        return []

    # 3.5. glue bound units into atoms before any break decision runs.
    timed = glue_atoms(raw_timed, lexicon or default_lexicon({}))

    # sentence-start offsets in the same char coordinates as `timed` below.
    boundary_offsets = snap_boundary_offsets(_sentence_boundary_offsets(full_text), timed)
    boundary_idx = 0

    # 4. greedy group whole atoms into cues. Whitespace atoms are buffered and only
    # kept once a real atom follows in the same cue, so a cue never starts or ends on
    # whitespace (a trailing space carries the next atom's timing and would corrupt
    # the cue's end time and the gap check).
    cues: list[tuple[str, int, int, float | None]] = []
    cur: list[tuple[str, int, int, float | None]] = []
    pending_ws: list[tuple[str, int, int, float | None]] = []

    def _close():
        text = "".join(x[0] for x in cur).strip()
        if text:
            confs = [x[3] for x in cur if x[3] is not None]
            conf = sum(confs) / len(confs) if confs else None
            cues.append((text, cur[0][1], cur[-1][2], conf))

    def _cue_so_far() -> tuple[int, int]:
        """(chars, span_ms) of the open cue — 0/0 when nothing is open."""
        if not cur:
            return 0, 0
        return len("".join(x[0] for x in cur).strip()), cur[-1][2] - cur[0][1]

    def _remainder_stands_alone(i: int) -> bool:
        """Would the text AFTER this space form a viable cue on its own?

        Breaking at a space only helps if both sides are viable — otherwise it
        trades one bad boundary for a flash-frame runt (a 140ms 'โอเค' cue was
        exactly this). Scans forward to wherever the next break would land
        anyway: the next space, the next real pause, or end of stream.
        """
        chars, first_start, last_end = 0, None, None
        for t2, s2, e2, _conf2, _pos2 in timed[i + 1:]:
            if not t2.strip():
                break                        # the next space closes the remainder
            if last_end is not None and s2 - last_end >= gap_ms:
                break                        # a real pause closes it
            if first_start is None:
                first_start = s2
            chars += len(t2.strip())
            last_end = e2
            if chars >= target_chars:
                return True                  # long enough on its own regardless
        if first_start is None:
            return False
        return chars >= space_min_chars and (last_end - first_start) >= space_min_ms

    for i, (t, s, e, conf, char_pos) in enumerate(timed):
        if not t.strip():
            if not cur:
                continue
            n_chars, span = _cue_so_far()
            if (n_chars >= space_min_chars and span >= space_min_ms
                    and _remainder_stands_alone(i)):
                # Break on Whisper's own breath boundary. The whitespace itself is
                # dropped: a cue must not end on a space (it carries the *next*
                # atom's timing, which would corrupt the cue end and the gap check).
                _close()
                cur = []
                pending_ws = []
            else:
                pending_ws.append((t, s, e, conf))
            continue
        # Consume any sentence boundary at or before this token — forces a
        # break here even if the gap/length heuristics wouldn't have broken
        # on their own (e.g. no pause between "...ทั้งนั้น" and "อย่า...").
        new_sentence = False
        while boundary_idx < len(boundary_offsets) and char_pos >= boundary_offsets[boundary_idx]:
            new_sentence = True
            boundary_idx += 1
        if cur:
            gap = s - cur[-1][2]
            span = e - cur[0][1]
            n_chars = len("".join(x[0] for x in cur).strip())
            wants_break = new_sentence or gap >= gap_ms or span > target_ms or n_chars >= target_chars
            if wants_break:
                _close()
                cur = []
        if cur:
            cur.extend(pending_ws)  # interior whitespace only
        pending_ws = []
        cur.append((t, s, e, conf))
    if cur:
        _close()
    return cues


def _dp_split_segment(timed, real_idx, seg_start, seg_end,
                       target_ms, target_chars, min_chars, min_ms):
    """Cost-minimising split of one hard-delimited run of real atoms (local
    indices `seg_start:seg_end` into `real_idx`) into cues. Classic subtitle
    line-breaking DP: candidates are every inter-atom boundary — `timed` has
    already been through `glue_atoms` (HANDOFF_THAI_BREAK_ATOMS.md), so every
    such boundary is legal by construction and none need be excluded here;
    dp[c] is the min cost to cover local atoms [0, c)."""
    n_words = seg_end - seg_start

    # Legal candidate breaks (local atom index where a new cue may start) —
    # every inter-atom boundary, since an atom can never be split.
    candidates = list(range(n_words + 1))

    def had_whitespace_before(c) -> bool:
        """A raw whitespace piece sits between local words c-1 and c — Whisper's
        own breath/clause boundary signal (discounted, not required, unlike
        the greedy path's hard minima)."""
        if c <= 0 or c >= n_words:
            return False
        return real_idx[seg_start + c] - real_idx[seg_start + c - 1] > 1

    def cue_text(a, c):
        lo = real_idx[seg_start + a]
        hi = real_idx[seg_start + c - 1]
        return "".join(tok[0] for tok in timed[lo:hi + 1]).strip()

    def cue_span(a, c):
        lo = real_idx[seg_start + a]
        hi = real_idx[seg_start + c - 1]
        return len(cue_text(a, c)), timed[lo][1], timed[hi][2]

    dp = {0: 0.0}
    back = {}
    for c in candidates:
        if c == 0:
            continue
        best_cost, best_a = float("inf"), None
        for a in candidates:
            if a not in dp or a >= c:
                continue
            chars, start_ms, end_ms = cue_span(a, c)
            span_ms = end_ms - start_ms
            if chars > target_chars:
                size_cost = ((chars - target_chars) ** 2) * _DP_OVERSHOOT_WEIGHT
            else:
                size_cost = (target_chars - chars) * _DP_UNDERSHOOT_WEIGHT
            overflow_ms = max(0, span_ms - target_ms)
            overflow_cost = ((overflow_ms // _DP_OVERFLOW_UNIT_MS) ** 2) * _DP_OVERFLOW_WEIGHT
            viable = (chars >= min_chars and span_ms >= min_ms) or chars >= target_chars
            runt_cost = 0.0 if viable else _DP_RUNT_PENALTY
            discount = _DP_SPACE_DISCOUNT if had_whitespace_before(c) else 0.0
            cost = dp[a] + size_cost + overflow_cost + runt_cost - discount
            if cost < best_cost:
                best_cost, best_a = cost, a
        dp[c] = best_cost
        back[c] = best_a

    breaks = []
    c = n_words
    while c != 0:
        a = back[c]
        breaks.append((a, c))
        c = a
    breaks.reverse()

    cues: list[tuple[str, int, int, float | None]] = []
    for a, c in breaks:
        lo = real_idx[seg_start + a]
        hi = real_idx[seg_start + c - 1]
        text = cue_text(a, c)
        if not text:
            continue
        confs = [tok[3] for tok in timed[lo:hi + 1] if tok[3] is not None]
        conf = sum(confs) / len(confs) if confs else None
        cues.append((text, timed[lo][1], timed[hi][2], conf))
    return cues


def _group_words_into_cues_dp(words, gap_ms=_CUE_GAP_MS, target_ms=_CUE_TARGET_MS,
                              target_chars=_CUE_TARGET_CHARS,
                              min_chars=_CUE_SPACE_MIN_CHARS, min_ms=_CUE_SPACE_MIN_MS,
                              lexicon=None):
    """Cost-minimising cue split (HANDOFF_CEILING_BREAK §5): a classic
    subtitle line-breaking DP over pythainlp's real word boundaries, replacing
    the greedy fill's "close the instant the character budget is hit,
    wherever that lands" rule (measured F1-neutral: `_group_words_into_cues_greedy`'s
    docstring / config.yaml's cue_space_min_* comment).

    Candidate breaks are every inter-atom boundary — `words` is glued into
    break-atoms first (HANDOFF_THAI_BREAK_ATOMS.md: STYLE_GUIDE §7's
    unsplittable units, e.g. mai yamok orphaning, a numeral split from its
    classifier, are unrepresentable once glued, not excluded per-candidate).
    Sentence boundaries (crfcut) and real silence gaps (>= gap_ms) stay hard
    splits — same "a cue must never cross either" invariant as the greedy
    path — dividing the atom stream into independent runs; within each run,
    DP picks the break set minimising deviation from target_chars/target_ms,
    penalising overflow past target_ms and cues under min_chars/min_ms (a
    "runt"), and discounting any point Whisper itself emitted a space.

    Returns list of (text, start_ms, end_ms, confidence), same contract as
    `_group_words_into_cues_greedy`.
    """
    from cutdeck.words import timed_tokens
    from transcribe.thai.atoms import default_lexicon, glue_atoms, snap_boundary_offsets

    full_text, raw_timed = timed_tokens(words)
    if not full_text:
        return []
    timed = glue_atoms(raw_timed, lexicon or default_lexicon({}))

    boundary_offsets = snap_boundary_offsets(_sentence_boundary_offsets(full_text), timed)
    real_idx = [k for k, tok in enumerate(timed) if tok[0].strip()]
    if not real_idx:
        return []

    # Hard split points: local index p (0..len(real_idx)) BEFORE which a cue
    # must start fresh, mirroring the greedy path's sentence/gap forcing.
    hard_splits = {0, len(real_idx)}
    b_idx = 0
    for p in range(1, len(real_idx)):
        k = real_idx[p]
        char_pos = timed[k][4]
        crossed = False
        while b_idx < len(boundary_offsets) and char_pos >= boundary_offsets[b_idx]:
            crossed = True
            b_idx += 1
        if crossed:
            hard_splits.add(p)
            continue
        prev_k = real_idx[p - 1]
        if timed[k][1] - timed[prev_k][2] >= gap_ms:
            hard_splits.add(p)
    hard_splits = sorted(hard_splits)

    cues: list[tuple[str, int, int, float | None]] = []
    for seg_start, seg_end in zip(hard_splits, hard_splits[1:]):
        cues.extend(_dp_split_segment(timed, real_idx, seg_start, seg_end,
                                       target_ms, target_chars, min_chars, min_ms))
    return cues


@register("faster_whisper")
class FasterWhisperEngine(Engine):
    """Thai-specialist Whisper via CTranslate2."""

    prefers_whole_file = True

    def __init__(self, model_id: str = _DEFAULT_MODEL, device: str = "cuda",
                 compute_type: str | None = None, beam_size: int = 5,
                 cue_gap_ms: int = _CUE_GAP_MS, cue_max_ms: int = _CUE_TARGET_MS,
                 cue_target_chars: int = _CUE_TARGET_CHARS,
                 cue_space_min_chars: int = _CUE_SPACE_MIN_CHARS,
                 cue_space_min_ms: int = _CUE_SPACE_MIN_MS,
                 cue_split_algorithm: str = _CUE_SPLIT_ALGORITHM,
                 bias_prompt_budget: int = 200, batch_size: int = 8,
                 vad_threshold: float = 0.35, vad_min_silence_ms: int = 500,
                 config: dict | None = None):
        self._model_id = model_id
        self._device = device
        # compute_type override lets an 8GB card fall back to int8_float16 if a
        # large model OOMs at float16. None → pick a sane default per device.
        self._compute_type = compute_type
        self._beam_size = beam_size
        self._cue_gap_ms = cue_gap_ms
        self._cue_space_min_chars = cue_space_min_chars
        self._cue_space_min_ms = cue_space_min_ms
        self._cue_max_ms = cue_max_ms
        self._cue_target_chars = cue_target_chars
        self._cue_split_algorithm = cue_split_algorithm
        self._bias_prompt_budget = bias_prompt_budget
        self._batch_size = batch_size
        # HANDOFF_THAI_BREAK_ATOMS.md: the break-atom lexicon consumed by cue
        # splitting (both algorithms). `config` is the full pipeline config
        # (not the engines.faster_whisper sub-block) so `thai_atoms` and
        # `normalization.exception_lexicon` are both visible — built once
        # here, pure/cheap, no model/GPU involved.
        from transcribe.thai.atoms import default_lexicon
        self._lexicon = default_lexicon(config)
        # This is a whole-file engine (prefers_whole_file=True), so ingest.py's VAD
        # never runs on this audio — we run our own Silero VAD pass in
        # _transcribe_batched (via _vad_speech_spans) using these thresholds, instead
        # of letting faster-whisper fall back to its defaults (threshold=0.5,
        # min_silence_duration_ms=2000), which clip soft Thai sentence-final
        # particles (ครับ/ค่ะ) exactly like ingest.vad_threshold's docstring warns
        # about. Defaulting these to match config.yaml's tuned ingest values keeps
        # both VAD paths consistent.
        self._vad_threshold = vad_threshold
        self._vad_min_silence_ms = vad_min_silence_ms
        self._model = None
        self._pipeline = None
        self._pre_load_path: str | None = None

    def load(self) -> None:
        # Restored in unload() — see _register_cuda_dll_dirs's docstring for
        # why this PATH mutation must not outlive this engine's residency.
        self._pre_load_path = _register_cuda_dll_dirs()
        from faster_whisper import WhisperModel, BatchedInferencePipeline

        compute_type = self._compute_type or ("float16" if self._device != "cpu" else "int8")
        logger.info("Loading FasterWhisper: %s (%s)", self._model_id, compute_type)
        self._model = WhisperModel(self._model_id, device=self._device, compute_type=compute_type)
        # BatchedInferencePipeline VAD-segments the track and decodes voiced regions
        # as parallel batches (WhisperX-style) — ~3× the sequential 30 s-window path
        # on the 3070 (3.1). self._model is kept for tokenizer access + unload.
        self._pipeline = BatchedInferencePipeline(model=self._model)
        logger.info("FasterWhisper (batched) loaded on %s", self._device)

    def _ct2_token_counter(self):
        """CT2's own tokenizer counts prompt tokens (Thai is token-dense; a Latin
        heuristic under-counts). Falls back to inject._approx_tokens if the
        installed faster-whisper doesn't expose hf_tokenizer."""
        tok = getattr(self._model, "hf_tokenizer", None)
        if tok is None:
            return None
        try:
            return lambda s: len(tok.encode(s).ids)
        except Exception:
            return None

    def _build_bias_prompt(self, inp: EngineInput) -> str:
        weights = inp.bias_weights or {}
        terms = [BiasTerm(t, weight=float(weights.get(t, 1.0))) for t in inp.bias_terms]
        return build_prompt(
            terms,
            budget_tokens=self._bias_prompt_budget,
            count_tokens=self._ct2_token_counter(),  # None → inject's approx fallback
        )

    def _load_array(self, inp: EngineInput):
        if inp.audio is not None:
            return inp.audio
        import librosa
        audio, _ = librosa.load(inp.audio_path, sr=16000, mono=True)
        return audio

    def _decode(self, audio_arr, clip_timestamps, vad_filter, common_kwargs, bs):
        """One BatchedInferencePipeline.transcribe call, halving batch_size on CUDA
        OOM. The batched API is a generator that runs inference lazily, so we
        materialize it inside the try — that's where an OOM actually surfaces.
        Mirrors _batch.py's OOM-halving philosophy without reusing it (that path
        is HF-pipeline-specific). Returns (segments, batch_size_used) so the
        caller's next call starts from whatever size succeeded."""
        import torch

        while True:
            try:
                segments, _info = self._pipeline.transcribe(
                    audio_arr,
                    vad_filter=vad_filter,
                    clip_timestamps=clip_timestamps,
                    batch_size=bs,
                    **common_kwargs,
                )
                return list(segments), bs  # materialize here so OOM lands in this try
            except Exception as e:  # noqa: BLE001 — narrowed by _is_cuda_oom
                if _is_cuda_oom(e) and bs > 1:
                    bs = max(1, bs // 2)
                    logger.warning("CUDA OOM in batched decode — retrying at batch_size=%d", bs)
                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                    continue
                raise

    @staticmethod
    def _words_of(segments) -> list[RecognizedToken]:
        out = []
        for seg in segments:
            for w in (seg.words or []):
                if w.word.strip():  # keep w.word verbatim (its leading space marks the word boundary)
                    out.append(RecognizedToken(
                        text=w.word, start_ms=int(w.start * 1000), end_ms=int(w.end * 1000),
                        confidence=w.probability, script=detect_script(w.word),
                    ))
        return out

    @staticmethod
    def _find_safe_cut(tokens_before, anchor_ms, lookback_ms=_TRUNCATION_LOOKBACK_MS):
        """Index of the token after which to cut, chosen as the largest
        inter-token gap within lookback_ms of anchor_ms — an actual acoustic
        pause Whisper's own timings already show, not an arbitrary time
        offset. A fixed offset back from the suspicious word can land
        mid-syllable regardless of how big it is (Thai subword pieces don't
        align to word boundaries), which is what caused earlier attempts at
        this fix to reproduce a stray syllable on both sides of the cut.
        Returns None if there aren't at least two tokens within range to
        compare (nothing to cut between)."""
        in_range = [i for i, t in enumerate(tokens_before) if anchor_ms - t.end_ms <= lookback_ms]
        if len(in_range) < 2:
            return None
        best_i, best_gap = None, -1
        for i in range(in_range[0], len(tokens_before) - 1):
            gap = tokens_before[i + 1].start_ms - tokens_before[i].end_ms
            if gap > best_gap:
                best_i, best_gap = i, gap
        return best_i

    def _recover_truncated_tail(self, tokens, sub_audio, common, bs):
        """Detect and recover content dropped by an early-EOS decode within one
        long-span window (see _TRUNCATION_TAIL_MS above for the failure mode,
        and its 2026-08-10 update for why this no longer requires the
        suspicious word to reach the window's own end). One-shot: redecodes
        standalone from the nearest safe cut point (see _find_safe_cut) to the
        window's end (a much shorter, easier decode) and concatenates — no
        overlap-and-dedup splice, since Thai's lack of clean word boundaries
        makes stitch.py's exact-text dedup miss the resulting near-duplicates
        (verified empirically while building this: a fixed-offset cut
        reproduced a stray syllable on both sides no matter how the offset
        was tuned). No recursion — if the redecode hits the same issue, its
        result is kept as-is."""
        if not tokens:
            return tokens, bs
        last = tokens[-1]
        dur = last.end_ms - last.start_ms
        if dur < _TRUNCATION_TAIL_MS:
            return tokens, bs

        cut_i = self._find_safe_cut(tokens[:-1], last.start_ms)
        if cut_i is None:
            return tokens, bs
        kept = tokens[:cut_i + 1]
        tail_start_ms = tokens[cut_i + 1].start_ms
        tail_audio = sub_audio[int(tail_start_ms / 1000 * _SR):]
        if len(tail_audio) < _SR * 0.5:
            return tokens, bs

        segments, bs = self._decode(tail_audio, None, False, common, bs)
        tail_tokens = self._words_of(segments)
        if not tail_tokens:
            return tokens, bs
        for t in tail_tokens:
            t.start_ms += tail_start_ms
            t.end_ms += tail_start_ms

        merged = kept + tail_tokens
        logger.info("Recovered truncated tail: suspect word spanned %d-%dms, "
                    "redecoded from %.2fs -> %d token(s)",
                    last.start_ms, last.end_ms, tail_start_ms / 1000, len(tail_tokens))
        return merged, bs

    def _transcribe_batched(self, audio, language_hint, initial_prompt,
                             temperature=None, beam_size=None) -> list[tuple[str, int, int, float | None]]:
        """Decode the whole file, splitting+stitching any pause-free run too long
        for Whisper's encoder window (see _LONG_SPAN_SAFE_S). word_timestamps +
        the anti-hallucination knobs are all supported by the batched signature
        (verified against fw 1.2.x).

        temperature: None (default) omits the key entirely, so faster-whisper
        falls through to its own cascading fallback list — production
        behaviour, byte-identical to before this param existed. A scalar
        pins decode to that single temperature.

        IMPORTANT (found probing HANDOFF_ONE_ENGINE §6 Phase D, 2026-08-05):
        `temperature` alone is a no-op through this batched path when beam_size
        stays at its production value. faster-whisper's
        BatchedInferencePipeline.generate_segment_batched always calls
        ctranslate2's Whisper.generate(beam_size=options.beam_size, ...) — beam
        search is deterministic search, not sampling, and CTranslate2's
        sampling_temperature has no effect while beam_size>1 (verified against
        installed faster-whisper 1.2.1 source: transcribe.py's
        generate_segment_batched never reads options.best_of and always passes
        the fixed beam_size). A temperature override only produces a genuinely
        different decode when paired with beam_size=1 (switches CTranslate2
        into sampling mode). See TODO_LEDGER.md "HANDOFF_ONE_ENGINE Phase D".

        beam_size: None (default) uses self._beam_size (production, 5). An
        override lets a self-ensemble second hypothesis decode at beam_size=1
        (+ temperature>0) to get real sampling diversity from the same
        residency, without touching the primary hypothesis's beam width.
        """
        from transcribe.pipeline import stitch

        common = dict(
            language=language_hint or "th",
            task="transcribe",
            initial_prompt=initial_prompt,
            beam_size=beam_size if beam_size is not None else self._beam_size,
            word_timestamps=True,
            condition_on_previous_text=False,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
        )
        if temperature is not None:
            common["temperature"] = temperature
        bs = self._batch_size
        words: list[tuple[str, int, int, float | None]] = []

        spans = _vad_speech_spans(audio, self._vad_threshold, self._vad_min_silence_ms)
        spans = _merge_contiguous_spans(spans)
        normal = [(s, e) for s, e in spans if e - s <= _LONG_SPAN_SAFE_S]
        long_spans = [(s, e) for s, e in spans if e - s > _LONG_SPAN_SAFE_S]

        if normal:
            # One batched call for every normal-length span (own VAD spans, already
            # each under the encoder cap, so no arbitrary internal re-split happens).
            clip = [{"start": s, "end": e} for s, e in normal]
            segments, bs = self._decode(audio, clip, False, common, bs)
            for tok in self._words_of(segments):
                words.append((tok.text, tok.start_ms, tok.end_ms, tok.confidence))
        elif not long_spans:
            # No speech spans detected at all (rare) — fall back to faster-whisper's
            # own automatic VAD/whole-file path rather than emitting nothing.
            segments, bs = self._decode(audio, None, True, common, bs)
            for tok in self._words_of(segments):
                words.append((tok.text, tok.start_ms, tok.end_ms, tok.confidence))

        for span_start, span_end in long_spans:
            chunk_tokens = []
            for win_start, win_end in _split_long_span(span_start, span_end):
                sub_audio = audio[int(win_start * _SR):int(win_end * _SR)]
                segments, bs = self._decode(sub_audio, None, False, common, bs)
                win_tokens = self._words_of(segments)
                win_tokens, bs = self._recover_truncated_tail(win_tokens, sub_audio, common, bs)
                for t in win_tokens:  # offset local → global
                    t.start_ms += int(win_start * 1000)
                    t.end_ms += int(win_start * 1000)
                chunk_tokens.append(stitch.ChunkTokens(
                    win_tokens, int(win_start * 1000), int(win_end * 1000)))
            logger.info("Long pause-free span %.1fs-%.1fs decoded as %d overlapping window(s)",
                        span_start, span_end, len(chunk_tokens))
            for tok in stitch.stitch(chunk_tokens,
                                     seam_window_ms=int(_LONG_SPAN_OVERLAP_S * 1000)):
                words.append((tok.text, tok.start_ms, tok.end_ms, tok.confidence))

        words.sort(key=lambda w: w[1])
        return words

    def transcribe(self, inp: EngineInput, temperature: float | list[float] | None = None,
                    beam_size: int | None = None) -> EngineResult:
        """temperature/beam_size: optional decode overrides — None preserves the
        exact production defaults. Not part of the abstract Engine.transcribe(inp)
        contract; existing callers (transcribe_batch, other engines) are
        unaffected since both are keyword-only with no-op defaults. See
        HANDOFF_ONE_ENGINE §6 (Phase D) and _transcribe_batched's docstring
        (temperature alone is a no-op at beam_size>1 — pair it with beam_size=1
        for real sampling diversity): this lets the pipeline call the same
        loaded residency twice at different decode settings for a
        self-ensemble N-best pair, with zero second model load."""
        assert self._model is not None, "load() must be called first"
        audio = self._load_array(inp)

        # bias terms ride in as initial_prompt (CT2's native biasing channel).
        # GAP-5 / 5.1: budget-aware packing, ranked by learned weight (not insertion
        # order), counted with CT2's own tokenizer so Thai token density is honoured.
        initial_prompt = self._build_bias_prompt(inp) if inp.bias_terms else None

        words = self._transcribe_batched(audio, inp.language_hint, initial_prompt,
                                          temperature=temperature, beam_size=beam_size)

        tokens = [
            RecognizedToken(
                text=text, start_ms=start, end_ms=end,
                confidence=conf, script=detect_script(text),
            )
            for text, start, end, conf in _group_words_into_cues(
                words, gap_ms=self._cue_gap_ms, target_ms=self._cue_max_ms,
                target_chars=self._cue_target_chars,
                space_min_chars=self._cue_space_min_chars,
                space_min_ms=self._cue_space_min_ms,
                algorithm=self._cue_split_algorithm,
                lexicon=self._lexicon)
        ]

        return EngineResult(
            tokens=tokens,
            engine_name="faster_whisper",
            timestamps_final=True,  # phrase cues are final; skip re-align
            # 5.4: keep the raw per-word list. Tokens persisted to the DB are phrase
            # cues; word granularity is re-derived on demand from here (CutDeck Phase
            # 5 filler excision needs word-level cuts inside a cue).
            raw={"words": [{"text": t, "start_ms": s, "end_ms": e, "confidence": c} for t, s, e, c in words]},
        )

    def unload(self) -> None:
        if self._pipeline is not None:
            del self._pipeline
            self._pipeline = None
        if self._model is not None:
            del self._model
            self._model = None
        # Undo _register_cuda_dll_dirs's PATH prepend now that this engine no
        # longer needs it — an engine loaded afterward in this process (e.g. a
        # NeMo-based Engine B) must not inherit a CUDA-12 cudnn64_9.dll ahead
        # of its own on PATH. See that function's docstring for the crash this
        # caused before the fix (CUDNN_STATUS_SUBLIBRARY_VERSION_MISMATCH).
        if self._pre_load_path is not None:
            os.environ["PATH"] = self._pre_load_path
            self._pre_load_path = None
        gc.collect()
        logger.info("FasterWhisper unloaded, VRAM freed")
