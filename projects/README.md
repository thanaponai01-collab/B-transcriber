# Projects

The user's editing projects (channels and shows), one folder each. Product code stays in
`cutdeck/`, `transcribe/`, `uxp/`; tests stay in `tests/`. A project folder holds what the agent must
know to edit for that project.

| Project | What | Start here |
|---|---|---|
| [1raceclub](1raceclub/README.md) | the user's F1 YouTube channel: live reaction videos and Shorts | [1raceclub/README.md](1raceclub/README.md) |
| [hks](hks/README.md) | โหนกระแส (Honekasae) news-talk show: long form, FB, reels | [hks/README.md](hks/README.md) |

## Layers

Each layer is its own file. Each thing is written once, in one place, and points up to the layer
above it.

| Layer | File | Holds | Changes |
|---|---|---|---|
| Main principles | [PRINCIPLES.md](PRINCIPLES.md) (`M-n`) | the why for every project + index of all | rarely |
| Project principles | `<project>/principles.md` | the why for this project only | rarely |
| Rules | `<project>/rules.md` (or `*-rules.md`) | how a principle is applied today; cites its ID | often |
| Memory | `<project>/memory/` | facts: where things are, what happened, decisions, gotchas, preferences | often |
| Evidence | `<project>/workflow-log.md` | step-by-step record of the user's own edits | appended |
| Plans, audits, designs | `<project>/*.md` | build plans and their checks | per task |
| Code and tests | `cutdeck/`, `tests/` | the automation; cites the rule doc | per change |

Shared facts that hold for every project go in [memory/](memory/MEMORY.md).

## Read order (agents)

1. [PRINCIPLES.md](PRINCIPLES.md)
2. `<project>/README.md`, then its `principles.md`
3. `<project>/memory/MEMORY.md`, opening only the memories relevant to the task
4. the rules file, then the log, plans or audits the task needs

## Upkeep

- **Principle or rule?** If the reason would survive new footage, it's a principle. If it holds a
  value or a how-to, it's a rule. A fact about the world (a path, an episode, a quirk) is memory.
- **One place each.** Before adding, search for an existing entry and update it instead. Move text
  word for word with a pointer left behind; never keep two copies.
- **Status tags** (confirmed / seen / guess) travel with the text. Only the user upgrades them.
- **Promotion:** memory that keeps steering edits becomes a rule or principle; a project principle
  becomes main per the rule in [PRINCIPLES.md](PRINCIPLES.md).
- **Grow by splitting:** a file over ~400 lines, or a `MEMORY.md` over ~150, splits into sub-files or
  sub-folders (e.g. `memory/episodes/`). Don't split ahead of need.

## Memory files

One fact per file in `<project>/memory/`, listed one line each in `memory/MEMORY.md`
(`- [Title](file.md) — hook`):

```markdown
---
name: kebab-case-slug
description: one line, used to decide whether it's relevant
type: fact | decision | gotcha | preference | reference
status: current            # or: superseded-by: <name>
updated: YYYY-MM-DD
---
The fact.
**Why it matters:** …
**How to apply:** …
Related: [[other-memory]], RC-5
```

A changed fact gets `status: superseded-by: <name>` and stays listed; a fact that was simply wrong is
deleted.

## Add a project

1. Copy [_template/](_template/) to `projects/<name>/` (lowercase, no spaces).
2. Fill in its `README.md`: what the project is, where its files live, its code and tests.
3. Add a row to the table above and to the index in [PRINCIPLES.md](PRINCIPLES.md).
4. Record principles, rules and memory as they are learned. Leave a file nearly empty rather than
   guessing.
