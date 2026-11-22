---
name: watch-method
description: How HKS editing was recorded (user narrates steps, agent reads saves and a word transcript)
type: decision
status: current
updated: 2026-11-20
---
Since 2026-11-20 the user reports each HKS step; the agent records it in
[workflow-log.md](../workflow-log.md) (Do / Input→output / Decisions / Time / Automate?), reads state
from Ctrl+S saves with `cutdeck/prproj_reader.py` and a faster-whisper word transcript of the footage.
Episode 20261120 is recorded end to end (steps 0–8). Open: export naming, the AE title-card template,
what the live notes contain.
**How to apply:** when the user describes a step, append it to the log, then ask 2–3 targeted questions
(the rule and its why, inputs/outputs, frequency).
