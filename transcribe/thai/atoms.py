from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from transcribe.words import TimedToken

_CLASSIFIERS = frozenset({
    "คน", "อัน", "ตัว", "ที่", "สิ่ง",
    "เรื่อง", "แห่ง", "ลูก", "ใบ", "เล่ม", "คัน", "หลัง", "เครื่อง",
    "ชิ้น", "ชุด", "คู่", "ครั้ง", "ที", "รอบ",
})

_DEMONSTRATIVES = frozenset({"นั้น", "นี้", "โน้น", "นี่", "นั่น", "โน่น", "นู่น", "นู้น"})

_NUMERAL_ONE_FORMS = frozenset({"นึง", "หนึ่ง"})

_PAIR_RIGHT = _DEMONSTRATIVES | _NUMERAL_ONE_FORMS
_DEFAULT_PAIRS = frozenset((c, d) for c in _CLASSIFIERS for d in _PAIR_RIGHT)

_FINAL_PARTICLES = frozenset({
    "นะ", "ครับ", "ค่ะ", "คะ", "สิ", "เลย", "ล่ะ", "แหละ", "หรอก", "เถอะ",
    "จ้ะ", "อ่ะ", "มั้ย", "ไหม", "เหรอ", "หรอ", "ป่ะ",
})

TRAILING_PARTICLES = _FINAL_PARTICLES | frozenset({"เนี้ย", "เนี่ย", "น่ะ"})

LEADING_CONNECTIVES = frozenset({"แล้วก็"})

CLAUSE_CLOSERS = frozenset({"ครับ", "ค่ะ", "คะ"})

STRONG_OPENERS = frozenset({
    "แต่", "แต่ว่า", "ถ้า", "ถ้าเกิด", "ก็เลย", "ทำไม", "แล้วก็", "เพราะ", "เพราะว่า",
    "คือ", "พอ", "ซึ่ง", "หรือว่า", "ดังนั้น", "เพราะฉะนั้น",
})
WEAK_OPENERS = frozenset({
    "เขา", "เค้า", "หนู", "เรา", "มัน", "พี่", "ผม", "ฉัน", "คุณ", "แล้ว", "ก็",
})
NON_OPENERS = frozenset({
    "ให้", "ของ", "อะไร", "เป็น", "ได้", "ว่า", "ไป", "มา", "กับ", "กว่า", "ที่", "ที่จะ",
    "อยู่", "ด้วย", "แล้ว ๆ",
})
DANGLING_ENDS = STRONG_OPENERS | frozenset({
    "ก็", "ยัง", "อาจจะ", "ที่จะ", "ที่", "กับ", "ว่า", "จะ", "ไม่", "ของ", "ให้", "ต้อง",
    "อยาก", "แล้ว", "เป็น", "ใน", "และ", "หรือ", "โดย", "เพื่อ", "กำลัง", "ไม่ได้",
})

RULE_MAI_YAMOK = "mai_yamok"
RULE_RECIPROCAL_PARTICLE = "reciprocal_particle"
RULE_NUMERAL_UNIT = "numeral_unit"
RULE_CLASSIFIER_DEMONSTRATIVE = "classifier_demonstrative"
RULE_FINAL_PARTICLE = "final_particle"


@dataclass(frozen=True)
class BreakLexicon:
    """
    bind_left: a token whose stripped text is in this set glues to the atom
        BEFORE it UNCONDITIONALLY (mai yamok's ๆ, final particles).
    bind_right_digit: a token ending in a digit glues to whatever follows it
        (its unit/classifier — "100 บาท", "3 คน").
    pair_bind_left: (classifier, demonstrative-or-"one") pairs — glue the two
        together AND glue the result to the token immediately before them
        (the noun being re-specified).
    unsplittable_terms: multi-token spans that must come out as one atom.
    pos_conditioned_bind_left: like bind_left, but the glue only fires when
        the nearest preceding real token is POS-tagged as a verb.
    """

    bind_left: frozenset[str] = field(default_factory=frozenset)
    bind_right_digit: bool = False
    pair_bind_left: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    unsplittable_terms: frozenset[str] = field(default_factory=frozenset)
    pos_conditioned_bind_left: frozenset[str] = field(default_factory=frozenset)


def default_lexicon(config: dict | None = None) -> BreakLexicon:
    """STYLE_GUIDE §7's rule categories, extended by config: a `thai_atoms:` block
    with `extra_bind_left`, `extra_pairs` and `disable: [rule-name]`.
    `unsplittable_terms` is seeded from `normalization.exception_lexicon`.
    """
    config = config or {}
    atoms_cfg = config.get("thai_atoms", {}) or {}
    disabled = set(atoms_cfg.get("disable", []) or [])
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
    if not tokens:
        return []
    from pythainlp.tag import pos_tag

    return [tag for _, tag in pos_tag(tokens)]


def is_verb_tag(tag: str) -> bool:
    return tag.startswith("V")


def _merge_range(glue_prev: list[bool], a: int, b: int) -> None:
    for j in range(a + 1, b + 1):
        glue_prev[j] = True


def _glue_left(glue_prev: list[bool], stripped: list[str], i: int) -> None:
    if i <= 0 or glue_prev[i]:
        return
    glue_prev[i] = True
    if not stripped[i - 1]:
        _glue_left(glue_prev, stripped, i - 1)


def _merge_group(timed: list[TimedToken], indices: list[int]) -> TimedToken:
    if len(indices) == 1:
        return timed[indices[0]]
    text = "".join(timed[i][0] for i in indices)
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

    for i, s in enumerate(stripped):
        if s and s in lexicon.bind_left:
            _glue_left(glue_prev, stripped, i)

    if lexicon.pos_conditioned_bind_left:
        real_positions = [i for i, s in enumerate(stripped) if s]
        tags = pos_tag_texts([stripped[i] for i in real_positions])
        for k, i in enumerate(real_positions):
            if k == 0:
                continue
            if stripped[i] in lexicon.pos_conditioned_bind_left and is_verb_tag(tags[k - 1]):
                _glue_left(glue_prev, stripped, i)

    if lexicon.bind_right_digit:
        for i, s in enumerate(stripped):
            if s and s[-1].isdigit():
                j = i + 1
                while j < n and not stripped[j]:
                    _glue_left(glue_prev, stripped, j)
                    j += 1
                if j < n:
                    _glue_left(glue_prev, stripped, j)

    if lexicon.pair_bind_left:
        real_idx = [i for i, s in enumerate(stripped) if s]
        for k in range(len(real_idx) - 1):
            c_i, d_i = real_idx[k], real_idx[k + 1]
            if (stripped[c_i], stripped[d_i]) in lexicon.pair_bind_left:
                _merge_range(glue_prev, c_i, d_i)
                if k > 0:
                    _merge_range(glue_prev, real_idx[k - 1], c_i)

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
    """A crfcut sentence-boundary offset landing *inside* an atom's char span
    moves to the atom's start. `timed` here is the post-`glue_atoms` atom list;
    `offsets` are char positions into the same `full_text` the atoms' char_pos
    values are relative to.
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
