"""transcribe/thai/atoms.py — HANDOFF_THAI_BREAK_ATOMS.md Phase 1.

Thai has no orthographic word boundaries, so a cue splitter working directly
off pythainlp's word-tokenized output can land a break inside a bound
morphological unit (mai yamok's ๆ, a reciprocal particle like กัน, a
classifier+demonstrative pair) — exactly the incident this module exists to
make structurally impossible. The pre-2026-08-06 fix checked break-legality
at every break decision point (a "veto function per call site" design —
brittle, easy to forget on a new break path, and exactly what caused the
incident: the space-break path had vetoes, the length-forced path didn't).

`glue_atoms()` inverts this: merge bound tokens into a single TimedToken
*before* any splitter runs. A splitter that only ever sees atoms can close a
cue anywhere it likes and remain legal by construction — the knowledge lives
in one declarative `BreakLexicon` instead of scattered veto calls. Pure
functions, no model imports, no GPU — cutdeck/words.py::timed_tokens() does
the actual pythainlp tokenization; this module only re-groups its output.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from cutdeck.words import TimedToken

# STYLE_GUIDE §7: a classifier immediately followed by a demonstrative
# (คน + นั้น = "that NOUN") functions as one atomic unit that also
# re-specifies the noun immediately before it in spoken Thai — pythainlp
# tokenizes the classifier and demonstrative as two separate tokens. The
# original five (คน อัน ตัว ที่ สิ่ง) matched the pre-atoms veto exactly;
# HANDOFF_THAI_BREAK_ATOMS.md §4 item 2 grows the set toward the common
# spoken-Thai classifiers named in the handoff (a hand list beats an
# unshipped pythainlp-corpus-derived one — see the handoff's own Phase 4 note).
_CLASSIFIERS = frozenset({
    "คน", "อัน", "ตัว", "ที่", "สิ่ง",
    "เรื่อง", "แห่ง", "ลูก", "ใบ", "เล่ม", "คัน", "หลัง", "เครื่อง",
    "ชิ้น", "ชุด", "คู่", "ครั้ง", "ที", "รอบ",
})

# Written-register demonstratives (นั้น นี้ โน้น) plus HANDOFF §4 item 1's
# spoken/deictic forms (นี่ นั่น โน่น นู่น นู้น) — this corpus is creator
# speech, and the deictic forms are the ones that actually occur in it.
_DEMONSTRATIVES = frozenset({"นั้น", "นี้", "โน้น", "นี่", "นั่น", "โน่น", "นู่น", "นู้น"})

# HANDOFF §4 item 1: คนนึง/คนหนึ่ง (classifier + "one") is the same atomic
# shape as classifier+demonstrative — pythainlp splits คน|นึง / คน|หนึ่ง, but
# the pair means "a/one NOUN" and re-specifies the preceding noun exactly
# like คนนั้น does. STYLE_GUIDE §8 already keeps both the colloquial (นึง) and
# formal (หนึ่ง) register verbatim on the text side; gluing here only refuses
# to split whichever one was actually said, it doesn't pick between them.
_NUMERAL_ONE_FORMS = frozenset({"นึง", "หนึ่ง"})

_PAIR_RIGHT = _DEMONSTRATIVES | _NUMERAL_ONE_FORMS
_DEFAULT_PAIRS = frozenset((c, d) for c in _CLASSIFIERS for d in _PAIR_RIGHT)

# HANDOFF §4 item 3: utterance-final/polite particles are never sentence-
# initial in Thai — stranded at a cue's start they read exactly as broken as
# a stranded กัน did. Highest homograph risk of the Phase 2 batches (e.g.
# เลย is also "at all"/"past"/a place name) — accepted per §2.4: an
# over-glue moves a break a few characters earlier (cosmetic), an under-glue
# strands the particle (the exact defect the user hand-fixes in Premiere).
_FINAL_PARTICLES = frozenset({
    "นะ", "ครับ", "ค่ะ", "คะ", "สิ", "เลย", "ล่ะ", "แหละ", "หรอก", "เถอะ",
    "จ้ะ", "อ่ะ", "มั้ย", "ไหม", "เหรอ", "หรอ", "ป่ะ",
})

RULE_MAI_YAMOK = "mai_yamok"
RULE_RECIPROCAL_PARTICLE = "reciprocal_particle"
RULE_NUMERAL_UNIT = "numeral_unit"
RULE_CLASSIFIER_DEMONSTRATIVE = "classifier_demonstrative"
RULE_FINAL_PARTICLE = "final_particle"


@dataclass(frozen=True)
class BreakLexicon:
    """Declarative break-legality knowledge — the single source `glue_atoms()`
    (and, per HANDOFF_THAI_BREAK_ATOMS.md §5, the future harness cue-legality
    lint) both consult, so the lint and the splitter can never drift apart
    (same law as `db/store.py` owning SQL). Data, not code: growing the
    lexicon (Phase 2) never means adding a new call site.

    bind_left: a token whose stripped text is in this set glues to the atom
        BEFORE it UNCONDITIONALLY (mai yamok's ๆ, final particles).
    bind_right_digit: a token ending in a digit glues to whatever follows it
        (its unit/classifier — "100 บาท", "3 คน").
    pair_bind_left: (classifier, demonstrative-or-"one") pairs — glue the two
        together AND glue the result to the token immediately before them
        (the noun being re-specified). "Demonstrative-or-one" because
        classifier+นึง/หนึ่ง ("a/one NOUN") is the same atomic shape as
        classifier+demonstrative (HANDOFF §4 item 1) and uses this same field.
    unsplittable_terms: multi-token spans that must come out as one atom —
        seeded from config.yaml's normalization.exception_lexicon (STYLE_GUIDE
        §6: brands, COVID-19, mixed-script proper nouns).
    pos_conditioned_bind_left: like bind_left, but the glue only fires when
        the nearest preceding real token is POS-tagged as a verb (HANDOFF §6
        Phase 4 probe — กัน is also "to block" outside the reciprocal sense;
        gluing it unconditionally, as bind_left does, over-glues that
        homograph. Empty by default: this is an opt-in probe, not a default
        behaviour change — see `thai_atoms.pos_condition_reciprocal`).
    """

    bind_left: frozenset[str] = field(default_factory=frozenset)
    bind_right_digit: bool = False
    pair_bind_left: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    unsplittable_terms: frozenset[str] = field(default_factory=frozenset)
    pos_conditioned_bind_left: frozenset[str] = field(default_factory=frozenset)


def default_lexicon(config: dict | None = None) -> BreakLexicon:
    """STYLE_GUIDE §7's rule *categories* — Phase 1 ported the original four
    from the pre-2026-08-06 veto functions; HANDOFF_THAI_BREAK_ATOMS.md §4
    grows their coverage in batches (each batch stays gated on its own toggle
    name, it just widens what that toggle's set contains) and item 3 added a
    fifth category (`final_particle`) — plus the config extension points
    HANDOFF_THAI_BREAK_ATOMS.md §2.2 specifies: a `thai_atoms:` block with
    `extra_bind_left`, `extra_pairs`, `disable: [rule-name]`, so the lexicon
    grows from observed Premiere pain without a code change.
    `unsplittable_terms` is seeded from `normalization.exception_lexicon`
    (STYLE_GUIDE §6), not from `thai_atoms` — one lexicon, not a second list
    to keep in sync.
    """
    config = config or {}
    atoms_cfg = config.get("thai_atoms", {}) or {}
    disabled = set(atoms_cfg.get("disable", []) or [])
    # HANDOFF §6 Phase 4 probe, opt-in and off by default: instead of gluing
    # กัน unconditionally, only glue it after a POS-tagged verb (see
    # `pos_conditioned_bind_left`'s docstring for why — the reciprocal sense
    # is not the only sense of กัน).
    pos_condition_reciprocal = bool(atoms_cfg.get("pos_condition_reciprocal", False))

    bind_left = set()
    if RULE_MAI_YAMOK not in disabled:
        bind_left.add("ๆ")
    if RULE_RECIPROCAL_PARTICLE not in disabled and not pos_condition_reciprocal:
        bind_left.add("กัน")
    if RULE_FINAL_PARTICLE not in disabled:
        bind_left.update(_FINAL_PARTICLES)
    bind_left.update(atoms_cfg.get("extra_bind_left", []) or [])

    pos_conditioned_bind_left = set()
    if RULE_RECIPROCAL_PARTICLE not in disabled and pos_condition_reciprocal:
        pos_conditioned_bind_left.add("กัน")

    pair_bind_left = set()
    if RULE_CLASSIFIER_DEMONSTRATIVE not in disabled:
        pair_bind_left.update(_DEFAULT_PAIRS)
    pair_bind_left.update(tuple(p) for p in (atoms_cfg.get("extra_pairs", []) or []))

    unsplittable_terms = config.get("normalization", {}).get("exception_lexicon", []) or []

    return BreakLexicon(
        bind_left=frozenset(bind_left),
        bind_right_digit=RULE_NUMERAL_UNIT not in disabled,
        pair_bind_left=frozenset(pair_bind_left),
        unsplittable_terms=frozenset(unsplittable_terms),
        pos_conditioned_bind_left=frozenset(pos_conditioned_bind_left),
    )


def pos_tag_texts(tokens: list[str]) -> list[str]:
    """Thin wrapper around `pythainlp.tag.pos_tag` (perceptron, ORCHID tagset)
    so both `glue_atoms` and `transcribe/thai/lint.py`'s particle_initial
    check make the exact same tag-classification call — one knowledge source
    for "does this tag count as a verb", same law `BreakLexicon` follows for
    the glue rules themselves. Lazy import: a model-file load, only paid when
    a pos-conditioned rule is actually configured/checked (HANDOFF §6: "cost
    it — POS tagging runs per file on CPU").
    """
    if not tokens:
        return []
    from pythainlp.tag import pos_tag

    return [tag for _, tag in pos_tag(tokens)]


def is_verb_tag(tag: str) -> bool:
    """ORCHID verb tags are VACT/VSTA/VATT/VACT-prefixed — HANDOFF §6's
    probe claim ("กัน binds only after a VERB-tagged token") is unproven on
    unpunctuated ASR output until a harness run says otherwise; this is the
    single place that claim is encoded so the probe can be judged, tuned, or
    killed in one spot."""
    return tag.startswith("V")


def _merge_range(glue_prev: list[bool], a: int, b: int) -> None:
    """Mark indices (a, b] as glued to their predecessor — merges tokens
    a..b (inclusive) into one atom."""
    for j in range(a + 1, b + 1):
        glue_prev[j] = True


def _glue_left(glue_prev: list[bool], stripped: list[str], i: int) -> None:
    """Merge token i into the atom ending at i-1, absorbing a run of
    whitespace-only tokens immediately before it too — Whisper sometimes
    writes mai yamok as a separate ' ๆ' piece, tokenized as its own
    whitespace token followed by 'ๆ'; the space must land inside the glued
    atom, not survive as a break candidate of its own."""
    if i <= 0 or glue_prev[i]:
        return
    glue_prev[i] = True
    if not stripped[i - 1]:
        _glue_left(glue_prev, stripped, i - 1)


def _merge_group(timed: list[TimedToken], indices: list[int]) -> TimedToken:
    if len(indices) == 1:
        return timed[indices[0]]
    text = "".join(timed[i][0] for i in indices)  # verbatim — atoms never change text
    start_ms = timed[indices[0]][1]
    end_ms = timed[indices[-1]][2]
    confs = [timed[i][3] for i in indices if timed[i][3] is not None]
    conf = sum(confs) / len(confs) if confs else None
    char_pos = timed[indices[0]][4]
    return (text, start_ms, end_ms, conf, char_pos)


def glue_atoms(timed: list[TimedToken], lexicon: BreakLexicon) -> list[TimedToken]:
    """Merge pythainlp tokens into break-atoms per `lexicon`. Same TimedToken
    shape as the input (text, start_ms, end_ms, confidence, char_pos) — an
    atom is just a token the splitters may not look inside. Whitespace
    tokens remain separate atoms except when a rule glues them into a merged
    pair. Grouping only: text is never normalized, expanded, or dropped.
    """
    n = len(timed)
    if n == 0:
        return []

    stripped = [t[0].strip() for t in timed]
    glue_prev = [False] * n

    # bind_left: token glues to the atom BEFORE it (ๆ, กัน, config extras).
    for i, s in enumerate(stripped):
        if s and s in lexicon.bind_left:
            _glue_left(glue_prev, stripped, i)

    # pos_conditioned_bind_left (HANDOFF §6 Phase 4 probe): same glue-left
    # shape as bind_left, but only when the nearest preceding REAL token's
    # POS tag is verb-like. Tags every real token in this segment once (not
    # pairwise) so the tagger sees full local context, not a 2-word window.
    if lexicon.pos_conditioned_bind_left:
        real_positions = [i for i, s in enumerate(stripped) if s]
        tags = pos_tag_texts([stripped[i] for i in real_positions])
        for k, i in enumerate(real_positions):
            if k == 0:
                continue
            if stripped[i] in lexicon.pos_conditioned_bind_left and is_verb_tag(tags[k - 1]):
                _glue_left(glue_prev, stripped, i)

    # bind_right_digit: a digit-final real token glues to whatever follows
    # it (its unit/classifier), absorbing any whitespace between them.
    if lexicon.bind_right_digit:
        for i, s in enumerate(stripped):
            if s and s[-1].isdigit():
                j = i + 1
                while j < n and not stripped[j]:
                    _glue_left(glue_prev, stripped, j)
                    j += 1
                if j < n:
                    _glue_left(glue_prev, stripped, j)

    # pair_bind_left: (classifier, demonstrative) glue together AND glue to
    # the immediately preceding real token (the noun being re-specified).
    if lexicon.pair_bind_left:
        real_idx = [i for i, s in enumerate(stripped) if s]
        for k in range(len(real_idx) - 1):
            c_i, d_i = real_idx[k], real_idx[k + 1]
            if (stripped[c_i], stripped[d_i]) in lexicon.pair_bind_left:
                _merge_range(glue_prev, c_i, d_i)
                if k > 0:
                    _merge_range(glue_prev, real_idx[k - 1], c_i)

    # unsplittable_terms: exact multi-token spans (STYLE_GUIDE §6 brands /
    # mixed-script terms, e.g. pythainlp splits "COVID-19" into "COVID-" +
    # "19") merge into one atom. Longest-first so a shorter term never
    # pre-empts a longer one that contains it.
    if lexicon.unsplittable_terms:
        full_text = "".join(t[0] for t in timed)
        starts = [t[4] for t in timed]
        ends = [t[4] + len(t[0]) for t in timed]
        for term in sorted(lexicon.unsplittable_terms, key=len, reverse=True):
            if not term:
                continue
            search_from = 0
            while True:
                idx = full_text.find(term, search_from)
                if idx == -1:
                    break
                span_end = idx + len(term)
                lo = bisect.bisect_right(starts, idx) - 1
                hi = bisect.bisect_right(starts, span_end - 1) - 1
                if 0 <= lo < hi < n and ends[lo] > idx:
                    _merge_range(glue_prev, lo, hi)
                search_from = span_end

    atoms: list[TimedToken] = []
    group: list[int] = [0]
    for i in range(1, n):
        if glue_prev[i]:
            group.append(i)
        else:
            atoms.append(_merge_group(timed, group))
            group = [i]
    atoms.append(_merge_group(timed, group))
    return atoms


def snap_boundary_offsets(offsets: list[int], timed: list[TimedToken]) -> list[int]:
    """HANDOFF_THAI_BREAK_ATOMS.md §2.3 item 1: a crfcut sentence-boundary
    offset landing *inside* an atom's char span moves to the atom's start —
    crfcut segments raw, unpunctuated ASR text and can't see atom-internal
    structure, so a 'boundary' inside a glued atom is crfcut being wrong, not
    a licence to split the atom. `timed` here is the post-`glue_atoms` atom
    list; `offsets` are char positions into the same `full_text` the atoms'
    char_pos values are relative to.
    """
    if not offsets or not timed:
        return list(offsets)
    starts = [t[4] for t in timed]
    ends = [t[4] + len(t[0]) for t in timed]
    snapped = []
    for off in offsets:
        moved = off
        i = bisect.bisect_right(starts, off) - 1
        if 0 <= i < len(timed) and starts[i] < off < ends[i]:
            moved = starts[i]
        snapped.append(moved)
    return snapped
