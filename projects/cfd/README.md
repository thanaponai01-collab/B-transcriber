# Club Friday (CFD)

Club Friday: a call-in advice show. Two hosts (sometimes three) listen to an audience member who
calls in with their story, then give advice. From a batch of finished episode videos we make **one
long form** and **Shorts**. *(confirmed, user 2026-11-26)*

## What gets made

1. **Long form** (16:9): every clip in the batch (about 5–10) on one timeline in order, each with its
   opening and ending cut off, and each with the hosts' advice quoted on screen as text.
2. **Shorts** (9:16): pick the 3 clips with the strongest story; each becomes its own Short with
   subtitles and one advice quote near the end.

Steps and the why: [rules.md](rules.md), [principles.md](principles.md).

## Read order
1. [Main principles](../PRINCIPLES.md)
2. [principles.md](principles.md): this project's why (`CFD-n`)
3. [memory/MEMORY.md](memory/MEMORY.md): facts; open only what the task needs
4. [rules.md](rules.md): how, today
5. [workflow-log.md](workflow-log.md): the evidence

## Where things live
Episode folders: `G:\Me\Works\YYYYMMDD - CFD <ep>` (template tree `1. FOOTAGE` … `8. THUMBNAIL`).
Details and past episodes: [memory/episode-folders.md](memory/episode-folders.md).

## Code and tests
- No CFD-specific code. The work uses the shared CutDeck routes
  ([docs/PREMIERE_CONTROL_MAP.md](../../docs/PREMIERE_CONTROL_MAP.md)): timeline transcript to find
  the opening/ending and the advice, text placement for the quotes, and
  [SubtitleDesk](../../subtitle_desk/) for Shorts subtitles.
