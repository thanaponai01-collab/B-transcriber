---
name: dialogue-cleanup-of-exports
description: User's defaults for cutting spoken mistakes out of an exported F1 talking video, and the join technique that worked
type: preference
status: current
updated: 2026-11-11
---
On 2026-11-11 the user asked to clean spoken mistakes out of an exported rough cut
(`E:\Me\2.Tasks\20261108 - 4\5. EXPORTS\Brazil YT1.mp4`, F1 race review, Thai). Their choices when asked:

- Deliver a **new MP4 next to the original** (original untouched), not a Premiere sequence.
- Remove repeated words and wrong starts, **and** fillers (เอ่อ/อืม/อ่า), off-topic live-chat replies,
  "looking for the picture" moments, and leftover words after the closing line.
- **Cut first, then they review** from a cut list with times; leave unsure spots in and list them.

**Why it matters:** they want each sentence said once, cleanly (M-4), without re-asking these choices.
**How to apply:** for the same kind of request, use these as defaults and say so. Thai reduplication
(เรื่อยเรื่อย, เต็มเต็ม) is not a repeat. Technique that worked (scripts were scratch, not in the repo):
faster-whisper word times are too coarse for word-level joins (zero-length fillers, ±0.1–0.3 s); for a
repeated word, cut from a point in take 1 to the same-sounding point in take 2 (log-mel match),
otherwise snap edges to the quietest 10 ms; cut audio sample-exact and pick video frames to track it;
then re-transcribe the result to check each join.
