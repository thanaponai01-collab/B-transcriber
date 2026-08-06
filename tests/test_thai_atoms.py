"""transcribe/thai/atoms.py — HANDOFF_THAI_BREAK_ATOMS.md Phase 1.

Direct unit tests for the glue-atoms inversion (break-legality knowledge as
data, not veto-at-break-time checks), plus the property test that makes the
inversion real: no cue boundary, at any target_chars setting, on either
splitter algorithm, may ever fall strictly inside an atom's span. That
invariant was impossible to state cleanly against the old scattered vetoes —
it's the whole reason this module exists.

Run: python -m pytest tests/test_thai_atoms.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from cutdeck.words import timed_tokens, words_from_pieces
from transcribe.engines.faster_whisper import _group_words_into_cues
from transcribe.thai.atoms import BreakLexicon, default_lexicon, glue_atoms, snap_boundary_offsets


def _char_pieces(text: str, start: int = 0, step: int = 100):
    out, t = [], start
    for ch in text:
        out.append((ch, t, t + step, 0.9))
        t += step
    return out


def _atoms_for(text: str, lexicon=None, start=0, step=100):
    lexicon = lexicon or default_lexicon({})
    _, timed = timed_tokens(_char_pieces(text, start=start, step=step))
    return glue_atoms(timed, lexicon)


# ── default_lexicon ─────────────────────────────────────────────────────────

def test_default_lexicon_seeds_exactly_the_four_ported_rules():
    lex = default_lexicon({})
    assert lex.bind_left == frozenset({"ๆ", "กัน"})
    assert lex.bind_right_digit is True
    assert ("คน", "นั้น") in lex.pair_bind_left
    assert ("ตัว", "นี้") in lex.pair_bind_left
    assert lex.unsplittable_terms == frozenset()


def test_default_lexicon_reads_exception_lexicon_as_unsplittable_terms():
    config = {"normalization": {"exception_lexicon": ["COVID-19", "iPhone"]}}
    lex = default_lexicon(config)
    assert lex.unsplittable_terms == frozenset({"COVID-19", "iPhone"})


def test_default_lexicon_disable_and_extra_bind_left():
    config = {"thai_atoms": {"disable": ["reciprocal_particle"], "extra_bind_left": ["นะ"]}}
    lex = default_lexicon(config)
    assert lex.bind_left == frozenset({"ๆ", "นะ"})  # กัน dropped, นะ added


def test_default_lexicon_disable_classifier_demonstrative_and_extra_pairs():
    config = {"thai_atoms": {"disable": ["classifier_demonstrative"],
                              "extra_pairs": [["เรื่อง", "นี้"]]}}
    lex = default_lexicon(config)
    assert lex.pair_bind_left == frozenset({("เรื่อง", "นี้")})


# ── glue_atoms: mai yamok ───────────────────────────────────────────────────

def test_mai_yamok_attached_no_space_glues_to_preceding_word():
    atoms = _atoms_for("เด็กๆน่ารัก")
    texts = [a[0] for a in atoms]
    assert "เด็กๆ" in texts
    assert not any(t.strip() == "ๆ" for t in texts), f"ๆ orphaned: {texts}"


def test_mai_yamok_with_leading_space_absorbs_the_space_into_the_atom():
    """Whisper writes mai yamok as a separate ' ๆ' piece — pythainlp can
    tokenize the space as its own whitespace token ahead of 'ๆ'
    (`เขาชอบเด็ก ๆ มาก` -> ['เขา','ชอบ','เด็ก',' ','ๆ',' ','มาก']); the space
    must land inside the glued atom, not survive as a standalone atom."""
    atoms = _atoms_for("เขาชอบเด็ก ๆ มาก")
    texts = [a[0] for a in atoms]
    assert "เด็ก ๆ" in texts, f"space not absorbed into the atom: {texts}"
    assert not any(t.strip() == "ๆ" for t in texts), f"ๆ orphaned: {texts}"


def test_mai_yamok_rule_can_be_disabled():
    lexicon = default_lexicon({"thai_atoms": {"disable": ["mai_yamok"]}})
    atoms = _atoms_for("เด็กๆน่ารัก", lexicon=lexicon)
    texts = [a[0] for a in atoms]
    assert "เด็ก" in texts and "ๆ" in texts, f"disabled rule still glued: {texts}"


# ── glue_atoms: reciprocal particle ─────────────────────────────────────────

def test_reciprocal_particle_glues_to_preceding_verb():
    atoms = _atoms_for("เราทะเลาะกันเมื่อวาน")
    texts = [a[0] for a in atoms]
    assert "ทะเลาะกัน" in texts, f"กัน not glued to its verb: {texts}"
    assert not any(t.strip() == "กัน" for t in texts), f"กัน orphaned: {texts}"


# ── glue_atoms: numeral + unit/classifier ───────────────────────────────────

def test_digit_final_token_glues_to_its_unit_across_whitespace():
    atoms = _atoms_for("ราคาทั้งหมดอยู่ที่ 100 บาทครับ")
    texts = [a[0] for a in atoms]
    assert "100 บาท" in texts, f"numeral split from its unit: {texts}"


def test_digit_final_token_glues_to_its_classifier_with_no_space():
    atoms = _atoms_for("มีแมว3ตัวที่บ้าน")
    texts = [a[0] for a in atoms]
    assert "3ตัว" in texts, f"numeral split from its classifier: {texts}"


def test_bind_right_digit_can_be_disabled():
    lexicon = default_lexicon({"thai_atoms": {"disable": ["numeral_unit"]}})
    atoms = _atoms_for("มีแมว3ตัวที่บ้าน", lexicon=lexicon)
    texts = [a[0] for a in atoms]
    assert "3" in texts, f"disabled rule still glued: {texts}"


# ── glue_atoms: classifier + demonstrative (+ preceding noun) ──────────────

def test_classifier_demonstrative_glues_to_each_other_and_the_preceding_noun():
    atoms = _atoms_for("เจอผู้หญิงคนนั้นเมื่อวาน")
    texts = [a[0] for a in atoms]
    assert "ผู้หญิงคนนั้น" in texts, f"pair not glued to its noun: {texts}"
    assert not any(t.strip() == "คน" for t in texts), f"classifier orphaned: {texts}"
    assert not any(t.strip() == "นั้น" for t in texts), f"demonstrative orphaned: {texts}"


def test_classifier_demonstrative_pair_alone_still_glues_with_no_preceding_token():
    """The pair must glue to itself even with nothing before it to extend to
    (matches the pre-atoms veto's 'inside the pair' branch, which never
    checked whether a preceding token existed)."""
    atoms = _atoms_for("คนนั้นสวยมาก")
    texts = [a[0] for a in atoms]
    assert "คนนั้น" in texts, f"pair not glued: {texts}"


# ── glue_atoms: HANDOFF §4 item 1 — spoken deictic forms ───────────────────

@pytest.mark.parametrize("deictic", ["นี่", "นั่น", "โน่น", "นู่น", "นู้น"])
def test_classifier_spoken_deictic_form_glues_same_as_written_demonstrative(deictic):
    """Spoken Thai (this corpus is creator speech) uses นี่/นั่น/โน่น/นู่น/นู้น
    far more than the written-register นี้/นั้น/โน้น the pre-Phase-2 lexicon
    only had — same atomic shape, same glue behaviour."""
    atoms = _atoms_for(f"เจอผู้หญิงคน{deictic}เมื่อวาน")
    texts = [a[0] for a in atoms]
    assert f"ผู้หญิงคน{deictic}" in texts, f"deictic pair not glued: {texts}"
    assert not any(t.strip() == "คน" for t in texts), f"classifier orphaned: {texts}"
    assert not any(t.strip() == deictic for t in texts), f"deictic orphaned: {texts}"


# ── glue_atoms: HANDOFF §4 item 1 — คนนึง / คนหนึ่ง (classifier + "one") ────

@pytest.mark.parametrize("one_form", ["นึง", "หนึ่ง"])
def test_classifier_plus_one_form_glues_to_preceding_noun(one_form):
    """คนนึง/คนหนึ่ง ('a/one NOUN') is the same atomic shape as
    classifier+demonstrative — STYLE_GUIDE §8 keeps both registers verbatim
    on the text side; this only tests that neither gets split at the cue
    level."""
    atoms = _atoms_for(f"เจอผู้หญิงคน{one_form}เมื่อวาน")
    texts = [a[0] for a in atoms]
    assert f"ผู้หญิงคน{one_form}" in texts, f"pair not glued to its noun: {texts}"
    assert not any(t.strip() == "คน" for t in texts), f"classifier orphaned: {texts}"
    assert not any(t.strip() == one_form for t in texts), f"'{one_form}' orphaned: {texts}"


# ── glue_atoms: unsplittable_terms (exception lexicon) ─────────────────────

def test_exception_lexicon_term_split_by_tokenizer_is_reglued():
    """pythainlp splits 'COVID-19' into 'COVID-' + '19' — the exact case this
    rule exists for (STYLE_GUIDE §6). numeral_unit disabled so this test
    isolates the unsplittable_terms rule alone from the (separately tested)
    digit-glue rule, which would otherwise also glue '19' to 'ครับ' and
    obscure which rule did the work."""
    lexicon = default_lexicon({"normalization": {"exception_lexicon": ["COVID-19"]},
                                "thai_atoms": {"disable": ["numeral_unit"]}})
    atoms = _atoms_for("เขาเป็นCOVID-19ครับ", lexicon=lexicon)
    texts = [a[0] for a in atoms]
    assert "COVID-19" in texts, f"exception term not reglued: {texts}"


def test_exception_lexicon_term_already_one_token_is_a_no_op():
    lexicon = default_lexicon({"normalization": {"exception_lexicon": ["iPhone"]}})
    atoms = _atoms_for("ผมใช้iPhoneอยู่", lexicon=lexicon)
    texts = [a[0] for a in atoms]
    assert "iPhone" in texts


def test_no_unsplittable_terms_configured_is_a_no_op():
    lexicon = default_lexicon({"thai_atoms": {"disable": ["numeral_unit"]}})
    atoms = _atoms_for("เขาเป็นCOVID-19ครับ", lexicon=lexicon)
    texts = [a[0] for a in atoms]
    assert "COVID-" in texts and "19" in texts  # left as pythainlp split it


def test_unsplittable_terms_and_digit_glue_combine_when_both_active():
    """Rule interaction, not a bug: bind_right_digit is a separate default
    rule (§7's numeral+unit protection) that also fires on '19' here — both
    rules just OR into the same glue_prev array, so the resulting atom can be
    bigger than the exception term alone. Over-gluing is the accepted safe
    direction (HANDOFF_THAI_BREAK_ATOMS.md §2.4)."""
    lexicon = default_lexicon({"normalization": {"exception_lexicon": ["COVID-19"]}})
    atoms = _atoms_for("เขาเป็นCOVID-19ครับ", lexicon=lexicon)
    texts = [a[0] for a in atoms]
    assert any("COVID-19" in t for t in texts), f"exception term not reglued: {texts}"


# ── merged-atom shape: timing / confidence / char_pos / verbatim text ──────

def test_merged_atom_timing_spans_first_to_last_constituent():
    words = [("ทะเลาะ", 0, 900, 0.9), ("กัน", 900, 1200, 0.5)]
    _, timed = timed_tokens(words)
    atoms = glue_atoms(timed, default_lexicon({}))
    merged = next(a for a in atoms if a[0] == "ทะเลาะกัน")
    assert merged[1] == 0      # start_ms of the first constituent
    assert merged[2] == 1200   # end_ms of the last constituent


def test_merged_atom_confidence_is_mean_of_non_none_constituents():
    words = [("ทะเลาะ", 0, 900, 1.0), ("กัน", 900, 1200, None)]
    _, timed = timed_tokens(words)
    atoms = glue_atoms(timed, default_lexicon({}))
    merged = next(a for a in atoms if a[0] == "ทะเลาะกัน")
    assert merged[3] == 1.0  # only the non-None constituent counts


def test_merged_atom_char_pos_is_first_constituents():
    atoms = _atoms_for("เราทะเลาะกันเมื่อวาน")
    merged = next(a for a in atoms if a[0] == "ทะเลาะกัน")
    assert merged[4] == len("เรา")


def test_atoms_never_change_text_concatenation_is_verbatim():
    """HANDOFF §2.3 item 5: atoms only regroup, never normalize/expand/drop."""
    text = "เจอผู้หญิงคนนั้นเมื่อวานตอน100บาทกับเด็กๆที่ทะเลาะกัน"
    _, timed = timed_tokens(_char_pieces(text))
    atoms = glue_atoms(timed, default_lexicon({}))
    assert "".join(a[0] for a in atoms) == text


# ── §2.3 item 4: CutDeck word-level rules keep seeing words, not atoms ─────

def test_words_from_pieces_stays_word_level_not_atom_level():
    """`words_from_pieces` (cutdeck/words.py) must not be rerouted through
    glue_atoms — CutDeck's filler-excision rules operate on real words."""
    words = words_from_pieces(_char_pieces("เราทะเลาะกันเมื่อวาน"))
    texts = [w.text for w in words]
    assert "กัน" in texts, f"CutDeck word path unexpectedly atom-merged: {texts}"


# ── snap_boundary_offsets (§2.3 item 1) ─────────────────────────────────────

def test_snap_boundary_offsets_moves_an_interior_offset_to_the_atoms_start():
    atoms = _atoms_for("เราทะเลาะกันเมื่อวาน")
    merged = next(a for a in atoms if a[0] == "ทะเลาะกัน")
    interior_offset = merged[4] + 2  # strictly inside "ทะเลาะกัน"
    snapped = snap_boundary_offsets([interior_offset], atoms)
    assert snapped == [merged[4]]


def test_snap_boundary_offsets_leaves_a_legal_offset_unchanged():
    atoms = _atoms_for("เราทะเลาะกันเมื่อวาน")
    legal_offset = atoms[0][4] + len(atoms[0][0])  # exactly the 2nd atom's start
    snapped = snap_boundary_offsets([legal_offset], atoms)
    assert snapped == [legal_offset]


def test_snap_boundary_offsets_empty_inputs():
    assert snap_boundary_offsets([], []) == []
    assert snap_boundary_offsets([5], []) == [5]


# ── §2.3 item 2: a gap between an atom's constituents never splits the cue ─

@pytest.mark.parametrize("algorithm", ["greedy", "dp"])
def test_gap_between_atom_constituents_does_not_force_a_cue_break(algorithm):
    """A silence >= gap_ms landing between two constituents of an atom (rare —
    Whisper timestamp jitter) must not split the atom: the gap check runs
    between atoms only, because by the time the splitter sees the stream, the
    atom is already one entry."""
    words = [("100", 0, 300, 0.9), (" ", 300, 350, 0.9), ("บาท", 3000, 3300, 0.9)]
    cues = _group_words_into_cues(words, gap_ms=700, target_ms=100_000,
                                   target_chars=42, algorithm=algorithm)
    assert len(cues) == 1
    assert cues[0][0] == "100 บาท"


# ── property test: the inversion made real ──────────────────────────────────

_FIXTURES = [
    "เราทะเลาะกันเมื่อวาน",
    "เจอผู้หญิงคนนั้นเมื่อวาน",
    "เขาชอบเด็กๆมาก",
    "เขาชอบเด็ก ๆ มาก",
    "ราคาทั้งหมดอยู่ที่100บาทครับ",
    "มีแมว3ตัวที่บ้าน",
    "เขาเป็นCOVID-19ครับ",
    "เจอผู้หญิงคนนั้นเมื่อวานตอน100บาทกับเด็กๆที่ทะเลาะกัน",
    "เจอผู้หญิงคนนี่เมื่อวาน",
    "เจอผู้หญิงคนนึงเมื่อวาน",
    "เจอผู้หญิงคนหนึ่งเมื่อวาน",
]


@pytest.mark.parametrize("algorithm", ["greedy", "dp"])
def test_no_cue_boundary_ever_falls_inside_an_atoms_span(algorithm):
    """The property that was impossible to write against scattered vetoes:
    across every fixture sentence and a sweep of target_chars, no cue start
    or end may land strictly inside an atom's [start_ms, end_ms) span."""
    config = {"normalization": {"exception_lexicon": ["COVID-19"]}}
    lexicon = default_lexicon(config)
    for text in _FIXTURES:
        pieces = _char_pieces(text)
        _, raw_timed = timed_tokens(pieces)
        atoms = glue_atoms(raw_timed, lexicon)
        for target_chars in range(5, 61, 5):
            cues = _group_words_into_cues(
                pieces, gap_ms=5000, target_ms=1_000_000,
                target_chars=target_chars, algorithm=algorithm, lexicon=lexicon,
            )
            boundaries = set()
            for c in cues:
                boundaries.add(c[1])
                boundaries.add(c[2])
            for atom_text, a_start, a_end, _conf, _pos in atoms:
                for b in boundaries:
                    assert not (a_start < b < a_end), (
                        f"{text!r} target_chars={target_chars} algorithm={algorithm}: "
                        f"boundary {b} falls inside atom {atom_text!r} [{a_start},{a_end})"
                    )
