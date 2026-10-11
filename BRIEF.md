# Project brief

Goal: local Thai-primary transcription and review, with CutDeck Premiere workflows
and a separate ClubFriday quote workspace. Sources: [SYSTEM_SPEC.md](SYSTEM_SPEC.md),
[ClubFriday requirements](clubfriday/README.md), [agent decisions](CLAUDE.md).

## Decisions and constraints in force
- Engine A is faster_whisper; Engine B is passthrough; LLM reconciliation is off
  (transcribe/config.yaml). The older two-active-engine narrative is historical intent.
- Select-only reconciliation, sequential GPU model residency, engine contract boundary
  and metric regression gates remain mandatory (CLAUDE.md, STYLE_GUIDE.md).
- ClubFriday preserves editable exact text, one to three lines and absolute timeline
  timestamps; saved quotes can be reopened. Exports use UTF-8 BOM and project-local
  CutDeck/ClubFriday paths (clubfriday/README.md).
- No automatic styled graphics or automatic caption timeline placement is promised.
- Requirements and acceptance must not be inferred from implementation alone.

## Selected acceptance for this foundation
ClubFriday adds the captured range offset to helper-relative cue times; quote and
full transcript exports preserve timeline timing and text. Empty/overlapping quotes
are refused. Requirement: clubfriday/README.md; checks: tests/test_clubfriday.py.

## Scope and unanswered questions
- Current owner priority (2026-10-11): fix Rough Cut stopping midway and leaving
  FAILED copies; recover and record the architecture (docs/rough-cut.md).
- Scope is repository context plus a ClubFriday backend verification slice.
- Rough Cut reliability is the current owner priority; live-host confirmation remains pending.
- Real GPU accuracy, Premiere insertion and browser interactions need separate proof.
- SYSTEM_SPEC.md has historical engine/status/count notes; use current config and
  CLAUDE.md for active engine decisions. This pass does not rewrite historical specs.

Read [features](FEATURES.md) for area paths and [work](BUILD.md) for Next.
