GENERATED from projects/hks/registry by tools/hks_registry_build.py; do not edit.

# Before you cut (read this every time, before any HKS draft)

Short on purpose. The full rules are in [rules.md](rules.md). This page exists because on 20261125 I had those rules and broke them anyway (the reasons are at the end). Each line is a gate. If a gate fails, fix it. If I can't fix it, the handover opens with that gate's name and what's still broken. A failed gate is never handed over quietly, and lack of time is not a reason to skip one.

Every active rule of a stage, with its do-confirm question, is in that stage's skill (`hks-day-setup`, `hks-paper-edit`, `hks-build`, `hks-handover`, under `.claude/skills/`).

## Code gates (the handover runs these)
- **HKS-33** Sound and picture cut at different times (`same_frame_share`)
- **HKS-X8** Never a jump cut, not even one frame (`near_miss_covers`)
- **HKS-X37** The held picture must be safe (`unsafe_holds`)
- **HKS-X38** Check visible studio edges in speech (`visible_cuts_in_speech`)
- **HKS-X63** I cut in the middle of a thought (`visible_cuts_in_speech`)
- **HKS-X65** I cut sound and picture on the same frame (`same_frame_share`)
- **HKS-X66** A split edit can hold a talking picture (`unsafe_holds`)
- **HKS-X75** Every draft is labelled (`draft_labels`)
- **HKS-X93** No source played twice (`source_repeats`)
- **HKS-X94** Same-frame sound and picture cuts: few (`same_frame_share`)
- **HKS-X100** Ripple fixes can overlap neighbours (`source_repeats`)

## Day setup (before the paper edit)
0. **Mark the hot spots yellow on `Editing`**, not just the question colours: the loud arguments (raised voices, people talking over each other), the clash, the admissions, the lines the story can't lose. Mark the closing lines orange. Yellow is the must-keep list for the YT and the pool for the hook and highlight. Use the audio level to find the loud stretches, then listen to each one. On 20261125 I coloured only per question and marked no yellow at all.
0b. **`Backup` is 1920x1080, built at the YT frame size, never from `Editing` (720p).** Every insert is scaled to fill it: full-screen footage Scale 150 centred; a boxed split screen zoomed to its box, centred, about 8 % past the box edge; no studio shot of the host or a guest, no edge of the show frame. Render the frames and look before using any as a cover. On 20261126 I built it at 1280x720 from `Editing`, unzoomed, and the user had to tell me ("make sure the backup is 1920x1080 and all broll scale up and fit the rules").

## Story (before building)
1. **Set-up in two lines:** who these people are, where (the houses, the shop), what happened between them. The cut gives a first-time viewer these facts before the first detail that needs them.
2. **Give a taste of the event itself** (the clip, its sound) before the people talk about it. If the broadcast plays footage of the incident, the body uses it where the story reaches that moment.
3. **Story order, not the broadcast's order.** Each story part answers "what happens next?" for someone who has never seen the case. Cut the back-and-forth and the repeats, but keep the set-up.

## Every edge (after building, before handover)
4. **Read the last words of every piece out loud.** Each one is a finished sentence that lands, not just a pause: no "...คือ", "...ก็", "...แล้วกันพี่", no question left hanging. `hks_cut_check` finds pauses, not finished thoughts. A clean result there doesn't mean the endings are finished.
5. **No source played twice.** Two pieces next to each other must not overlap in source (repeated words).
6. **Same-frame sound and picture cuts: few.** `hks_cut_check` gives the count. Your 20261124 YT body: 12 of 173. My 20261125 v1: 31 of 39. Every jump to another speech in the same studio scene gets a cover: insert, B-roll or a still person from `Backup`.

## Building
7. **J/L on a copy:** duplicate the clip onto the track above and trim the copy. The raw clip stays below, untouched, as the backup.
8. **Use Premiere's own tool first:** blur = my own adjustment layer + Gaussian Blur + an Ellipse or Rectangle mask, feathered. "No API" means: try the UI route. It doesn't mean impossible. A workaround is the last way, and the handover names it.

## Why I broke the rules on 20261125 (what to watch for in myself)
- I treated a passing check as the rule. The cut check passed on pauses, so I called the endings finished without reading them.
- I read "get in fast" and "drop backstory" as "cut the context". The where and the incident clip are set-up, not backstory.
- I saw the check say 79% same-frame cuts and handed over anyway. You were waiting, so I chose speed and didn't say so plainly. That was cutting a corner.
- My ripple fixes made neighbouring pieces overlap in source, and I didn't check for it.
- For the blur I read "masks have no API" as "masks can't be done", and copied your layer instead of building one.

The whole note: [memory/why-rules-broke-20261125.md](memory/why-rules-broke-20261125.md).
