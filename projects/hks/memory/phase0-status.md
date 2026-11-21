---
name: phase0-status
description: HKS build plan Phase 0 (gold reader, clock, audit, scorer, holdout) done; 7 rule questions still with the user
type: fact
status: current
updated: 2026-11-21
---
Phase 0 (0.1–0.6) of [build-plan.md](../build-plan.md) is done: 0.1–0.4 merged as PR #107
(2026-11-20), 0.5–0.6 by 2026-11-21. Tools: `cutdeck/hks_gold.py`, `hks_clock.py` (TV clock via colon
dots), `hks_audit.py` + [rule-audit.md](../rule-audit.md), `hks_score.py`.
**How to apply:** before building Phase 1+ on a rule, check whether the user answered the 7 questions
at the end of [rule-audit.md](../rule-audit.md) (exact FB / 1-min lengths fail; the jump-cut rule is
wider than written).
