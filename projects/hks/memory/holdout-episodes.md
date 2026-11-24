---
name: holdout-episodes
description: Which HKS episodes are held out from tuning and when they may be scored
type: decision
status: current
updated: 2026-11-23
---
Holdout: 20261002, 20261109, 20261118 (`cutdeck/hks_gold.py` `HOLDOUT`). `hks_audit` / `hks_score`
leave them out unless `--holdout` is passed.
**Why it matters:** later phases are scored against the gold; tuning on the holdout would hide overfitting.
**How to apply:** tune only on the eight other episodes; score the holdout once, at the end of a step.

**2026-11-23:** all three were read and scored once in the overnight study's blind test ([../study/holdout/](../study/holdout/README.md)); HKS-11–13 came from them, so they no longer test the principles. A fresh holdout needs a new episode.
