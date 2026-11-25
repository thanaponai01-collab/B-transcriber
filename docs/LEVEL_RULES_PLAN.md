# Level rules: measured, then planned

Written 2026-11-25. Goal: every cut and timing rule should mean the same thing on every recording,
with its parameters taken from measurement instead of a preset name. This file records what the
prototypes measured, then lists the PRs that are still worth doing.

## Status after building PR 1 and PR 2 (2026-11-25)

Building PR 2 turned up two facts that change the plan below. **PR 2 shipped as a consolidation
with no behavior change.**

| What the plan said | What the data said | What shipped |
|---|---|---|
| Remove the −65/−35 floor clamp | At the ±20 ms check `word_cut` uses, J falls from 67.1 to 44.3 on 20261112 and from 36.6 to 31.7 on 20261109. Those sources have gated silence near −74 dB, so an unclamped floor sits under the room tone between words. | Clamp kept (`levels.FLOOR_CLAMP_DB`), with this reason |
| Point margin +10 (hysteresis 18/10/3) | It won on held-out 20261109 and 20261118 but lost 5 J on held-out 20261002, a YouTube master with a −46 dB floor. The sweep also asked "any quiet window within 40 ms", while `word_cut` and timeline edges ask "every window within 20 ms quiet". | +6 kept (`levels.QUIET`) |
| `hks_cut_check` on the point rule | Its window is ±120 ms. At that collar +6 is best (J 59.0), and the seed changes nothing. | `levels.QUIET` |

Proof that PR 2 changes nothing:

- 0 of 6,678,430 windows and 0 of 6,012 cut and kept-word points change.
- `hks_tighten --check` pooled edge P/R stays at 0.758 / 0.585.
- `hks_cut_check` on the user's 20261124 D1 is unchanged: 182 cuts, 9 visible in speech, 13 same-frame, 6 holds.

**Next experiment, not shipped:** `sweep_level_rule.py --need all --collar 20` asks `word_cut`'s
own question. On the tuning days, grow +16 scores J 70.1 against +6 (ΔJ +25 to +40, CI from
resampling days). All three held-out episodes have been looked at, so it needs a fresh one: an
episode cut by the user alone, with no agent draft under it. The gain-invariant replacement for
the clamp needs the same.

The prototype scripts are throwaway and gitignored, in `output/level_rule_prototype/`:

| Script | What it does |
|---|---|
| `build_points.py` | Builds the dataset as `points.json` |
| `premise.py` | Checks whether a normalization gain changes any decision |
| `sweep.py`, `compare.py` | Point-rule sweep, leave-one-day-out, CIs |
| `seedgrow.py` | Hysteresis in `ingest.sound_runs`' seed/grow form |
| `localfloor.py` | Local versus whole-file floor |
| `pauses_hyst.py` | Pause rules through `hks_tighten --check` |
| `strips.py` | Spectrogram strips at missed edges |

PR 1 turns the sweep into a repo tool.

## Method

- **Positives:** the user's finished YouTube bodies on the 8 HKS tuning days give 2,268 sound edges.
- **Negatives:** the same number of mid-points of words the user kept, each 250 ms or longer.
- **Envelope:** the shared 10 ms envelope from `timeline_transcript.source_levels`.
- **Quiet:** a point is quiet when the rule finds a quiet 10 ms window within ±40 ms, which is one frame at 25 fps.
- **Score:** J = % of edges called quiet − % of kept mid-words called quiet. CIs come from resampling days.
- **Held-out episodes:** 20261109 and 20261118, each scored once with a frozen rule. Their projects have no agent sequences, and no level margin had been scored on them before. 20261002 stays unspent.

## Findings

### 1. A linear R128 gain changes nothing that is floor-relative

The 15 sources measure from −29.7 to −8.6 LUFS. The YouTube masters sit near −10 and the Facebook masters near −23. Each was gained to −23 LUFS:

| Rule | Decisions flipped |
|---|---|
| `timeline_transcript` floor + 6, `quiet_runs` floor + 18 | **0** on 7 sources. The other 8 flip only because the −65/−35 floor clamp binds before or after the gain (their true floors are −64 to −74 dB). |
| ffmpeg `silencedetect` −35 dB (`hks_tighten.silences`, still used by `hks_judge`) | 1.2 % to 20 % of all 10 ms windows |

- The absolute rules are the −35 dB ffmpeg pauses, the ingest denoise gate at −35 dB, the gate-floor clamps at −80/−35 and −55, `sync`'s `MIN_RMS` at 1e-4, and the −65/−35 clamp on the shared floor whenever it binds.
- The full inventory has about 50 rules. None was found in the UXP panel, `subtitle_desk` or the subtitle writers.
- **Decision:** don't add a normalization stage. Remove the clamp, taking p5 of the non-digital windows instead, and move `hks_judge`, the last absolute cut rule, onto the shared envelope. The rules then ignore gain without an extra stage. Record LUFS in the source profile as a measurement.

### 2. A per-source profile can't pay on HKS, and DNSMOS isn't needed for it

| | Floor (p5) | Speech (p90) | Range |
|---|---|---|---|
| 15 HKS sources | −74 to −46 dB | −34 to −8 dB | **37 to 43.5 dB** |

- **Ceiling for any per-source parameter.** Suppose some measurement predicted each day's best margin perfectly. It would beat a fixed floor + 10 by only **1.4 J** (edge-weighted; per day 0.3 to 4.9). That is below the day-to-day spread.
- Anchoring the threshold to the range (floor + 0.25 × range) scores J 68.0. Speech − 30 dB scores 67.4 and floor + 10 scores 67.5. The CIs overlap.
- A local floor (p5 over 5, 15 or 60 s) scores **worse** than the whole-file floor: J 43 to 60.
- DNSMOS was not run. Its model (`sig_bak_ovr.onnx`, from Microsoft's DNS-Challenge repo) is not on disk. It could add at most the 1.4 above on these recordings.
- No non-HKS source has edit gold in a form this harness reads. The 1RaceClub and timing-ruler clips have word-start gold, not cut gold, so the anchors can't be told apart yet.

### 3. One envelope rule: floor + 10 for points, with seed/grow hysteresis for stability

Point question, one-frame collar, 8 tuning days:

| Rule (unclamped floor F) | J | Edges quiet | Kept mid-words quiet | Flips/min | ΔJ, 95 % CI |
|---|---|---|---|---|---|
| Today: clamped floor + 6 | 63.4 | 76.1 % | 12.7 % | 239 | |
| F + 10 | **67.5** | 87.2 % | 19.7 % | 244 | +1.0 to +7.9 vs today |
| Seed F + 18, grow F + 10, ≥ 3 seed windows | **67.6** | | | **132** | −0.1 to +0.3 vs F + 10 |
| Seed F + 14, grow F + 8 | 67.1 | | | 115 | −1.6 to +1.1 vs F + 10 |
| Grow F + 6, any seed | 62.9 to 63.4 | | | 87 to 125 | −7.5 to −1.5 vs F + 10 |

- **The grow (exit) margin sets which points are quiet. The seed (enter) margin sets how often the state flips.** Seed + 18 over grow + 10 gives the same J with 46 % fewer sound/quiet flips. That is the stability hysteresis should buy, here at no cost.
- **Held-out 20261109** (F + 10 frozen): today's rule scores 57.6, F + 10 scores **63.4** (ΔJ +5.8, CI +1.8 to +10.3). Edges called quiet go from 71.4 % to 79.9 %, and kept mid-words called quiet from 13.8 % to 16.5 %.
- **Held-out 20261118** (seed 18 / grow 10 / 3 frozen): today's rule scores 57.0, F + 10 scores 60.7, and the hysteresis rule scores **60.7** with flips going from 267 to 159 per minute.
- **The operating point depends on the collar.** At ±120 ms, F + 10 loses to today's rule (ΔJ −6.9 to −2.4). +10 is right only for consumers that snap within one frame, `word_cut`'s quiet frame and `hks_cut_check`.
- **The cost:** +10 calls 3 to 7 points more of kept speech quiet. J weighs a missed quiet edge the same as a false quiet inside a word, and that weighting is the user's call.
- `timeline_transcript.tighten` (word-edge fitting) was not measured. It keeps its + 6 until it is.

Pause question (`hks_tighten --check`, pooled over 8 days, `hks_score`'s 500 ms boundary tolerance):

| Pauses from | Edge P / R | 0.6–3 s tightening P / R |
|---|---|---|
| Clamped floor + 18 (today) | 0.758 / 0.585 | 0.495 / 0.307 |
| Unclamped floor + 18 | 0.764 / 0.583 | 0.511 / 0.306 |
| Unclamped + 16 | 0.777 / 0.576 | 0.529 / 0.285 |
| Unclamped + 20 | 0.744 / 0.592 | 0.491 / 0.321 |
| Enter + 18 / exit + 6 (clamped) | 0.799 / 0.608 (per-day mean) | 0.538 / 0.296 |

- `PAUSE_DB = 18` holds on the unclamped floor.
- Hysteresis on pauses lands on the same precision/recall curve as a single margin. About 36 gold cuts per day per class is too few to separate them.
- A 500 ms tolerance can't see where a boundary falls, so the point table above is the one-frame evidence.

### 4. What the misses are

Today's rule misses 585 of 2,268 edges. Spectrograms of a sample from 20261120 are in `output/level_rule_prototype/strips_20261120.png`.

- **23 (1 %) sit in continuous sound,** with no window within ±1 s below F + 12. The strips show stacked harmonics with a flat envelope: music or overlapping voices. A dialogue stem could help these, and only these. That ceiling is about 1 % of edges.
- **Most of the rest are cuts in the dip between two words of running speech.** The dip is 30 to 40 dB under the speech peaks but above any floor line. A dip-depth rule ("or ≥ 35 dB under the peak within ±200 ms") does not help: J goes from 67.5 to 67.8, because the dips between syllables of kept words look the same.
- **The ceiling of a pure level rule is about J 68 here.** The rest needs word boundaries from the transcript, which `hks_cut_check`'s word-gap rule already adds. The stem test is not worth a model download for 1 % of edges.

**Speech enhancement stays off the ASR path.** Denoise runs only for chunk engines, and the active engine is whole-file `faster_whisper`, so the −35 dB denoise gate does not run today.

**Presets (`aggressive` / `standard`).** They change `ingest.sound_runs` (seed 15 or 10, grow 6 or 5, minimum 100 or 40 ms) and the VAD and cut durations. Two things follow from the data:

- The level margins in a preset can be replaced by the shared rule. The seed/grow form is the one `sound_runs` already uses, and the measured operating point replaces both presets' margins.
- The duration settings (`min_silence_ms`, pads, VAD gaps) are editing taste, not measurement, and stay as named options.

`sound_runs` feeds ASR chunks, so its move goes through the `cer_thai` harness (PR 5).

### 5. Beyond HKS: 54 sources, 7 shows

`python tools/measure_audio_condition.py --json output/audio_condition/sources.json` (read-only) measured every transcribed source still on disk plus one file each from คชาภา EP33, พุธทอล์ค 234 and CFD 97: 54 sources. Per-day edge scores come from `measure_middle_layer.py --days <day> --reach 40`, saved in `output/audio_condition/edges_<day>.json`. Both ran before PR 2, on the same floor (clamped p5) and the ffmpeg −35 dB rule.

**The −35 dB rule fails on the loud HKS days.** Edges called quiet at ±40 ms, per tuning day:

| Day | Source LUFS | ffmpeg −35 dB | Clamped floor + 6 |
|---|---|---|---|
| 20261001 | −10.4 | **6 %** | 83 % |
| 20261012 | −8.7 | **18 %** | 74 % |
| The other six | −22 to −29 | 60 to 80 % | 62 to 95 % |

On the YouTube-master days, `hks_judge` and `hks_draft` find almost no pauses. This is PR 3's case, measured per day.

**Other shows have a much smaller range** (p95 − clamped floor):

| Show | Floor | Range |
|---|---|---|
| HKS, โหน(หลัง)กระแส | −49 to −65 dB | 33 to 48 dB |
| คชาภา (4 sources) | −36 to −41 dB | **19 to 30 dB** |
| BeamOil (2) | −32 to −40 dB | **22 to 27 dB** |
| CFD (1) | −47 dB | 26 dB |
| 1RaceClub raw recordings (8 of 9; the ninth, 2026-11-21 10-55-45, has a floor of −43 dB and a range of 21 dB) | −77 to −85 dB unclamped | 40 to 49 dB |

- `QUIET` and `PAUSE` were tuned on HKS's 37 to 44 dB range. On a 19 to 27 dB range, floor + 18 sits near speech. This meets the reopen condition for per-source parameters below, except for the edit gold. No คชาภา, BeamOil or CFD cut is in a form the harness reads yet.
- **The clamp binds on 22 of 54.** It lifts 1RaceClub raw floors 12 to 20 dB above the room. On BeamOil the true floor (−31.7) sits above −35, and the clamp pulls it down. The clamp stays for now (see the status at the top).
- **5.1 sources:** 4 of the 5 sources on 20261112 have 6 channels. `ingest._load_audio_av` averages all channels (`mean(axis=0)`), which dilutes centre-channel dialogue. 20261112 also has the highest rate of kept mid-words called quiet (26 % vs 9 to 18 %). This is a hypothesis and has not been tested.
- **The same 8 1RaceClub raw recordings** have a loudness range of 9 to 19 LU (HKS: 5 to 12). Between 50 and 74 % of their windows sit below floor + 6.

## PRs

Landing order: 1 → 2 → 3 → 5. PR 4 is independent and branches from trunk.

### PR 1. Level-rule sweep tool (the lever)

- [ ] Depends on: none
- [ ] Files: `tools/sweep_level_rule.py` (new), `tests/test_sweep_level_rule.py` (new)
- [ ] Change: builds the dataset and sweeps seed/grow margins, anchor and minimum seed. It scores J, flips per minute and boundary distance at a given collar, with leave-one-day-out selection and a day bootstrap. `--holdout DAY` scores a frozen rule once.
- [ ] Unit: on a synthetic envelope with planted edges, J and the flip count match hand-computed values.
- [ ] Live: a rerun reproduces this file's tables: J 63.4 / 67.5 / 67.6 on the tuning days, 57.6 / 63.4 on 20261109, and 57.0 / 60.7 / 60.7 on 20261118.
- [ ] Perf: a full sweep takes under 10 minutes on cached envelopes (baseline: the prototype, about 4 minutes).

### PR 2. One floor, one quiet function (`transcribe/audio/levels.py`)

- [ ] Depends on: PR 1
- [ ] Files: `transcribe/audio/levels.py` (new), `cutdeck/timeline_transcript.py`, `cutdeck/word_cut.py`, `cutdeck/hks_cut_check.py`, `cutdeck/hks_tighten.py`, and their tests
- [ ] Change: `levels.py` holds the envelope, the profile, `sound(levels, profile, seed_db, grow_db, min_seed)` and `quiet_runs`. The floor is p5 of the non-digital windows, with no clamp. The named operating points are `POINT = (18, 10, 3)` and `PAUSE_DB = 18`. `tighten` keeps + 6. The profile (floor, speech p90, LUFS) is cached next to the `.npy`, keyed by sha256 plus a version.
- [ ] Unit: `python -m pytest tests -k "timeline or word_cut or hks or levels"` and `node --test tests/*.cjs` pass. A gain added to a synthetic envelope changes no decision.
- [ ] Live: `verify-cutdeck` runs `cut_words` on a scratch copy of a 5-minute range. No cut lands inside a word, and the cut count is reported against trunk.
- [ ] Perf: `hks_tighten --check` pooled edge P/R stays within 0.01 of 0.764 / 0.583. PR 1's tool gives J ≥ 67 on the tuning days. Fail if J < 66.
- [ ] **Review-gated:** +10 changes where `word_cut` places cuts. It needs the user's yes on the trade-off of 3 to 7 points more kept speech read as quiet.

### PR 3. `hks_judge` off ffmpeg −35 dB

- [ ] Depends on: PR 2
- [ ] Files: `cutdeck/hks_judge.py`, `cutdeck/hks_tighten.py` (delete `silences`, `NOISE_DB` and `--quiet ffmpeg`), `tools/measure_middle_layer.py`
- [ ] Change: the last absolute cut rule moves to `levels.quiet_runs(…, PAUSE_DB)`.
- [ ] Unit: the existing `hks_judge` tests pass.
- [ ] Live: diff `hks_judge`'s output on the 8 tuning days against trunk. The PR body explains every pause that moved.

### PR 4. Spectrogram strips at disputed boundaries

- [ ] Depends on: none
- [ ] Files: `tools/disputed_edges.py` (new, from `strips.py`)
- [ ] Change: for each edge where two rules disagree, it writes a strip (spectrogram, envelope, both thresholds, the edge) and one HTML index.
- [ ] Live: run on 20261120, open the index, and check that each strip's red line sits at its edge time.

### PR 5. `ingest.sound_runs` on the shared rule; presets lose their margins

- [ ] Depends on: PR 2
- [ ] Files: `transcribe/pipeline/ingest.py`, `transcribe/config.yaml`, `transcribe/config.aggressive_cut.yaml`, `cutdeck/contracts.py`
- [ ] Change: `sound_runs` calls `levels.sound` on its 20 ms windows with the measured margins. `sound_guard_db` and `sound_guard_tail_db` leave both presets, while duration settings stay.
- [ ] Verify: `python -m transcribe.eval.harness` shows no gated regression in `cer_thai`, `wer_latin` or either boundary rate. A rough-cut run on the 2026-10-12 news clip keeps 0 audible windows inside cuts.

## Not planned, and what would reopen it

| Item | Why not now | What would reopen it |
|---|---|---|
| R128 normalization stage | Measured no-op for floor-relative rules | An absolute rule that has to stay absolute |
| DNSMOS-driven parameters | Ceiling of 1.4 J for any per-source mapping on HKS. Model download needed. | Edit gold on recordings with a different range, plus the user's OK to download |
| Dialogue-stem test | Ceiling of about 1 % of edges. Separator download needed. | Footage where music beds hold most of the misses (game audio, 1RaceClub) |
| Dip-depth rule | No gain (67.5 → 67.8) | None. The fix for those edges is word boundaries. |
| Speech enhancement on ASR | Not on the path today | A `cer_thai` A/B that shows no harm |
