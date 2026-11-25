# HKS (โหนกระแส, Honekasae)

A ~2 h live news-talk show, cut by the user into 4 deliverables per episode: YouTube long form
(15–20 min), Facebook (1080², 2:59:24), Reel 3 min and Reel 1 min. Goal: the user approves drafts
instead of cutting by hand ([build-plan.md](build-plan.md)).

**Two programs (the user, 2026-11-24):**
- **โหนกระแส**: the main show. Each day's ~2 h broadcast is cut into the four deliverables above.
- **โหนหลังกระแส**: a compilation. It usually joins **4 videos**, each one a **long โหนกระแส video that is
  already edited** (a day's finished YT cut, ~20 min), cut down again into one video (EP.162, EP.167, EP.168;
  study files `*-compilation.md`, `20261111-ep168-paper-edit.md`).

## Read order
0. **[before-you-cut.md](before-you-cut.md): read before every draft.** Short gates; a failed one is named in the handover.
1. [Main principles](../PRINCIPLES.md)
2. [principles.md](principles.md): the show's why (`HKS-n`; none confirmed yet)
3. [memory/MEMORY.md](memory/MEMORY.md): facts; open only what the task needs
4. [rules.md](rules.md): how it's cut today (`HKS-Rn`, under audit)
5. [build-plan.md](build-plan.md) → [rule-audit.md](rule-audit.md): the automation plan and its checks
6. [workflow-log.md](workflow-log.md): the evidence (episode 20261120, steps 0–8)
7. [design-topic-cut.md](design-topic-cut.md): earlier topic-cut design; its findings still hold
8. [study/README.md](study/README.md): the agent's study of every finished cut (2026-11-23): synthesis,
   candidate principles HKS-1–13, holdout test, questions for the user

## Where things live
- Day folders: `G:\Me\Works\YYYYMMDD - โหนกระแส` ([memory](memory/day-folders.md))

## Code and tests
- `cutdeck/hks_gold.py`, `hks_clock.py`, `hks_audit.py`, `hks_score.py`, `hks_build.py`, `hks_words.py`
  (`tests/test_hks_*.py`)
- `cutdeck/hks_cut_check.py` — the agent's own cut mistakes in a saved draft: visible cuts in speech, same-frame cuts, unsafe J/L holds (`tests/test_hks_cut_check.py`; rules.md "My own mistakes")
- `cutdeck/hks_handover.py` — run before every draft handover: the gates in [gates/registry.json](gates/registry.json) (lines set on the user's finals), a Drafts snapshot, the handover header. Why and evidence: [gates/](gates/README.md)
- `cutdeck/honekasae_export.py` — one-command export to Media Encoder (`tests/test_honekasae_export.py`)
- `cutdeck/topic_layout.py`, `topic_speakers.py` (`tests/test_cutdeck_topic_*.py`)
- `uxp/cutdeck/timeline/buildSequence.js`, `hksSpikeProbe.js`
