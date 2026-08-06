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

def test_default_lexicon_seeds_the_ported_and_grown_rules():
    """Phase 1 ported มai_yamok/กัน exactly; Phase 2 (HANDOFF §4) grows
    bind_left with the final-particle batch on top — this test tracks the
    current shipped default, not a frozen Phase-1 snapshot."""
    lex = default_lexicon({})
    assert {"ๆ", "กัน"} <= lex.bind_left
    assert "ครับ" in lex.bind_left and "ค่ะ" in lex.bind_left  # final_particle batch
    assert lex.bind_right_digit is True
    assert ("คน", "นั้น") in lex.pair_bind_left
    assert ("ตัว", "นี้") in lex.pair_bind_left
    assert lex.unsplittable_terms == frozenset()


def test_final_particle_rule_can_be_disabled():
    lex = default_lexicon({"thai_atoms": {"disable": ["final_particle"]}})
    assert "ครับ" not in lex.bind_left
    assert {"ๆ", "กัน"} <= lex.bind_left  # other default rules unaffected


def test_default_lexicon_reads_exception_lexicon_as_unsplittable_terms():
    config = {"normalization": {"exception_lexicon": ["COVID-19", "iPhone"]}}
    lex = default_lexicon(config)
    assert lex.unsplittable_terms == frozenset({"COVID-19", "iPhone"})


def test_default_lexicon_disable_and_extra_bind_left():
    config = {"thai_atoms": {"disable": ["reciprocal_particle", "final_particle"],
                              "extra_bind_left": ["นะ"]}}
    lex = default_lexicon(config)
    assert lex.bind_left == frozenset({"ๆ", "นะ"})  # กัน + final_particle batch dropped, นะ added back


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


# ── glue_atoms: pos_conditioned_bind_left (HANDOFF §6 Phase 4 probe) ───────

def test_default_lexicon_pos_condition_reciprocal_off_by_default():
    lex = default_lexicon({})
    assert "กัน" in lex.bind_left
    assert lex.pos_conditioned_bind_left == frozenset()


def test_default_lexicon_pos_condition_reciprocal_moves_gan_out_of_bind_left():
    lex = default_lexicon({"thai_atoms": {"pos_condition_reciprocal": True}})
    assert "กัน" not in lex.bind_left
    assert lex.pos_conditioned_bind_left == frozenset({"กัน"})


def test_pos_conditioned_reciprocal_still_glues_after_a_verb():
    lexicon = default_lexicon({"thai_atoms": {"pos_condition_reciprocal": True}})
    atoms = _atoms_for("เราทะเลาะกันเมื่อวาน", lexicon=lexicon)
    texts = [a[0] for a in atoms]
    assert "ทะเลาะกัน" in texts, f"verb-preceded กัน should still glue: {texts}"


def test_pos_conditioned_reciprocal_does_not_glue_after_a_pronoun():
    """กัน is also 'to block' outside the reciprocal sense — bind_left glues
    it unconditionally (accepted over-glue, §2.4); the POS-conditioned probe
    exists specifically to stop this over-glue when nothing verb-like
    precedes it."""
    lexicon = default_lexicon({"thai_atoms": {"pos_condition_reciprocal": True}})
    atoms = _atoms_for("เขากันไม่ให้เข้ามา", lexicon=lexicon)
    texts = [a[0] for a in atoms]
    assert "เขากัน" not in texts, f"pronoun-preceded กัน should not glue: {texts}"
    assert any(t.strip() == "กัน" for t in texts), f"กัน should stand alone: {texts}"


def test_pos_condition_reciprocal_disabled_still_over_glues_after_a_pronoun():
    """Default (off) behaviour is unchanged by adding the probe — bind_left's
    unconditional glue still fires regardless of what precedes กัน."""
    atoms = _atoms_for("เขากันไม่ให้เข้ามา")
    texts = [a[0] for a in atoms]
    assert "เขากัน" in texts, f"default behaviour should be unchanged: {texts}"


def test_pos_conditioned_reciprocal_strands_gan_after_a_demonstrative_real_corpus_case():
    """Real sentence from Short2.json (gold-set reference, already in the
    corpus): 'ทำแบบนี้กันทั้งนั้น' ("[everyone] does it like this") — กัน
    marks the whole verb phrase ทำแบบนี้ as collective, but immediately
    follows the demonstrative แบบนี้ (POS-tagged DDAC), not the verb ทำ
    itself. This is the confirmed negative result that keeps
    pos_condition_reciprocal at false (see config.yaml/TODO_LEDGER): a
    single-token lookback strands กัน on real, unremarkable creator speech —
    reproducing the exact stranded-particle defect this handoff exists to
    prevent. Default (off) must keep gluing it; do not re-enable the flag
    without this test also passing."""
    default_atoms = _atoms_for("ทำแบบนี้กันทั้งนั้น")
    default_texts = [a[0] for a in default_atoms]
    assert "แบบนี้กัน" in default_texts, f"default should glue: {default_texts}"

    pos_lexicon = default_lexicon({"thai_atoms": {"pos_condition_reciprocal": True}})
    pos_atoms = _atoms_for("ทำแบบนี้กันทั้งนั้น", lexicon=pos_lexicon)
    pos_texts = [a[0] for a in pos_atoms]
    assert any(t.strip() == "กัน" for t in pos_texts), (
        f"documents the known false-negative: pos-conditioning strands กัน "
        f"here instead of gluing it — got {pos_texts}"
    )


# ── glue_atoms: numeral + unit/classifier ───────────────────────────────────

def test_digit_final_token_glues_to_its_unit_across_whitespace():
    """ครับ is also a default final_particle (batch 3) and glues onto บาท in
    turn, so the merged atom legitimately grows to '100 บาทครับ' — assert by
    substring, not exact text, to isolate the digit-unit rule under test."""
    atoms = _atoms_for("ราคาทั้งหมดอยู่ที่ 100 บาทครับ")
    texts = [a[0] for a in atoms]
    assert any("100 บาท" in t for t in texts), f"numeral split from its unit: {texts}"


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


# ── glue_atoms: HANDOFF §4 item 2 — grown classifier set ────────────────────

@pytest.mark.parametrize("noun,classifier", [
    ("หนังสือ", "เล่ม"),   # book
    ("รถ", "คัน"),         # vehicle
    ("บ้าน", "หลัง"),      # building
    ("เสื้อ", "ตัว"),      # already present, sanity check alongside new ones
    ("รองเท้า", "คู่"),    # pair
    ("นิทาน", "เรื่อง"),   # story/topic
])
def test_grown_classifier_glues_to_its_demonstrative_and_preceding_noun(noun, classifier):
    """HANDOFF §4 item 2: the original 5 classifiers only covered a sliver of
    spoken Thai's common set — เล่ม/คัน/หลัง/คู่/... etc. need the same
    protection คน already had."""
    atoms = _atoms_for(f"เจอ{noun}{classifier}นั้นเมื่อวาน")
    texts = [a[0] for a in atoms]
    assert f"{noun}{classifier}นั้น" in texts, f"pair not glued to its noun: {texts}"
    assert not any(t.strip() == classifier for t in texts), f"classifier orphaned: {texts}"


# ── glue_atoms: HANDOFF §4 item 3 — final/polite particles ─────────────────

@pytest.mark.parametrize("particle", [
    "นะ", "ครับ", "ค่ะ", "คะ", "สิ", "เลย", "ล่ะ", "แหละ", "หรอก", "เถอะ",
    "จ้ะ", "อ่ะ", "มั้ย", "ไหม", "เหรอ", "หรอ", "ป่ะ",
])
def test_final_particle_glues_to_preceding_word(particle):
    """Utterance-final particles are never sentence-initial in Thai —
    stranded at a cue start they read exactly as broken as a stranded กัน
    did (HANDOFF §4 item 3)."""
    atoms = _atoms_for(f"ไปกิน{particle}")
    texts = [a[0] for a in atoms]
    assert f"กิน{particle}" in texts, f"particle not glued to preceding word: {texts}"
    assert not any(t.strip() == particle for t in texts), f"particle orphaned: {texts}"


def test_final_particle_rule_disabled_leaves_particle_unglued():
    lexicon = default_lexicon({"thai_atoms": {"disable": ["final_particle"]}})
    atoms = _atoms_for("ไปกินครับ", lexicon=lexicon)
    texts = [a[0] for a in atoms]
    assert "กิน" in texts and "ครับ" in texts, f"disabled rule still glued: {texts}"


# ── glue_atoms: unsplittable_terms (exception lexicon) ─────────────────────

def test_exception_lexicon_term_split_by_tokenizer_is_reglued():
    """pythainlp splits 'COVID-19' into 'COVID-' + '19' — the exact case this
    rule exists for (STYLE_GUIDE §6). numeral_unit and final_particle both
    disabled so this test isolates the unsplittable_terms rule alone from
    the (separately tested) digit-glue and final-particle rules, which would
    otherwise also glue '19' to 'ครับ' and obscure which rule did the work."""
    lexicon = default_lexicon({"normalization": {"exception_lexicon": ["COVID-19"]},
                                "thai_atoms": {"disable": ["numeral_unit", "final_particle"]}})
    atoms = _atoms_for("เขาเป็นCOVID-19ครับ", lexicon=lexicon)
    texts = [a[0] for a in atoms]
    assert "COVID-19" in texts, f"exception term not reglued: {texts}"


def test_exception_lexicon_term_already_one_token_is_a_no_op():
    lexicon = default_lexicon({"normalization": {"exception_lexicon": ["iPhone"]}})
    atoms = _atoms_for("ผมใช้iPhoneอยู่", lexicon=lexicon)
    texts = [a[0] for a in atoms]
    assert "iPhone" in texts


def test_no_unsplittable_terms_configured_is_a_no_op():
    lexicon = default_lexicon({"thai_atoms": {"disable": ["numeral_unit", "final_particle"]}})
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
