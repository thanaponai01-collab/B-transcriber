"""transcribe/thai/lint.py — HANDOFF_THAI_BREAK_ATOMS.md Phase 3.

Cue-legality lint: the harness's own eyes for the incident's failure class,
scanning real hypothesis (and reference) cue output for breaks the shared
`BreakLexicon` says are illegal, instead of relying on a human to notice it
in Premiere after export.

Run: python -m pytest tests/test_thai_lint.py -v
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from transcribe.db import store
from transcribe.thai.atoms import BreakLexicon, default_lexicon
from transcribe.thai.lint import (
    RULE_CLASSIFIER_DEMONSTRATIVE_SPLIT,
    RULE_DIGIT_FINAL,
    RULE_PARTICLE_INITIAL,
    RULE_UNSPLITTABLE_TERM_SPLIT,
    find_cue_legality_violations,
)


def _cues(*texts: str) -> list[dict]:
    return [{"text": t} for t in texts]


def _tmp_db():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    db = Path(f.name)
    store.init_db(db)
    return db


# ── no violations on legal cues ─────────────────────────────────────────────

def test_no_violations_on_well_formed_cues():
    lexicon = default_lexicon({})
    cues = _cues("เราทะเลาะกันเมื่อวาน", "เจอผู้หญิงคนนั้นวันนี้")
    assert find_cue_legality_violations(cues, lexicon) == []


def test_empty_cue_list_is_a_no_op():
    assert find_cue_legality_violations([], default_lexicon({})) == []


# ── particle_initial ─────────────────────────────────────────────────────────

def test_particle_initial_flagged_when_bind_left_material_opens_a_cue():
    lexicon = default_lexicon({})
    cues = _cues("ไปกิน", "ครับ วันนี้อากาศดี")  # ครับ stranded at cue 2's start
    violations = find_cue_legality_violations(cues, lexicon)
    assert any(v.rule == RULE_PARTICLE_INITIAL and v.index == 1 for v in violations)


def test_first_cue_starting_with_bind_left_material_is_not_flagged():
    """Nothing precedes the very first cue for the particle to have glued
    to — there is no break to be illegal."""
    lexicon = default_lexicon({})
    cues = _cues("ครับ ขอบคุณมาก")
    violations = find_cue_legality_violations(cues, lexicon)
    assert not any(v.rule == RULE_PARTICLE_INITIAL for v in violations)


def test_particle_initial_rule_respects_disabled_final_particle():
    lexicon = default_lexicon({"thai_atoms": {"disable": ["final_particle"]}})
    cues = _cues("ไปกิน", "ครับ วันนี้อากาศดี")
    violations = find_cue_legality_violations(cues, lexicon)
    assert not any(v.rule == RULE_PARTICLE_INITIAL for v in violations)


# ── particle_initial: pos_conditioned_bind_left (HANDOFF §6 Phase 4 probe) ──

def test_particle_initial_flagged_for_pos_conditioned_gan_after_a_verb():
    lexicon = default_lexicon({"thai_atoms": {"pos_condition_reciprocal": True}})
    cues = _cues("เราทะเลาะ", "กันเมื่อวาน")  # verb stranded from its กัน
    violations = find_cue_legality_violations(cues, lexicon)
    assert any(v.rule == RULE_PARTICLE_INITIAL and v.index == 1 for v in violations)


def test_particle_initial_not_flagged_for_pos_conditioned_gan_after_a_pronoun():
    """กัน opening a new cue after a pronoun-ending cue is not a stranded
    reciprocal particle — the same POS condition glue_atoms uses to decide
    not to glue it also means the lint must not flag it."""
    lexicon = default_lexicon({"thai_atoms": {"pos_condition_reciprocal": True}})
    cues = _cues("เขา", "กันไม่ให้เข้ามา")
    violations = find_cue_legality_violations(cues, lexicon)
    assert not any(v.rule == RULE_PARTICLE_INITIAL for v in violations)


# ── digit_final ──────────────────────────────────────────────────────────────

def test_digit_final_flagged_when_unit_lands_in_next_cue():
    lexicon = default_lexicon({})
    cues = _cues("ราคาทั้งหมดอยู่ที่ 100", "บาทถ้วน")
    violations = find_cue_legality_violations(cues, lexicon)
    assert any(v.rule == RULE_DIGIT_FINAL and v.index == 0 for v in violations)


def test_digit_final_on_last_cue_is_not_flagged():
    """No next cue exists for the unit to have landed in — a transcript may
    legitimately end on a bare number."""
    lexicon = default_lexicon({})
    cues = _cues("เขามีเงิน", "100")
    violations = find_cue_legality_violations(cues, lexicon)
    assert not any(v.rule == RULE_DIGIT_FINAL for v in violations)


def test_digit_final_rule_can_be_disabled():
    lexicon = default_lexicon({"thai_atoms": {"disable": ["numeral_unit"]}})
    cues = _cues("ราคาทั้งหมดอยู่ที่ 100", "บาทถ้วน")
    violations = find_cue_legality_violations(cues, lexicon)
    assert not any(v.rule == RULE_DIGIT_FINAL for v in violations)


# ── classifier_demonstrative_split ──────────────────────────────────────────

def test_classifier_demonstrative_split_flagged_across_cue_boundary():
    lexicon = default_lexicon({})
    cues = _cues("เจอผู้หญิงคน", "นั้นเมื่อวาน")
    violations = find_cue_legality_violations(cues, lexicon)
    assert any(
        v.rule == RULE_CLASSIFIER_DEMONSTRATIVE_SPLIT and v.index == 0
        for v in violations
    )


def test_classifier_demonstrative_pair_within_one_cue_is_not_flagged():
    lexicon = default_lexicon({})
    cues = _cues("เจอผู้หญิงคนนั้นเมื่อวาน")
    violations = find_cue_legality_violations(cues, lexicon)
    assert not any(v.rule == RULE_CLASSIFIER_DEMONSTRATIVE_SPLIT for v in violations)


def test_classifier_demonstrative_split_rule_can_be_disabled():
    lexicon = default_lexicon({"thai_atoms": {"disable": ["classifier_demonstrative"]}})
    cues = _cues("เจอผู้หญิงคน", "นั้นเมื่อวาน")
    violations = find_cue_legality_violations(cues, lexicon)
    assert not any(v.rule == RULE_CLASSIFIER_DEMONSTRATIVE_SPLIT for v in violations)


# ── unsplittable_term_split ──────────────────────────────────────────────────

def test_unsplittable_term_split_flagged_across_cue_boundary():
    lexicon = default_lexicon({"normalization": {"exception_lexicon": ["COVID-19"]}})
    cues = _cues("เขาเป็นCOVID-", "19ครับ")
    violations = find_cue_legality_violations(cues, lexicon)
    assert any(
        v.rule == RULE_UNSPLITTABLE_TERM_SPLIT and v.detail == "COVID-19" and v.index == 0
        for v in violations
    )


def test_unsplittable_term_whole_inside_one_cue_is_not_flagged():
    lexicon = default_lexicon({"normalization": {"exception_lexicon": ["COVID-19"]}})
    cues = _cues("เขาเป็นCOVID-19ครับ")
    violations = find_cue_legality_violations(cues, lexicon)
    assert not any(v.rule == RULE_UNSPLITTABLE_TERM_SPLIT for v in violations)


def test_no_unsplittable_terms_configured_is_a_no_op():
    lexicon = default_lexicon({})
    cues = _cues("เขาเป็นCOVID-", "19ครับ")
    violations = find_cue_legality_violations(cues, lexicon)
    assert not any(v.rule == RULE_UNSPLITTABLE_TERM_SPLIT for v in violations)


# ── §5: reference cues that violate the lexicon are found too, separately ──

def test_reference_cues_are_scanned_the_same_way_as_hypothesis():
    """The lint doesn't special-case which side it's given — the harness is
    responsible for calling it once per side and treating a reference
    violation as a lexicon-vs-taste contradiction, not a hyp bug."""
    lexicon = default_lexicon({})
    ref_cues = _cues("ไปกิน", "ครับ วันนี้อากาศดี")
    violations = find_cue_legality_violations(ref_cues, lexicon)
    assert any(v.rule == RULE_PARTICLE_INITIAL for v in violations)


# ── cues missing a "text" key or with empty text don't crash ───────────────

def test_missing_or_empty_text_key_does_not_crash():
    lexicon = default_lexicon({})
    cues = [{"text": ""}, {}, {"text": "ไปกิน"}]
    violations = find_cue_legality_violations(cues, lexicon)
    assert isinstance(violations, list)


# ── harness wiring: prints + records the count ──────────────────────────────

def test_harness_records_zero_cue_legality_violations_on_legal_hyp(monkeypatch):
    from transcribe.eval import harness

    db = _tmp_db()
    ref = [
        {"text": "เราทะเลาะกันเมื่อวาน", "script": "thai", "start_ms": 0, "end_ms": 900},
        {"text": "เจอผู้หญิงคนนั้นวันนี้", "script": "thai", "start_ms": 900, "end_ms": 1800},
    ]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(Path("a.wav"), ref)])
    result = harness.run_harness(
        {"regression_tolerance": 0.02, "regression_abs_floor": 0.005},
        db, pipeline_fn=lambda p, c: ref,
    )
    assert result is not None and result.passed
    conn = store.connect(db)
    last = store.get_last_passing_eval(conn)
    assert last is not None
    assert last.cue_legality_violations == 0
    conn.close()


def test_harness_counts_hyp_cue_legality_violations_without_failing_the_run(monkeypatch, capsys):
    """Phase 3 is descriptive-only: a nonzero count is printed and recorded,
    never a gate failure by itself."""
    from transcribe.eval import harness

    db = _tmp_db()
    ref = [
        {"text": "ไปกินครับ วันนี้อากาศดี", "script": "thai", "start_ms": 0, "end_ms": 1800},
    ]
    hyp = [
        {"text": "ไปกิน", "script": "thai", "start_ms": 0, "end_ms": 900},
        {"text": "ครับ วันนี้อากาศดี", "script": "thai", "start_ms": 900, "end_ms": 1800},
    ]
    monkeypatch.setattr(harness, "_load_goldenset", lambda: [(Path("a.wav"), ref)])
    result = harness.run_harness(
        {"regression_tolerance": 0.02, "regression_abs_floor": 0.005},
        db, pipeline_fn=lambda p, c: hyp,
    )
    assert result is not None
    assert result.passed, "a nonzero lint count must never fail the run (no gate in Phase 3)"
    conn = store.connect(db)
    last = store.get_last_passing_eval(conn)
    assert last is not None
    assert last.cue_legality_violations == 1
    captured = capsys.readouterr()
    assert "cue_legality" in captured.out
    assert "particle_initial" in captured.out
    conn.close()
