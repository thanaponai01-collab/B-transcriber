# Clip label colours across 12 episodes (overnight study)

Read offline from each day's `.prproj` with `output/hks_study/study_labels.py`. A timeline clip's
label is `asl.clip.label.name = BE.Prefs.LabelColors.N` in its `VideoClip`/`AudioClip` properties.
The names come from the user's Premiere prefs (`27.0/Profile-thana/Adobe Premiere Pro Prefs`,
`BE.Prefs.LabelNames.N`): 1 PINK, 2 PURPLE, 4 BLUE, 7 TEAL, 8 GREEN, 9 LIGHT GREEN, 10 YELLOW, 11 ORANGE
(the meanings in [../rules.md](../rules.md)); 3 DEEP PURPLE, 5 LIGHT BLUE, 6 CYAN, 12 GREY, 15 B are also
used; 14 G is the default an unlabelled clip carries. The live `read_timeline` returns no label
(`colorLabel` null): offline is the only route today. Shares are seconds of the YT body's A1.

| Day | YT body (top labels) | YT last 3 pieces | FB from YT, by label | 1-min from YT, by label |
|---|---|---|---|---|
| 1001 | PURPLE 36, BLUE 25, PINK 20, YELLOW 8 | BLUE BLUE PINK | PURPLE 38, LT GREEN 21, PINK 18 | LT GREEN 43, **YELLOW 31**, PINK 16 |
| 1002 | **YELLOW 26**, BLUE 23, PINK 21 | **ORANGE ×3** | **YELLOW 41**, PINK 16 | LT GREEN 54, PINK 23, PURPLE 23 |
| 1003 | PINK 39, YELLOW 22, ORANGE 13 | **ORANGE ×3** | PINK 55, DEEP PURPLE 16 | DEEP PURPLE 62, **YELLOW 38** |
| 1012 | PINK 32, YELLOW 21, LT GREEN 18 | YELLOW GREEN PINK | PINK 67, YELLOW 20 | PINK 62, **YELLOW 38** |
| 1020 | PINK 34, YELLOW 18, TEAL 12 | BLUE BLUE **ORANGE** | PINK 51, B 18, TEAL 16 | PINK 100 |
| 1109 | LT BLUE 30, PURPLE 17, GREEN 15, YELLOW 12 | PURPLE PURPLE **ORANGE** | LT BLUE 33, **YELLOW 23** | **YELLOW 52**, GREEN 48 |
| 1110 | **YELLOW 27**, PINK 23 | PINK ×3 | **YELLOW 68**, PINK 32 | **YELLOW 100** |
| 1112 | PINK 58, YELLOW 13, ORANGE 11 | **ORANGE ×3** | **ORANGE 51**, PINK 38 | **ORANGE 100** |
| 1117 | LT GREEN 38, PINK 25, GREEN 16 | PINK ×3 | LT GREEN 53, PINK 42 | LT GREEN 66, PINK 34 |
| 1118 | PINK 34, YELLOW 25, TEAL 11, ORANGE 11 | GREY **ORANGE ORANGE** | PINK 48, **YELLOW 47** | **YELLOW 70**, ORANGE 30 |
| 1120 | PINK 30, LT GREEN 21, YELLOW 17 | BLUE BLUE **ORANGE** | LT GREEN 33, PINK 26 | **YELLOW 51**, LT GREEN 49 |
| 1123 | PINK 52, PURPLE 30, BLUE 10, GREEN 5 | G ×3 (unlabelled) | PINK 63, PURPLE 37 | PINK 100 |

## What the labels show (seen)

1. **ORANGE ("ending sentences") is the ending.** Every day that uses ORANGE in the YT body ends
   the YT on it: 8 of 8 (1002, 1003, 1020, 1109, 1112, 1118, 1120, and 0929 from its `topic cutting`
   pass, where the ORANGE topic is the cut's last piece). The user marks the closing line
   while selecting, before the cut is built.
2. **YELLOW ("must be in, or a highlight") is the pool for the short cuts.** The shorter the cut, the
   larger YELLOW's share: 1110 27 % of the YT → 68 % of the FB → 100 % of the 1-min; 1118 25 → 47 → 70 %;
   1109 12 → 23 → 52 %; 1120 17 → 15 → 51 %; 1001 8 → 8 → 31 %; 1003 22 → 10 → 38 %; 1012 21 → 20 → 38 %.
   In 7 of the 9 days that use YELLOW, the 1-min holds more YELLOW than the YT.
3. **LIGHT GREEN (inserts, videos) also grows in the 1-min** (1001 43 %, 1002 54 %, 1117 66 %, 1120 49 %):
   the 1-min favours footage over studio talk.
4. **On 1112 the ending is the short:** the FB is 51 % ORANGE and the 1-min 100 % ORANGE. The closing
   threat is the episode's punch (HKS-15).
5. **The colour meanings settled late.** October days use DEEP PURPLE, LIGHT BLUE, CYAN, B and GREY
   with meanings of their own; 1123 is labelled purely by speaker (PINK guest 1, PURPLE guest 2, BLUE
   lawyer, GREEN host: the "label per question" rule of 2026-11-23) with no YELLOW or ORANGE at all.

## 1123 without YELLOW or ORANGE: what the short cuts imply (guess)

1123 carries no YELLOW or ORANGE, so the sets are inferred from where its short cuts draw:
- **Inferred YELLOW (the 1-min pool):** all ten YT pieces the 1-min uses lie in 818.6–944.1 s of the YT,
  the night of the 16th (comeback and stabbing). That is 5 % of the YT body, all PINK (guest 1). The
  FB draws on 29 YT pieces (24 %).
- **Inferred ORANGE (the ending):** the YT's last three pieces, 1170.9–1189.0 s (quit selling; the
  money comes back and the loan is void), labelled G (unlabelled). The FB ends elsewhere: its last
  piece is source 3498.9–3511.3, the YT's is 4498.8–4509.0.
So on a speaker-labelled day the 1-min still takes the single most visual beat, as YELLOW does on
the other days (HKS-15).

## The why (guess) and what it means for drafts

- The labels are the user's **first pass of judgment**, made while watching: who speaks, what must
  stay, what ends it. The cut, the FB and the 1-min are then built from that pass. So a draft that
  gets the labels right gets most of the selection right.
- **For automation:** a judge that marks YELLOW and ORANGE on the day's question pieces would give
  the FB and 1-min pool and the ending in one pass. The 1123 labelling (speaker only) drops that
  signal. Ask whether YELLOW and ORANGE should still be marked now that labels are per question.

## Questions for the user

1. Is YELLOW still "the pool for the FB and 1-min" now that labels are per question (1123 has none)?
2. Should agent drafts mark YELLOW and ORANGE as well as the speaker colour?
3. What did LIGHT BLUE (1109, 30 %), CYAN, DEEP PURPLE, B and GREY mean on the October days?
