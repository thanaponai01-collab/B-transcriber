# Replay: the 16 rule-break corrections of 1123–1125 under the new design

"Stops" is fixed before scoring (three columns, only the first two count next to today's 4):

- **Blocked:** a kept control fails on the saved draft. The helper stores it, and the panel shows the draft red with the gate id and value whatever the agent says.
- **Visible:** the helper puts it on the panel row (a warning) without the agent's help, but nothing fails.
- **Answer:** only a do–confirm answer covers it. It depends on the agent answering honestly. The 1125 endings experiment (output/hks_rules/do_confirm/) shows an answer check doesn't catch it.
- **None:** nothing in the design touches it.

| K | Way | Today (gates + Stop hook) | New design | Column | Why |
|---|---|---|---|---|---|
| K1 | E | none | day_setup can't see one missed insert of 55 | Answer | day-setup do–confirm item only |
| K2 | C | none | no gate measures cover length within one scene | None | candidate gate needed |
| K3 | D | none | contradiction check flags the overturned rule (LLM, after the correction) | None | finds the conflict for the rule edit, doesn't stop the draft |
| K5 | C | none | no gate reads lip sync of a still | None | |
| K6 | A | draft_labels (counted) | draft_labels control | Blocked | |
| K7a | C | near_miss_covers (counted) | near_miss_covers control | Blocked | |
| K9 | B | day_setup warning, in the transcript only | day_setup "Editing not split" on the panel row | Visible | needs the panel to show warnings (done) |
| K10 | E | day_setup warning, in the transcript only | day_setup "Backup empty" on the panel row | Visible | |
| K11 | E | same_frame_share (counted) | same_frame_share control | Blocked | |
| K15 | E | none | piece-end list; answer check | Answer | experiment: verdicts can't judge endings |
| K17 | D | none | contradiction check, after the fact | None | |
| K18 | C | none | no gate measures the centring of the video inside the box | None | |
| K21 | D | none | paper-edit do–confirm (set-up in two lines) | Answer | |
| K22 | C | none | piece-end list; answer check | Answer | experiment: no design catches 3347.00 |
| K23 | B | same_frame_share + Stop hook label (counted) | same_frame_share control, red in the panel | Blocked | no longer depends on the session transcript |
| K26 | E | day_setup warning, in the transcript only | day_setup "no yellow" on the panel row | Visible | |

**Totals:** Blocked 4 (K6, K7a, K11, K23), the same 4 as today. Visible 3 (K9, K10, K26), up from 0 on the panel. Answer 4 (K1, K15, K21, K22). None 5 (K2, K3, K5, K17, K18). K27 (way F) stays blocked by source_repeats on the 19:34 save, as today.

**What changed is where the 4 are enforced, not how many there are.** Today a draft is counted as caught only if the agent runs hks_handover and the Stop hook reads its transcript. Under the new design the helper's record and the panel show red, or ungated after any later edit, whoever touched the draft.

Measured: K23 on the 1125 v1 save (Auto-Save 19:46), hks_enforce.handover → fail, same_frame_share 0.705 vs 0.46; 154 answers missing. Inferred: every other row. Each comes from the failure table, the gate registry and the replay rule above, not from a rerun.
