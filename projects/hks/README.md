# HKS (โหนกระแส, Honekasae)

A ~2 h live news-talk show, cut by the user into 4 deliverables per episode: YouTube long form
(15–20 min), Facebook (1080², 2:59:24), Reel 3 min and Reel 1 min. Goal: the user approves drafts
instead of cutting by hand ([build-plan.md](build-plan.md)).

## Read order
1. [Main principles](../PRINCIPLES.md)
2. [principles.md](principles.md): the show's why (`HKS-n`; none confirmed yet)
3. [memory/MEMORY.md](memory/MEMORY.md): facts; open only what the task needs
4. [rules.md](rules.md): how it's cut today (`HKS-Rn`, under audit)
5. [build-plan.md](build-plan.md) → [rule-audit.md](rule-audit.md): the automation plan and its checks
6. [workflow-log.md](workflow-log.md): the evidence (episode 20261120, steps 0–8)
7. [design-topic-cut.md](design-topic-cut.md): earlier topic-cut design; its findings still hold

## Where things live
- Day folders: `G:\Me\Works\YYYYMMDD - โหนกระแส` ([memory](memory/day-folders.md))

## Code and tests
- `cutdeck/hks_gold.py`, `hks_clock.py`, `hks_audit.py`, `hks_score.py`, `hks_build.py`, `hks_words.py`
  (`tests/test_hks_*.py`)
- `cutdeck/honekasae_export.py` — one-command export to Media Encoder (`tests/test_honekasae_export.py`)
- `cutdeck/topic_layout.py`, `topic_speakers.py` (`tests/test_cutdeck_topic_*.py`)
- `uxp/cutdeck/timeline/buildSequence.js`, `hksSpikeProbe.js`
