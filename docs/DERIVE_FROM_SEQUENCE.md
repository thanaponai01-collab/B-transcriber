# Derive from a sequence, don't rebuild

Status: design, 2026-11-24. Nothing here is built yet. Each tool row says LIVE (proven in
Premiere, row in `docs/PREMIERE_FACTS.md`) or unproven.

## Goal

The agent edits the way the user edits. One sequence holds the work of a stage. The next stage
starts from a copy of it in Premiere and picks pieces from there. The agent never goes back to the
source files or a plan to rebuild what a sequence already holds. So a fix the user makes by hand
on a sequence carries into everything cut from it, and the user can fix any agent draft on the
timeline.

## What goes wrong today

1. **Rebuild from source.** `plan_pieces` → `build_sequence` places clips from the footage files.
   `like {kind, track, start_ticks}` places a base item's media again with fresh in/out. Both
   start over. They drop every effect, mask, label and hand fix that the parent sequence had.
2. **FCP7 XML came back.** EP.168 (20261111) was built as `CutDeck\EP168 agent draft.xml` by
   `output/hks_study/ep168_build*.py`. They are gitignored scratch scripts that write xmeml by
   hand. `projects/hks/build-plan.md` allows XML only as an unproven fallback. The
   `patch-drafts-not-rebuild` memory was written the same day, and the rule in text did not stop it.
   Why the run chose XML (inferred, not stated in the log): the 20261111 project was not the open
   project, and `build_sequence` refuses any project but the open one. XML was the way round that.
3. **Reorder is hand arithmetic.** Moving blocks on a copy means writing the clone/lift swap
   recipe by hand (`build_sequence` description). That is slower than a scratch script, so the
   agent writes a scratch script.
4. **No route to pull one piece from another sequence.** "Take this insert from `backup`" or "take
   question 3 from the split sequence" has no command. Menu Copy/Paste works, but it is four
   calls with catches.

## The chain

The user's day, as stages. Each one is cut from its parent, never from the footage.

| Stage | Parent | How the agent makes it | Route status |
|---|---|---|---|
| `Editing` (whole broadcast) | footage | user, or `create_sequence` from media | LIVE |
| Transcript | footage files | `hks_day` (`hks_words`) once per file; `timeline_transcript` maps it onto any sequence | LIVE |
| Split (razored at each question, one label colour per question) | `Editing` | user; agent draft with `cut_copy` + `hks_day` markers | LIVE |
| `backup` (insert pool) | `Editing` | user; agent pastes into it | menu Copy/Paste LIVE |
| `1 YOUTUBE D1` | Split + `backup` | copy of Split, keep and reorder questions, paste inserts | **gaps 3 and 4** |
| Draft vN+1 | draft vN | `duplicate_sequence` + `edit_clips` / `set_param` | LIVE |
| FB 1080x1080 | `1 YOUTUBE D1` | `cut_copy` / `keep_words` + `settings_from` | LIVE |
| REEL 3M / 1M | FB or YT | `keep_words`, then nest in the reel frame (`place_media`) | LIVE |
| Compilation (โหนหลังกระแส) | finished YT sequences or their exports | copy pieces from each YT sequence; exported .mp4 only when no sequence exists | **gap 4** |

Every derive reads the parent **live** at the moment it runs, not a cached plan. So the user's
fixes on YT reach FB and the reels.

## What to build

Smallest first. Each step ends in its own check.

### 1. Probe `Sequence.createSubsequence` (Rule 2: typings only)

`Sequence.createSetInPointAction`, `createSetOutPointAction` and `createSubsequence` are declared
in `reference/adobe/api/premierepro.txt` and have no `PREMIERE_FACTS` row. They are Premiere's own
Make Subsequence: a range of a sequence becomes a new sequence with real clips, effects and every
track. If they work, "pick question 3" is one call.

**Done, LIVE 2026-11-24.** On the scratch sequence, In 1 s / Out 4 s gave `<name>_Sub_01` in
56 ms. Every track came across, edges frame-exact, Scale and Gaussian Blur kept. Its frame is
pixel-identical to the parent's at the same moment. One Undo removes it. Row in
`docs/PREMIERE_FACTS.md`; now the `make_subsequence` command. Still untried: keyframes cut mid-clip,
transitions at the edges, clip label colours. So "pick question 3" is: set In/Out on the split
sequence, make the subsequence. Step 3 can paste from it, so a range mid-clip needs no
`cut_copy` scratch.

### 2. `arrange`: reorder blocks on a copy by order, not arithmetic

Input: the copy's name and the wanted order of its blocks (`[[from, to], ...]` in sequence ticks,
on clip edges, as `keep_words` or `cut_copy` leaves them). A pure planner turns the order into the
clone/lift steps that `build_sequence into` already runs (LIVE). It uses clone, never
`createMoveAction` backward, which renders black (FACTS).

**Done, LIVE 2026-11-24** as `premiere_arrange {sequence, result_name, blocks}`. It makes the copy
itself, so the source is never edited. The blocks must cover one stretch exactly, and it refuses
any clip that crosses a block edge before it copies anything. Three pieces played 3, 1, 2 read
back exact with the cover's Scale kept, frames pixel-identical to the source.

### 3. `paste_from`: one piece of another sequence into this one

Input: a source sequence and range, a target sequence, the time and the track. It wraps the LIVE
menu route (`select_clips`, Edit > Copy, focus target, park the playhead past the end, Edit >
Paste, then `build_sequence` clone to the place and lift the park). Known catches, all in FACTS:
paste lands on the lowest targeted track, overwrites at the playhead, and must park past the end.
If step 1 works, a range mid-clip becomes a subsequence first. Otherwise it is a `cut_copy` to a
scratch sequence first.

**Done, LIVE 2026-11-24** as `premiere_paste_from {source, in_ticks, out_ticks, target, at_ticks,
v_offset}`. It makes a subsequence of the range, copies and pastes it 30 s past the target's end,
clones it into place (overwriting), lifts the park and deletes the piece. It reads back where the
paste landed and corrects for track targeting. A 1–4 s range with a blur and a Scale-50 layer
landed frame-exact with both effects. Still untried through this route: a masked insert from a
real `backup` (the menu rows in FACTS carry masks and Lumetri), keyframes cut mid-clip.

### 4. Pieces by question, read from the user's split sequence

`read_timeline` returns no clip label colour (the UXP typings have colour labels on project items
only). `prproj_reader` reads clip labels from the saved `.prproj` (`study_labels.py` did it for
every HKS day). A question is one run of same-colour clips between razor cuts on the split
sequence. The reader returns each question's range in sequence time, its colour (who is asked)
and its words from the day transcript.

**Done 2026-11-24** as `python -m cutdeck.split_pieces --prproj <day>.prproj --sequence Editing`.
Seen on the real splits: every keeper on V2 is one razor piece with one colour, and drops stay on
V1 (slot 14, the default). So a question is one V2 clip, not a run of clips. It prints each
question's timecode, length, colour and meaning, whether a drop came right before, and its
opening words from the stored transcript. Its `from_ticks` / `to_ticks` go straight into
`paste_from` and `arrange`. On 20261123 `Editing` it found the 22 V2 pieces in 1.4 s; 20261120
`Edit` reads too. It needs the project saved, because Premiere gives a panel no clip labels.
Not checked against `hks_day`'s `questions.md`, which is the judge's grouping, not the user's.

### 5. Make the rebuild routes hard to reach

- A Claude Code `PreToolUse` hook that refuses a Write or a script that writes `<xmeml` into a
  day folder. The memory alone did not hold.
- `build_sequence` with `media` items refuses when the named base has a parent in the chain
  (open question: how the tool knows. A name prefix, or a note next to the project).
- When the day's project is not open, the agent asks the user to open it and waits. It never
  writes an XML in its place.
- `cutdeck/honekasae_export.py` is the older story-pipeline FCP7 export, with tests. Retire it,
  or keep it for that pipeline only.

### 6. One timing source for words (check)

`word_align` now re-times word starts and ends in the pipeline (commits `4663647`…`31edfc6`).
`timeline_transcript` fits word times to the audio on its own (`fitted` in
`cutdeck/timeline_transcript.py`). If both run, a derived cut can land on the second fit, not
the measured one. Check which one `keep_words` and `paste_from` edges use, and keep one.

## Decisions for the user

1. **Stage names.** What do you call the split sequence and the sequences after it? Fixed names
   let every tool find a parent without asking.
2. **XML.** Block it with a hook (hard stop) or keep it as a rule (soft)?
3. **Order.** Steps 1 → 2 → 3 first (they remove the rebuilds you see), then 4, 5 and 6?
