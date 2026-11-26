# HKS gate mutation test

Each kept gate on the user's finals, then on a copy with the mistake it guards against put back.
`tools/hks_gates_mutate.py`; data in `results.json`. Holdouts marked *.

## Kill rate

| Mutant | Target gate | Killed | Survived | Other | Kill rate |
|---|---|---|---|---|---|
| noop | none | 0 | 0 | 14 | None |
| same_frame_share | same_frame_share | 14 | 0 | 0 | 1.0 |
| near_miss_early | near_miss_covers | 14 | 0 | 0 | 1.0 |
| near_miss_late | near_miss_covers | 0 | 14 | 0 | 0.0 |
| source_repeats | source_repeats | 14 | 0 | 0 | 1.0 |
| draft_labels | draft_labels | 13 | 0 | 1 | 1.0 |
| body_range | body_range | 14 | 0 | 0 | 1.0 |
| body_range_half_show | body_range | 2 | 12 | 0 | 0.143 |

## Baseline and margin

| Final | body_from | same_frame (cuts to fail) | near_miss (cuts / early shifts to fail) | repeats | labels (pieces to fail) | body share (fails from body_from s / show end s) | baseline fails |
|---|---|---|---|---|---|---|---|
| 20261001 | 22.80 | 0.143 (52 of 161) | 0.056 (1 / 2 of 8 covers) | 0 | 1.0 (9 of 176) | 0.997 (1308 / 1082) | - |
| 20261002* | 26.32 | 0.184 (38 of 136) | 0.044 (3 / 4 of 15 covers) | 0 | 1.0 (9 of 170) | 0.996 (1411 / 1102) | - |
| 20261003 | 18.56 | 0.168 (54 of 184) | 0.011 (10 / 13 of 26 covers) | 0 | 1.0 (12 of 226) | 0.998 (1866 / 1189) | - |
| 20261012 | 26.16 | 0.451 (1 of 71) | 0.014 (4 / 8 of 11 covers) | 0 | 1.0 (6 of 105) | 0.998 (2434 / 1143) | - |
| 20261020 | 26.92 | 0.333 (16 of 120) | 0.008 (7 / 9 of 11 covers) | 0 | 1.0 (9 of 171) | 0.997 (1896 / 1011) | - |
| 20261109* | 26.20 | 0.133 (38 of 113) | 0.009 (6 / 6 of 17 covers) | 0 | 1.0 (8 of 141) | 0.997 (2000 / 1098) | - |
| 20261110 | 21.48 | 0.373 (8 of 83) | 0.024 (4 / 6 of 7 covers) | 0 | 0.949 (0 of 118) | 0.997 (1350 / 1066) | draft_labels |
| 20261112 | 21.44 | 0.321 (15 of 106) | 0.009 (6 / 6 of 11 covers) | 0 | 1.0 (8 of 139) | 0.998 (2088 / 1147) | - |
| 20261117 | 24.32 | 0.066 (101 of 256) | 0.027 (9 / 9 of 19 covers) | 0 | 1.0 (15 of 296) | 0.997 (1538 / 1159) | - |
| 20261118* | 24.56 | 0.203 (32 of 123) | 0.049 (2 / 3 of 11 covers) | 0 | 1.0 (9 of 162) | 0.996 (1313 / 1126) | - |
| 20261120 | 25.84 | 0.112 (57 of 161) | 0.019 (7 / 7 of 17 covers) | 0 | 1.0 (10 of 193) | 0.997 (1688 / 1096) | - |
| 20261123 | 18.60 | 0.14 (49 of 150) | 0.02 (7 / 11 of 13 covers) | 0 | 0.971 (4 of 172) | 0.998 (2052 / 1197) | - |
| 20261124 | 32.00 | 0.069 (68 of 173) | 0.006 (10 / 10 of 24 covers) | 0 | 1.0 (11 of 207) | 0.973 (237 / 1184) | - |
| 20261125 | 23.24 | 0.23 (24 of 100) | 0.02 (5 / 5 of 13 covers) | 0 | 1.0 (7 of 123) | 0.978 (211 / 1053) | - |

## Mutants (state, target value, other gates that failed)

| Final | noop | same_frame_share | near_miss_early | near_miss_late | source_repeats | draft_labels | body_range | body_range_half_show |
|---|---|---|---|---|---|---|---|---|
| 20261001 | unchanged  | killed 0.503 | killed 0.087 | survived 0.056 | killed 1 | killed 0.898 | killed 0.5 | survived 0.917 (+same_frame_share) |
| 20261002* | unchanged  | killed 0.478 | killed 0.132 | survived 0.044 | killed 1 | killed 0.9 | killed 0.5 | survived 0.922 |
| 20261003 | unchanged  | killed 0.467 | killed 0.13 | survived 0.011 | killed 1 | killed 0.898 | killed 0.5 | survived 0.936 |
| 20261012 | unchanged  | killed 0.465 | killed 0.113 | survived 0.014 (+same_frame_share) | killed 1 | killed 0.895 | killed 0.5 | survived 0.953 (+same_frame_share) |
| 20261020 | unchanged  | killed 0.483 | killed 0.083 | survived 0.008 | killed 1 | killed 0.895 | killed 0.5 | survived 0.947 (+same_frame_share) |
| 20261109* | unchanged  | killed 0.504 | killed 0.159 | survived 0.009 | killed 1 | killed 0.894 | killed 0.5 | survived 0.945 |
| 20261110 | unchanged  | killed 0.47 | killed 0.084 | survived 0.024 | killed 1 | baseline fails 0.847 | killed 0.5 | survived 0.921 |
| 20261112 | unchanged  | killed 0.462 | killed 0.104 | survived 0.009 | killed 1 | killed 0.899 | killed 0.5 | survived 0.945 |
| 20261117 | unchanged  | killed 0.465 | killed 0.102 | survived 0.027 | killed 1 | killed 0.899 | killed 0.5 | survived 0.925 |
| 20261118* | unchanged  | killed 0.48 | killed 0.122 | survived 0.049 | killed 1 | killed 0.895 | killed 0.5 | survived 0.914 (+near_miss_covers) |
| 20261120 | unchanged  | killed 0.472 | killed 0.112 | survived 0.019 | killed 1 | killed 0.896 | killed 0.5 | survived 0.935 |
| 20261123 | unchanged  | killed 0.473 | killed 0.08 | survived 0.02 | killed 1 | killed 0.866 | killed 0.5 | survived 0.942 |
| 20261124 | unchanged  | killed 0.468 | killed 0.139 | survived 0.006 | killed 1 | killed 0.899 | killed 0.5 | killed 0.5 |
| 20261125 | unchanged  | killed 0.48 | killed 0.13 | survived 0.02 | killed 1 | killed 0.894 | killed 0.5 | killed 0.5 |
