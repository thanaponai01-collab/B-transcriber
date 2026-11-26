---
name: hks-handover
description: "HKS handover rules from the rule registry. Load when an HKS (โหนกระแส) draft is built and checked, before telling the user it is ready: it lists the handover's own rules and how every do-confirm answer is sent to `premiere_hks_handover`."
---

GENERATED from projects/hks/registry by tools/hks_registry_build.py; do not edit.

# HKS handover: rules and do-confirm

The 29 active `handover` rules in [the registry](../../../projects/hks/registry/rules/). A gate id names the `hks_gates` check that measures the rule.

- **HKS-C13** **Every promise is kept.** Whatever the hook, a headline card or the host raises is answered in the cut, or left open on purpose. Why: an unanswered question reads as a mistake.
- **HKS-C14** **The middle is re-hooked.** No stretch of about 3-4 min without a new picture, a host question or a turn. A turn said aloud counts; one picture held a long time is fine. Why: that is where viewers drop off.
- **HKS-C19** **Challenge the user's cuts.** In every draft, say where the agent would hook harder, where an explanation or a B-roll piece runs long, and where a cut lands snappy or clips a word at a camera switch.
- **HKS-X18** **Check: promises.** Every question from the hook, the cards and the host is answered, or open on purpose (HKS-C13). Listed in the handover with timecodes.
- **HKS-X19** **Check: middle.** No stretch of about 3-4 min without a new picture, a host question or a turn (HKS-C14).
- **HKS-X20** **Check: strongest lines.** Each side's single strongest line, named, and kept (HKS-C15).
- **HKS-X21** **Check: ending.** If the story is open, the last line says so (HKS-C16).
- **HKS-X22** **Check: challenge notes.** Challenge notes (HKS-C19): where the hook could hit harder, where an explanation or B-roll runs long, where a cut is snappy or clips a word at a camera switch. Snappy cuts: `output/hks_study/sliver_check.py` lists every shot under 0.4 s at an edit point; look at the frames before calling one.
- **HKS-X32** **Export when asked, with the command.** Export when asked: `python -m cutdeck.honekasae_export "<day folder>"` (one command; picks the same-named copy with content, queues all four in AME). Not hand-rolled `export_sequence` calls.
- **HKS-X38** **Check visible studio edges in speech.** Before handover, list every visible studio edge that sits in running speech (`python -m cutdeck.timeline_transcript ... --json`, `cuts_in_sound`) and look at each one not under a cover. Count the sound cuts that are also picture cuts on the same frame. The user's 20261124 body had 30 of 180. (gate `visible_cuts_in_speech`)
- **HKS-X67** **I trusted my own measure first.** Any new check runs on the user's finished cut first and on my draft second. It's kept only if it separates them, or it's kept as a list to look at and said to be one (like hks_cut_check).
- **HKS-X70** **I left (FAILED) copies.** After a panel error, save, `reload_panel`, read back, finish the remaining steps, and list any failed copy in the handover for the user to delete. Never delete it myself.
- **HKS-X82** **Every headline card is paid off in a guest's voice.** Every headline card is paid off in a guest's own voice in the body (unpaid: 1002 card 2, 1109 card 2, 1118 card 4).
- **HKS-X83** **Every host question has its trigger; every late name is set up.** Every question the host asks has its trigger in the cut, and every name in the last minute was set up earlier. Run this check on the pieces before dressing.
- **HKS-X85** **Piece length is measurable.** Median piece 1.8-5.6 s on the 13 dailies, 8.1-10.1 s on the 2026 compilations; target for a compilation draft a median near 8-10 s. A compilation keeps about 19-23 % of its sources. Match the year's style the user is cutting in now.
- **HKS-X86** A long stretch with no new picture (5+ min) is where viewers are likely to drop off.
- **HKS-X87** **A failed gate opens the handover.** Each line is a gate. If a gate fails, fix it. If I can't fix it, the handover opens with that gate's name and what's still broken. A failed gate is never handed over quietly, and lack of time is not a reason to skip one.
- **HKS-X92** Read the last words of every piece out loud. Each one is a finished sentence that lands, not just a pause: no "...คือ", "...ก็", "...แล้วกันพี่", no question left hanging. `hks_cut_check` finds pauses, not finished thoughts. A clean result there doesn't mean the endings are finished. (gate `visible_cuts_in_speech`)
- **HKS-X93** No source played twice. Two pieces next to each other must not overlap in source (repeated words). (gate `source_repeats`)
- **HKS-X94** Same-frame sound and picture cuts: few. `hks_cut_check` gives the count. Your 20261124 YT body: 12 of 173. My 20261125 v1: 31 of 39. Every jump to another speech in the same studio scene gets a cover: insert, B-roll or a still person from `Backup`. (gate `same_frame_share`)
- **HKS-X97** **A passing check is not the rule.** I treated a passing check as the rule. The cut check passed on pauses, so I called the endings finished without reading them.
- **HKS-X99** **A known failure is not handed over.** I saw the check say 79% same-frame cuts and handed over anyway. You were waiting, so I chose speed and didn't say so plainly. That was cutting a corner.
- **HKS-X102** Test a check on the user's finished cut before trusting it (agent, HKS 2026-11-25; guess). A check is kept if it separates the user's cut from the agent's; otherwise it's a list to look at, and the handover says so.
- **HKS-X103** **Late draft policy: label.** A failed control may reach the user only if the handover opens with its id and value (late_draft_policy "label", decided by the user 2026-11-25).
- **HKS-X104** **Override policy.** Agent or user may override a gate, each with a written reason (--override GATE="reason" --by <who>); every override is a line in overrides.jsonl and must be named in the handover (decided by the user 2026-11-25).
- **HKS-X107** ****Check the length before handover; cut what the story can lose.**.** Check the long form's length before handover: over 20 min, cut the pieces least worth it in the story (asides, a point told twice, feelings that move nothing) until it is in 17-20 min. On 20261126 I handed over v1 at 23.2 min, and the user said: "check the length again. It's above 20 minutes. So cut something that you think is not worth in the story".
- **M-2** **The user exports.** The agent never runs an export or queues Media Encoder unless asked. For HKS the user asked for `python -m cutdeck.honekasae_export` to queue and start the export (guess: the rule is "no export unless the user asks"); on 2026-11-24 and 2026-11-25 the agent exported only when asked, and only what had changed.
- **M-5** **Check the frame before handing over.** For every piece, look at what the frame actually shows (a reframed 16:9 source loses its edges). A cut that's right on time can still show nothing. (Confirmed on 1RaceClub; applying it beyond Shorts is a guess.)
- **M-6** **A correction isn't learned until it's a gate.** Every correction from the user goes three places the same day: memory (what happened, with numbers), principle (the why), gate (how it's checked before handover: a script if countable, a reviewer question if judgment, a first step if order). A failed gate is never handed over quietly: the handover opens with it. Time pressure is not a reason to skip a gate.

## Do–confirm

Each question needs a written answer in the handover, keyed by its rule id.

1. **HKS-C13** List each promise and where it is answered (timecode) or left open on purpose.
2. **HKS-C14** What is the longest stretch without a new picture, host question or turn?
3. **HKS-C19** Where would you hook harder, what runs long, and which cuts are snappy or clip a word?
4. **HKS-X18** List each question the hook, cards and host raise, and where each is answered (timecode) or left open on purpose.
5. **HKS-X19** What is the longest stretch with no new picture, host question or turn (timecodes, length)?
6. **HKS-X20** What is each side's strongest line, and where is it in the cut (timecode)?
7. **HKS-X21** Is the story open, and if so which last line (timecode) says so?
8. **HKS-X22** Where would you hook harder, what runs long, and which cuts are snappy (sliver_check list, frames looked at)?
9. **HKS-X32** Did the user ask for the export, and was honekasae_export the command used?
10. **HKS-X67** For each new check used, what did it give on the user's finished cut and on the draft?
11. **HKS-X70** Did any panel error occur, and which (FAILED) copies does the handover list?
12. **HKS-X82** For each headline card, which guest line in the body pays it off (timecode)?
13. **HKS-X83** Does each host question have its trigger in the cut, and is every name in the last minute set up earlier?
14. **HKS-X85** What is the draft's median piece length and kept share, against the target for this kind of cut?
15. **HKS-X86** What is the longest stretch with no new picture (timecodes)?
16. **HKS-X87** Which gates failed, and does the handover open with each one's name and what is still broken?
17. **HKS-X92** What are the last words of every piece, and does each land as a finished sentence?
18. **HKS-X97** For each check that passed, what did you read or look at to judge the goal itself?
19. **HKS-X99** Does any check fail at handover, and does the handover open with it?
20. **HKS-X102** For each check relied on, what did it give on the user's finished cut?
21. **HKS-X103** Which controls failed, and does the handover open with each id and value?
22. **HKS-X104** Which gates were overridden, by whom and why, and are they named in the handover?
23. **HKS-X107** How long is the body, and which pieces were cut to bring it into 17-20 min (source timecodes, why each)?
24. **M-2** Did the user ask for an export, and was only what changed exported?
25. **M-5** Which rendered frames were looked at for each reframed piece?
26. **M-6** For each correction this session, where are its memory, principle and gate entries?

## Sending the answers

Send every answer to the helper's `premiere_hks_handover` tool as `{rule_id: answer}`, one written answer per active do-confirm rule. That is the list above plus the lists in the other stage skills:

- `hks-day-setup`: HKS-16, HKS-C31, HKS-X13, HKS-X14, HKS-X69, HKS-X73, HKS-X74, HKS-X76, HKS-X77, HKS-X78, HKS-X79, HKS-X88, HKS-X105
- `hks-paper-edit`: HKS-1, HKS-2, HKS-3, HKS-5, HKS-10, HKS-11, HKS-13, HKS-14, HKS-18, HKS-19, HKS-22, HKS-24, HKS-25, HKS-26, HKS-C4, HKS-C5, HKS-C6, HKS-C7, HKS-C8, HKS-C11, HKS-C12, HKS-C15, HKS-C16, HKS-C21, HKS-C22, HKS-C23, HKS-C24, HKS-C27, HKS-R1, HKS-R2, HKS-R3, HKS-R4, HKS-X1, HKS-X5, HKS-X7, HKS-X15, HKS-X25, HKS-X26, HKS-X39, HKS-X71, HKS-X80, HKS-X89, HKS-X90, HKS-X91, HKS-X98, HKS-X109, M-1, M-4
- `hks-build`: HKS-7, HKS-17, HKS-20, HKS-32, HKS-C1, HKS-C2, HKS-C3, HKS-C9, HKS-C10, HKS-C17, HKS-C20, HKS-C25, HKS-C26, HKS-C28, HKS-C29, HKS-C30, HKS-R5, HKS-R6, HKS-R7, HKS-X2, HKS-X3, HKS-X4, HKS-X6, HKS-X9, HKS-X10, HKS-X11, HKS-X16, HKS-X17, HKS-X23, HKS-X24, HKS-X27, HKS-X28, HKS-X29, HKS-X30, HKS-X31, HKS-X33, HKS-X34, HKS-X35, HKS-X36, HKS-X40, HKS-X41, HKS-X42, HKS-X43, HKS-X44, HKS-X45, HKS-X46, HKS-X47, HKS-X48, HKS-X49, HKS-X50, HKS-X51, HKS-X52, HKS-X53, HKS-X54, HKS-X55, HKS-X56, HKS-X57, HKS-X58, HKS-X59, HKS-X60, HKS-X61, HKS-X62, HKS-X64, HKS-X68, HKS-X72, HKS-X81, HKS-X95, HKS-X96, HKS-X101, HKS-X106, HKS-X108, M-3
