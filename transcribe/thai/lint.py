"""transcribe/thai/lint.py — HANDOFF_THAI_BREAK_ATOMS.md Phase 3.

The incident (see the handoff's §0) was discovered by the user, in Premiere,
after export — the harness had no eyes for "is this cue break legal" at all.
This module gives it those eyes: scan a transcript's cues (hypothesis OR
reference — both, separately, per §5) for breaks `BreakLexicon` says should
never happen, the same knowledge `glue_atoms()` already uses to prevent them
at construction time.

Reuses `BreakLexicon` rather than restating its rules — the lint and the
splitter must share one knowledge source or they will drift apart (the same
law `db/store.py` follows for SQL). Pure text scan: no model/pipeline access,
so it costs nothing beyond what the harness already computes per clip.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass

from transcribe.thai.atoms import BreakLexicon, is_verb_tag, pos_tag_texts


@dataclass(frozen=True)
class CueViolation:
    """index: the cue that OWNS the illegal edge (the earlier of the two cues
    a rule spans, for the pair/term rules — see each rule's docstring below).
    rule: one of the RULE_* constants. detail: the offending text, for the
    harness's per-clip print."""
    index: int
    rule: str
    detail: str


RULE_PARTICLE_INITIAL = "particle_initial"
RULE_DIGIT_FINAL = "digit_final"
RULE_CLASSIFIER_DEMONSTRATIVE_SPLIT = "classifier_demonstrative_split"
RULE_UNSPLITTABLE_TERM_SPLIT = "unsplittable_term_split"


def _cue_edge_tokens(text: str) -> tuple[str, str]:
    """(first, last) non-whitespace pythainlp token in one cue's text — "" for
    a cue with no real token (pure whitespace/punctuation). Same tokenizer
    `cutdeck/words.py::timed_tokens` uses, so a cue's "first/last word" here
    means the same thing it means to `glue_atoms`."""
    from pythainlp.tokenize import word_tokenize

    toks = [t for t in word_tokenize(text, keep_whitespace=False) if t.strip()]
    if not toks:
        return "", ""
    return toks[0], toks[-1]


def find_cue_legality_violations(
    cues: list[dict], lexicon: BreakLexicon
) -> list[CueViolation]:
    """Scan time-ordered cues (each a dict with a "text" key) for edges the
    lexicon says are illegal — the four checks HANDOFF_THAI_BREAK_ATOMS.md §5
    names:

    - `particle_initial`: a cue (other than the first) opens with `bind_left`
      material — it should have glued to the PREVIOUS cue's end instead of
      starting a new one. Also fires for `pos_conditioned_bind_left` material
      (HANDOFF §6 Phase 4 probe) when the previous cue's last token tags as a
      verb — the same classification `glue_atoms` uses, but over only the two
      adjacent tokens (not the full original segment `glue_atoms` saw), a
      known narrower-context limitation of a post-split, cue-text-only scan.
    - `digit_final`: a cue (other than the last) ends in a digit — its
      unit/classifier landed in the next cue instead of gluing to this one.
    - `classifier_demonstrative_split`: a cue ends in a classifier whose
      matching demonstrative/"one" form opens the very next cue.
    - `unsplittable_term_split`: an exception-lexicon term's character span
      crosses a cue boundary.

    A cue with no timing role in these checks (e.g. a lone punctuation cue)
    contributes "" edge tokens and never matches anything.
    """
    n = len(cues)
    if n == 0:
        return []

    edges = [_cue_edge_tokens(c.get("text", "") or "") for c in cues]
    violations: list[CueViolation] = []

    for i in range(n):
        first, last = edges[i]
        if i > 0 and first and first in lexicon.bind_left:
            violations.append(CueViolation(i, RULE_PARTICLE_INITIAL, first))
        elif i > 0 and first and first in lexicon.pos_conditioned_bind_left:
            prev_last = edges[i - 1][1]
            if prev_last:
                tags = pos_tag_texts([prev_last, first])
                if tags and is_verb_tag(tags[0]):
                    violations.append(CueViolation(i, RULE_PARTICLE_INITIAL, first))
        if lexicon.bind_right_digit and i < n - 1 and last and last[-1].isdigit():
            violations.append(CueViolation(i, RULE_DIGIT_FINAL, last))
        if i < n - 1 and lexicon.pair_bind_left:
            nxt_first = edges[i + 1][0]
            if last and nxt_first and (last, nxt_first) in lexicon.pair_bind_left:
                violations.append(
                    CueViolation(
                        i, RULE_CLASSIFIER_DEMONSTRATIVE_SPLIT, f"{last}|{nxt_first}"
                    )
                )

    if lexicon.unsplittable_terms and n > 1:
        cue_texts = [c.get("text", "") or "" for c in cues]
        full_text = "".join(cue_texts)
        cue_starts: list[int] = []
        pos = 0
        for t in cue_texts:
            cue_starts.append(pos)
            pos += len(t)
        for term in lexicon.unsplittable_terms:
            if not term:
                continue
            search_from = 0
            while True:
                idx = full_text.find(term, search_from)
                if idx == -1:
                    break
                span_end = idx + len(term)
                lo = bisect.bisect_right(cue_starts, idx) - 1
                hi = bisect.bisect_right(cue_starts, span_end - 1) - 1
                if 0 <= lo < hi < n:
                    violations.append(
                        CueViolation(lo, RULE_UNSPLITTABLE_TERM_SPLIT, term)
                    )
                search_from = span_end

    return violations
