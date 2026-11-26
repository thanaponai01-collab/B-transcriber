---
name: overnight-study-2026-11-23
description: Overnight self-study of every HKS day folder (night of 2026-11-23): what was read, blockers, questions for the user
type: fact
status: current
updated: 2026-11-23
---
The user asked (2026-11-23, before sleeping) for the agent to learn from their finished โหนกระแส cuts,
starting with `1 YOUTUBE D1` of 20261123 open live, then every HKS day folder, and to log what it
learns. Findings per episode are in [../study/](../study/README.md). Nothing learned that night is
**confirmed**; every point is **seen** (read from the cut) or **guess**.

**Method:** `prproj_reader` + `timeline_transcript` offline for every folder; `read_timeline` and
`export_frame` live only for 20261123 (the open project). The `reverse-engineer-anything` skill
(REA) was loaded as asked; it is for binaries and apps and has no Premiere route, so only its
method was used: question checklist, evidence ledger, observation / inference / unknown kept apart.

**Blockers met:**
- `read_timeline` returns no clip label colour (`colorLabel` is read in `uxp/cutdeck/host/sequenceRead.js`
  only for project items; every clip came back `null`). Label colours could not be studied.
- Two sequences share the name `1 YOUTUBE D1` in 20261123 (one empty), so `read_timeline` by
  name refuses; read the active sequence instead.

**Done that night:** studies of 9 daily YT cuts (1001, 1003, 1012, 1020, 1110, 1112, 1117, 1120, 1123)
and the EP.167 compilation (its 4 source videos transcribed, jobs in the shared store); the
synthesis and 10 candidate principles (`HKS-1`–`HKS-10` in [../principles.md](../principles.md)); a
blind predict-then-score test on the holdouts (1002 / 1109 / 1118, [../study/holdout/](../study/holdout/));
one patched draft, now `agent v6 (study) of YT D1`, in the 20261123 project (last saved 2026-11-24 00:31,
unrendered, the active timeline; the user's D1 verified unchanged on disk). Never name a study copy
`1 YOUTUBE…`: `hks_gold` then refuses the day's gold (two different non-empty YT cuts). The emptied
`1 YOUTUBE D1 agent v6 (study)` is left for the user to delete.

More blockers:
- `open_sequence` refuses `1 YOUTUBE D1` (two sequences share the name) and `Window > Timelines`
  is not in `list_menu`, so the agent could not switch Premiere back to the user's D1.
- 20261112's footage is five files; `study_episode.py` reads keeps against one, so its topic labels
  and kept share are wrong (the 1112 study re-matched every piece by its words).
- 20261002 has no `hks_judge` lines; its transcript is `test_projects/hks_words/20261002/*.words.json`.
- EP.168 (20261111) has footage only, no edit: its 4 videos were transcribed and the agent wrote a
  paper edit ([../study/20261111-ep168-paper-edit.md](../study/20261111-ep168-paper-edit.md)) for the user to judge.
- A folder glob `20261111*` also matched `20261111 - คชาภา EP38` (another show): its videos were
  transcribed by mistake (cached in the store, harmless). Match HKS folders by name, not date.
- Holdout tests were only partly blind: the study README's numbers row for each holdout was read first.

**Short forms:** studied after the first report: every day's FB and 1-min mapped onto its YT cut
([../study/shortform.md](../study/shortform.md), HKS-14/15). The 3-min reel and `4 REEL SIZE` are
the FB and 1-min nested in the reel frame (workflow-log Steps 7–8), so they need no separate study.

**Labels and joins:** clip label colours read offline from every project ([../study/labels.md](../study/labels.md):
ORANGE is the YT ending 7/7, YELLOW is the short-cut pool); every uncovered join frame-checked
([../study/joins.md](../study/joins.md): 343 of 345 have no visible jump).

**Not covered:** rendered frames of other episodes' sequences (they were not opened; joins were checked
from source frames instead);
EP.168 is built as an FCP7 XML with the show sting, whooshes and BGM in its day folder
(`CutDeck\EP168 agent draft.xml`). Import was proven live 2026-11-24 (141/141 clips, nothing offline,
frames rendered) and then undone, so it is not in any project. v6 is render-scanned (388 frames, none
bad) and its BGM loop joins are fixed to the user's 56.48 s splice (saved 00:27). Nothing was heard by ear.
Gotcha: `helper_protocol.ask` is synchronous; a stray `await` ran an import twice.
**Second pass (2026-11-24, after the stop hook):** the last HKS sources were found and studied: the
show's master kit `รวมโหนกระแส` ([../study/template.md](../study/template.md)) and a 20260929 episode that
lives only as a collected copy in `E:/Me/7.test folder` ([../study/20260929-yt.md](../study/20260929-yt.md):
its `topic cutting` pass shows the labelled-topic selection step). The other `.prproj` files under the
assets folder are stock templates (Envato, Mixkit) or the SFX bin, not episodes. EP.168 now carries
covers for its 3 jumps, the compilation show's cards, lower thirds, glitches and end screen
(import-tested and undone). v6 was renamed `agent v6 (study) of YT D1`, snapped to its **25 fps** grid
(my 0.5333 s shift was 30 fps frames: 344 clips sat a third of a frame off; now 0, shift 0.52 s), and
every edit point render-checked: 8 flags, all the user's own cuts inside CCTV/phone footage or the
known masked three-shot jump. Gotchas: read `ticks_per_frame` before any ripple; never name a study
copy `1 YOUTUBE…`; `edit_clips` batches can refuse a clip id mid-list, so edit one track per call.
**Third pass (2026-11-24):** a drive-wide `*.prproj` search (G, E, F, D, H) found two more HKS
episodes outside `G:\Me\Works`: EP.162 (20260928, a themed compilation; transcribed, jobs 108–111) and
the 20260929 advice day; both studied, with the coverage table in [../study/README.md](../study/README.md).
The hook's headline cards of all 13 days were read straight from each day's `.aep` (UTF-16 text
layers) into [../study/headlines.md](../study/headlines.md). New candidates HKS-16 to HKS-19. Facts proven
live are in `docs/PREMIERE_FACTS.md` ("FCP7 XML import and timeline edits"). Blocked and left: hearing
audio; the After Effects MCP (no `AE_MCP_EXE`); hook-stack and film-damage layers in XML (adjustment
layers and blend modes). Nothing was committed; all changes are in the working tree
(`projects/hks/principles.md`, `README.md`, `memory/`, `study/`).

**Fourth pass (2026-11-24):** the three "blocked" items were worked through. (1) **Title card done:**
After Effects is reachable without the MCP: `AfterFX.exe -r <script.jsx>` (2027, the only installed
version; the `2026` folder is leftover plugins) runs the script in the one running AE instance, which
had no project open (checked first with a read-only probe). EP.162's card is the episode thumbnail PSD
animated, with `t1` / `t2` / `g1.png`; EP.168's set already existed, so the agent built
`CutDeck\EP168 agent title card.aep` by swapping sources, rendered it with `aerender` (Thai paths
in its arguments fail: render an ASCII-named copy) and placed the .mp4 in the gap of the dressed draft (20261123 project). `CompItem.saveFrameToPng` wrote nothing. (2) **Hook stack and film damage:** not in EP.162, but EP.167 puts them on its 2.84 s end tail under
`CG BG` (first logged as "not needed" from EP.162 alone; corrected). Both compilations mark every edge
with glitch + a 1–2 frame Invert flash. All of it is now in `EP168 agent draft (dressed v4)`, built by
`output/hks_study/ep168_dress.py`. (3) **Bugs found and fixed:** XML glitch clips imported Normal and
blacked out every edge (Screen needs Opacity [1]=22 and [2]=10; the XML now writes
`<compositemode>screen</compositemode>`); a fixed paste parking spot (905 s) fell inside a longer build
and damaged its end (park at end + 30 s). (4) **Listening** via `timeline_transcript`: 34 cuts went
through words; snapping now uses audio-tightened words (0 left), and nine paper-edit pieces that
stopped mid-clause were re-ended by hand. (5) The episode's theme is on its thumbnail: "รวมเคสรักเขา
จนหมดใจ / สุดท้ายกลายเป็นเหยื่อ?". Stale study sequences (`EP168 …` x4) are left empty for the user to delete.
**Fifth pass:** answered my own `CG BG` question from EP.167's exported .mp4 (it is Screen; set on v4).
Measured the mix with ffmpeg EBU R128 against EP.167's export: the user lifts a quiet source +3 dB;
applied to EP.168's three quiet files. Blur boxes copied but disabled (they hit set wall, not logos).
Coverage: every HKS project is studied except the three holdout days (1002, 1109, 1118), kept unseen
on purpose for evaluation ([holdout-episodes.md](holdout-episodes.md)).
**Sixth pass:** the three holdout days (1002, 1109, 1118), scored blind on 11-23, now have full studies
(`study/20261002-yt.md`, `20261109-yt.md`, `20261118-yt.md`); their findings are added under HKS-2, 12, 13, 14, 19. The EP.168
case-title spec (font, sizes, fade, positions, the four titles) is in the EP.168 study.
Gotcha: an `AfterFX.exe -r` script that errors can leave a modal; after that, `-r` stopped running
scripts (launcher hangs 120 s). Use `try` around every render-queue call and never `renderQueue.render()`
inside `-r`; render with `aerender`.
**Seventh pass:** case titles placed on v4 (After Effects → alpha PNGs → V9 with the user's fade). The
AE route was unblocked: the windowless AfterFX is Premiere's Dynamic Link engine (closing it, it
restarted at once, and Linked Comps still render); `-r` hands scripts to it and it never runs them.
`AfterFX.exe -m -r` starts a separate instance; after killed instances it first shows "Crash Repair
Options" (Continue = Enter). Render with `aerender`; for alpha use the "TIFF Sequence with Alpha"
template (PNG has no template; `setSettings` Format is read-only), then `ffmpeg -pix_fmt rgba` to PNG,
because AE writes the TIFF alpha as "unspecified" and Pillow drops it.
**Eighth pass:** found the draft's framing was wrong: compilations play footage at 56.25 % (letterboxed),
not 100 % as template.md said. Fixed on v4 and in the build; the template blur boxes then land on the
broadcast logos (render-checked), and the banner bleed disappears. Lesson: read the scale of the main
footage from the user's own sequence before copying a layout, and compare a rendered frame with the
user's export.
**Ninth pass:** rendered v4's audio offline (ffmpeg `amix` of every enabled clip at its Volume Level)
and measured it against EP.167's export. The balance is in the user's range (case spread 2.9 LU vs
3.9), but the +3 dB rule clipped: 2,588 full-scale samples vs EP.167's 1, because the boosted broadcast
files already peak at 0 dBFS. Nine clips capped live (most gain that keeps -1 dBTP, never below 0 dB):
2,588 → 91. Voice/bed stems measured (hook voice 6 LU over the bed; end-tail bed 2.4 LU under the last
line). Open: EP.168 is 2.3 LU quieter overall than EP.167. Render for the user: `output/hks_study/ep168_v5_mix.wav`.
Gotcha: ffmpeg `apad` before `atrim` in one chain ran without end and filled drive C (87 GB); deleted.
Lesson: check a clip's true peak before raising it; measure in float, since a 16-bit render hides overs.
Still open: hearing the mix by ear (no audio playback for the agent; measured against EP.167 instead).

**How to apply:** the user answered the study's questions on 2026-11-24 (HKS-C1 to C12 in
[../principles.md](../principles.md); rules 1–6 rewritten). Other study points are still candidates: ask
before turning one into a rule. Open: 1012 A-TECH (evidence or ad), HKS-C10's exceptions.
Related: [[yt-20261123-lessons]], [[gold-reading-gotchas]], [[holdout-episodes]]
**Tenth pass (loop 2):** all 16 studies re-read against principles.md by four parallel readers; the claims
that would change a rule or the draft were checked by hand. Seven candidate principles were added
(HKS-20–26), and HKS-1, 2, 4, 6, 10, 14, 17 and 19 were weakened where the evidence disagrees; the full list
is the "Pass 2" section of principles.md. Four "checks for any agent cut" (cards paid off, question
triggers, stakes within 60 s, long picture-less stretches) and the EP.168 v6 list are in the EP.168 study.
`joins.md` gained a scope note (studio-picture joins only).
EP.168 audio: the loudness step is scripted in `ep168_dress.py`; the Hard Limiter was probed live
(`add_effect` works, its params are on an unknown 0–1 scale; PREMIERE_FACTS) and left bypassed on
`EP168 agent draft (dressed v5 limiter)`, a copy of v4.
**Eleventh pass (loop 3):** built `EP168 agent v6 (paper edit)` from the pass-2 review: a 19.3 s clash hook from
case A, ~20 s of the host's restatements cut, D ending on the host's verdict. No cut through a word; all 10 new joins
are camera changes. Lesson: cut at a speaker change and the broadcast's own camera switch hides the join.
**Twelfth pass (loop 4):** dressed v6 as `EP168 agent v6.2 (dressed)` (script + layer port, frame-checked). Found a
build bug (hook end hard-coded to the third piece). Two re-run traps logged: a failed dress leaves its import
behind (guard added), and stale script objects after `build_sequence` steps (reload_panel). Case C has no
other side to use.
**Thirteenth pass (loop 5):** measured the pass-2 checks on all 15 user cuts (`hks_story_checks.py`): "stakes
within 60 s" refuted (4 of 15 exceed it); piece length is the real gap. Built v7 (median 11.0 s vs the user's
8.1–10.1). One drop made a same-shot jump (reverted in the build). Then the CutDeck panel dropped after a reload
and did not come back: live work stopped there; the user must reopen the panel and save.
**Morning (2026-11-24):** Premiere crashed; the user reopened it and the panel. v7 survived; the jump cover is
applied and saved (frame-checked). The user gave a standing OK to kill and restart Premiere and reopen CutDeck
after a crash: `output/hks_study/premiere_recover.py` (menu route proven, restart route not yet run).
**Loop 7 (2026-11-24):** Hard Limiter scale read off Effect Controls (Max Amplitude dB = −100·(1−v), Input
Boost dB = 150·v − 100; PREMIERE_FACTS). Ran the name / question checks on v7: the accused was named only in the
last 30 s; `EP168 agent v7.1 (dressed)` keeps the host naming him at 686.7 (patch on a copy, listening-checked).
**Loop 8:** measured the 2022 compilations offline (media gone, timings kept): kept share 23 % as in 2026; pieces 1.5–6.4 s vs 8–10 s now. Logged in study/README and principles.
 (not a correction)