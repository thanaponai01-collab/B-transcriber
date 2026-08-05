# Gold-set source videos (contamination guard)

**Why this file exists** (HANDOFF_ONE_ENGINE.md §3.4): the gold set is a
**test** set. The moment fine-tuning starts (Phase C), no clip in this
directory — nor any clip from the **same source video** — may enter training
data, even if the training clip covers a different time range. Silent
contamination here would invalidate the regression gate without anyone
noticing. Phase C's data-engine tooling (`tools/make_finetune_set.py`, not
yet built — TODO_LEDGER) must read this file and refuse any training
candidate whose source matches a row below.

Provenance was reconstructed from commit messages (`git log`), since no gold
JSON stores a source field. Where a relationship is stated below without a
`CONFIRMED` tag, it was **not** independently verified against the user's raw
footage — treat it as the conservative default (assume distinct source) but
double-check with the user before relying on it for a real fine-tune
exclusion decision.

| Gold clip | Source video | Status |
|---|---|---|
| `Bangkok Festivals_CT6_Short1_D5` | `SOUND FINAL.mp3` / `SOUND FINAL mine.srt` raw interview — intro teaser 0:00-0:15 + main occurrence 27:37-33:35 | **CONFIRMED** (commit `4e87034`/`6543249`) |
| `Bangkok Festivals_CT6_Short2_D1` | same `SOUND FINAL` raw interview — ~48:55-50:10 | **CONFIRMED** (commit `4e87034`, same interview as Short1_D5) |
| `Bangkok Festivals_CT6_PeterWolf` | same `SOUND FINAL` raw interview — 23:43-27:23 | **CONFIRMED** (commit `4e87034`, explicitly trimmed to avoid overlapping Short1_D5/Short2_D1's ranges above) |
| `Bangkok_Festivals_orchestra_sections` | Bangkok-Festivals-themed footage, added independently (commit `2378d3f`) | Unconfirmed whether this is the same raw interview as the three rows above (no "CT6" tag, added separately) — **treat as its own exclusion group by default**, verify before assuming independence |
| `Short1` | independent short (commit `e9f8ed4`) | Unconfirmed source video; no documented overlap with any other row |
| `Short2` | independent short (commit `e9f8ed4`) | Unconfirmed source video; no documented overlap with any other row |
| `Short3` | independent short (commit `e9f8ed4`) | Unconfirmed source video; no documented overlap with any other row |
| `หายไปนานเลย กลับมา DCA ต่อ ｜ 26 Month Update ｜ Wealthy 40 - [j6IECK-D-D8]` | standalone finance-vlog YouTube upload (commit `9705e70`), first 2 min | Distinct creator/channel from the Bangkok Festivals rows — no overlap expected |

**Exclusion groups for Phase C tooling:** `{Short1_D5, Short2_D1, PeterWolf}`
is one group (same raw interview — exclude ALL THREE if any one is
suspected to overlap a training clip's source). Every other row is its own
singleton group until proven otherwise.
