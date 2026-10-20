# Project brief

Goal: local Thai-primary transcription and review, with CutDeck Premiere workflows
and a separate ClubFriday quote workspace. Sources: [SYSTEM_SPEC.md](SYSTEM_SPEC.md),
[ClubFriday requirements](clubfriday/README.md), [agent decisions](CLAUDE.md).

## Decisions and constraints in force
- Text geometry follow-up (2026-10-19): reverse engineer Premiere's native text bounds for accurate alignment and anchor placement in the existing Transform UXP panel. Evidence and remaining live checks: [native text bounds](docs/research/cutdeck-native-text-bounds-2026-10-19.md). Native geometry must be validated before replacing rendered measurement.
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
- Follow-up authorized 2026-10-11: retire XML-file Rough Cut, keep JSON analysis and
  native editing, separate shared services, and refuse changed source audio before edits.
  Acceptance: verification/rough-cut-retirement.md.
- Real GPU accuracy, Premiere insertion and browser interactions need separate proof.
- SYSTEM_SPEC.md was synchronized (2026-10-20, issue #76) with active engine statuses, service.py, coverage.py, review.py, and METRICS_VERSION=4.

Read [features](FEATURES.md) for area paths and [work](BUILD.md) for Next.

## Native cutter prototype — 2026-10-16
- Owner request: use Premiere native cutting internally in the existing Rough Cut system; no manual cutting toolbar. Build a disposable native bridge spike first; do not integrate until real-host behavior is verified.
- Owner supplied Premiere Pro 26.0 C++ SDK under files/ and approved installation of Visual Studio 2022 C++ Build Tools, MSVC v143 and Windows SDK 10.0.26100.
- First check is a read-only Control Surface plugin that enumerates host commands. Only after load/enumeration proof may a separately bounded split test run on a disposable sequence copy. Existing source preservation and exact read-back remain required.
- Investigation: docs/research/cutdeck-native-cutter-2026-10-16.md. Prototype source: tools/native-cutter-spike/. Existing RUN.json belongs to earlier work and is preserved.
