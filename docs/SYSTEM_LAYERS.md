# System layers: one core, many tools

Written 2026-11-25 for the question: "Are we building block by block instead of one top-level
engine that every tool reuses, for transcribing and for commanding Premiere?" This file has the
answer, checked against the code, plus the words for the problem and a sharper version of the
question to hand an agent.

## Short answer

Partly. The **bottom** and the **top** are already single. The **middle** is where things are
built again each time.

| Layer | Single today? | Evidence |
|---|---|---|
| Transcribe a file | **Mostly** | The callers read (`cutdeck/ai_worker.py`, `cutdeck/hks_words.py`, `cutdeck/rough_cut.py`) go through `transcribe.service.transcribe`, which caches by media sha256. `cutdeck/timeline_transcript.py` maps each source's one transcript onto a cut, with no new ASR. Two exceptions: `transcribe_file.py` shells out to `transcribe.pipeline.run` directly, and Rough Cut's `--asr` fallback (`rough_cut.py:261`) transcribes a **mixdown of the timeline** when it can't map source transcripts. That fallback is the "transcribing on the timeline" second path. |
| Command Premiere | **Yes** | One table, `COMMANDS` in `cutdeck/driver_commands.py`. The MCP server makes one `premiere_<name>` tool per row (`cutdeck/mcp_server.py:132`), and the CLI and helper use the same table. Menu, keys, pixels and UXP are routes behind it (`docs/PREMIERE_CONTROL_MAP.md`). Besides the table, `mcp_server.py` hand-writes a few job tools (transcribe, rough cut, `get_job`). |
| Words with times | **Mostly** | `cutdeck.words.Word` → `timeline_transcript.SourceWord` → `TimelineWord` is one chain, each a view of the one before. HKS is the exception: `hks_words.pieces` writes raw engine pieces as `[start, end, text]` JSON, a separate word format. |
| "Where is it quiet?" | **No: four definitions, disagreeing** (measured below) | `hks_tighten.silences`: ffmpeg `silencedetect` at a fixed −35 dB, ≥0.3 s (used by `hks_judge`, `hks_draft`). `rules.silence_cuts`: VAD silences from `ingest` (500 ms). `timeline_transcript.tighten` / `word_cut` / `hks_cut_check`: 10 ms envelope, whole-file noise floor + 6 dB. `word_align.snap_to_sound` (re-times words, doesn't place cuts): local floor ±500 ms + 6 dB. |
| "What is a filler?" | **No: two lists** | `rules.filler_cuts` reads `filler_lexicon` in `transcribe/config.yaml` (เอ่อ อ่า อืม เอิ่ม um uh, off by default). `speech_clean.FILLER` is its own regex that also has ฮึ หืม ฮึ่ม ฮึบ อ้า. |
| "Plan cuts on a timeline" | **No: three stacks** | Rough Cut v1 (`rough_cut` → `sequence_mixdown` / `plan` → `rules` → `segment`, on a mixdown it ingests itself), word cuts v2 (`timeline_transcript` → `word_cut` / `speech_clean`), and HKS (24 `hks_*` modules; only `hks_cut_check` uses the v2 core, `hks_judge` / `hks_draft` use `hks_tighten.silences`). Rough Cut already prefers the v2 mapped transcript and falls back to its own ASR. |
| Map of the layers | **No** | `SYSTEM_SPEC.md` goes folder by folder and gives all of `cutdeck/` (60+ modules) one section; `FEATURES.md` lists features. Neither says which layer a module belongs to or which layer may call which, and nothing stops a new module from rolling its own. |

**Not checked:** the UXP panel JS (`uxp/cutdeck/`), `subtitle_desk/`, the subtitle writers
(`cutdeck/srt_subtitles.py`, `transcribe/subtitles/`) and the web editor. They may hold more
copies of the same rules.

So your feeling is right about the middle and mostly wrong about the ends. You don't need a new top
engine. The newest code (`timeline_transcript` + `word_cut`) is already close to the shared core
you're describing. What is missing is **naming it the core**, moving the older stacks onto it,
and making the rule checkable.

## Measured: do the duplicates disagree? (2026-11-25)

`python tools/measure_middle_layer.py --json output/middle_layer_measure.json`, read-only, on the
8 HKS tuning days (no holdout). Points: the 2,268 sound edges of the user's finished YouTube
bodies (a good rule calls them quiet) and 2,268 mid-points of words the user kept (a good rule
calls them not quiet). "Quiet" = the rule finds quiet within ±40 ms (one frame) of the point.

| Rule | Where it lives | User's edges quiet | Kept mid-words quiet (false) | Edges − false |
|---|---|---|---|---|
| A ffmpeg −35 dB, ≥0.3 s | `hks_tighten` (`hks_judge`, `hks_draft`) | 57.8% | 9.9% | 47.9 |
| B VAD speech-span gaps | stored by `transcribe`; Rough Cut | 39.8% | 3.7% | 36.1 |
| C file floor + 6 dB | `timeline_transcript` (`word_cut`, `speech_clean`) | **76.1%** | 13.4% | **62.7** |
| D local floor + 6 dB, 20 dB rise | `word_align.snap_to_sound` | 43.3% | 11.5% | 31.8 |
| E C or a ≥0.15 s word gap | `hks_cut_check` (the HKS gate) | 76.6% | 13.4% | 63.2 |

- **They disagree a lot.** On the same user edges, A and D agree on 43%, B and C on 60%, A and
  C on 67%. Only C and E (E is built on C) agree (99.5%). So the HKS draft (A) and the HKS
  gate (E) judge a third of real cut points differently.
- **C separates cut points from speech best**, and E adds almost nothing over it. At ±120 ms
  the order holds (C 57.1, A 43.5, B 42.1, D 19.0). C is the best rule **for a point**; the
  prototype below shows it is not the best for finding pauses to cut, so the shared piece is
  C's envelope with a margin per question. D does a different job (moving word starts), so it can
  keep its local floor but should be named as such, not as "quiet".
- **Fillers are not a real split in practice.** Both lists match the same three words in these
  transcripts (อ่า 131, อืม 103, เอ่อ 61); the regex adds 5 more hits (อ้า, หืม, ฮึ). The user cut
  88% of them versus 79% of all words, which is a weak signal on broadcast footage where most
  of the show is cut anyway. Merging the two lists is low-risk; which list is "right" can't be
  settled from HKS data.
- **Limits:** HKS broadcast footage only (music and room tone under speech), not 1RaceClub. B
  uses the transcription job's VAD spans, not Rough Cut's cut-config VAD. D is re-implemented
  on the 10 ms envelope, not `word_align`'s 25 ms windows. Contextual fillers (แบบ, ก็คือ) not
  measured.

## Prototype: HKS tightening on the shared rule (2026-11-25)

`hks_tighten` finds pauses to cut inside keeps from ffmpeg `silencedetect` (−35 dB, rule A).
The prototype adds `timeline_transcript.quiet_runs` (runs of the shared 10 ms envelope below
floor + margin) and `hks_tighten --check --quiet floor`, scored by `hks_score` against the
user's keeps on the 8 tuning days. The default is still ffmpeg.

| Pauses from | Edge precision | Edge recall | Tighten cuts 0.6–3 s (prec / recall) | < 0.6 s (prec / recall) |
|---|---|---|---|---|
| ffmpeg −35 dB (today) | 0.768 | 0.580 | 0.56 / 0.31 | 0.47 / 0.11 |
| floor + 6 dB (rule C as is) | 0.899 | 0.506 | 0.58 / 0.13 | 0.56 / 0.03 |
| floor + 12 dB | 0.804 | 0.557 | 0.58 / 0.25 | 0.52 / 0.08 |
| **floor + 18 dB** | 0.758 | 0.585 | 0.53 / 0.31 | 0.47 / 0.11 |
| floor + 24 dB | 0.701 | 0.614 | 0.46 / 0.36 | 0.44 / 0.17 |

- **Rule C as is makes tightening worse.** On these files the floor is −48 to −65 dB, so
  floor + 6 dB is 7–24 dB stricter than −35 dB, and room tone breaks most pauses. It finds
  under half of the user's 0.6–3 s tightening cuts that ffmpeg finds.
- **At + 18 dB the shared envelope scores the same as ffmpeg.** That means the second ffmpeg
  pass and its cache can go (one decode, one cache per file) with no loss. No margin beats
  ffmpeg on both precision and recall; it is a trade-off curve.
- **Switched (user's yes, 2026-11-25).** `hks_draft` and `hks_tighten --check` now take pauses
  from `hks_tighten.pauses` (shared envelope, floor + 18 dB); `--quiet ffmpeg` keeps the old
  source, and `hks_judge` still uses ffmpeg `silences`. Full draft check on the 8 tuning days:
  agreement, keep precision and recall move by 0.003 or less per day. Jump cuts go from 181 to
  187, and +8 of that is 20261001, whose floor is loud (−48 dB, so the threshold is −30 dB, above
  −35): it now finds 35 pauses to tighten instead of 2. The other days move by −1 to +2. The
  user kept the switch with the +6 jump cuts (2026-11-25).
- **The lesson for the core:** "is this point quiet?" and "is this a pause long enough to cut?"
  are two questions. The core should own **one envelope and one function** (`quiet_runs(levels,
  min_ms, margin)`) with a named margin per question (+6 dB for a point, +18 dB for a pause),
  not one threshold for everything. "Rule C wins" from the point test did not carry over.

## Which problem is this?

| Candidate | The one term | Sign that tells it apart | Found here? |
|---|---|---|---|
| A. No shared core | single source of truth | The same rule written twice gives different answers | **Yes**: quiet ×4, fillers ×2 |
| B. A core exists, callers go around it | strangler fig (unfinished migration) | A newer module does the job, older paths still do their own | **Yes**: Rough Cut v1 and HKS next to the v2 core |
| C. Layers exist, nobody drew them | layered architecture (enforced) | Docs list features, not layers; no rule on imports | **Yes**: no layer map, no import check |

Taught for **A + B**, because they produce wrong behaviour (a cut judged quiet by one tool
and loud by another; measured above). C is how to keep it fixed afterwards.

## Words for it (ranked by how much each changes what gets built)

1. **Narrow waist (hourglass model).** One thin shared layer in the middle; many things below
   it, many tools above it, and they talk only through it. *Names:* your "top engine that spreads
   into other tools". Here, the waist is "words and quiet on a timeline". Source:
   [Hourglass model](https://en.wikipedia.org/wiki/Hourglass_model), the Internet's IP layer.
   *Ask an agent:* "Define the narrow waist between the transcript store and the cut tools, and
   list every tool that bypasses it."
2. **Single source of truth.** Each fact is decided in exactly one place. *Names:* "instead of
   one". Here: one function answers "is this moment quiet?", one list answers "is this a filler?".
   Source: [Single source of truth](https://en.wikipedia.org/wiki/Single_source_of_truth).
   *Ask:* "Make one `quiet_at(media, ms)` that every cut tool calls."
3. **Intermediate representation (IR).** One shared data form many front ends produce and many
   back ends consume. *Names:* the shape of the core: engines in, timeline words + levels in the
   middle, Premiere / SRT / HKS out. Source: [LLVM Language Reference](https://llvm.org/docs/LangRef.html).
   *Ask:* "Write the IR schema for a timeline transcript and check every tool reads only it."
4. **Canonical data model.** One shared format every part translates to and from, instead of
   pairwise formats. *Names:* `[start, end, text]` JSON vs `SourceWord` vs `Word`. Source:
   [Canonical Data Model (EIP)](https://www.enterpriseintegrationpatterns.com/patterns/messaging/CanonicalDataModel.html).
   *Ask:* "Replace HKS's word JSON with the canonical word type."
5. **Strangler fig.** Replace an old path gradually by growing the new one around it until the
   old one can be deleted. *Names:* Rough Cut v1 next to word cuts v2. Source:
   [StranglerFigApplication (Fowler)](https://martinfowler.com/bliki/StranglerFigApplication.html).
   *Ask:* "Move Rough Cut's silence and filler steps onto the v2 core, one caller at a time, then
   delete `rules.silence_cuts`."
6. **Ports and adapters (hexagonal architecture).** The core talks to the outside through ports;
   each outside technology plugs in through an adapter. *Names:* what you already did for
   commands: UXP, menu, keys, pixels are adapters behind `COMMANDS`. Source:
   [Hexagonal architecture (Cockburn)](https://alistair.cockburn.us/hexagonal-architecture/).
   *Ask:* "Treat ffmpeg silencedetect and the 10 ms envelope as two adapters behind one quiet port."
7. **Layers contract.** A machine-checked rule that higher layers may import lower ones, never the
   reverse. *Names:* "that top level can be used in any below level", made enforceable. Source:
   [import-linter: Layers](https://import-linter.readthedocs.io/en/stable/contract_types/layers/).
   *Ask:* "Add an import-linter layers contract: `hks_*` → `cutdeck` core → `transcribe`; fail on violations."
8. **Ubiquitous language.** One vocabulary shared by the code and the people. *Names:* "cue",
   "piece", "word", "keep", "pause" mean slightly different things in different modules. Source:
   [UbiquitousLanguage (Fowler)](https://martinfowler.com/bliki/UbiquitousLanguage.html).
   *Ask:* "Write a glossary of the core nouns and rename modules that use them differently."
9. **Derived state (from a log of events).** Keep the raw record once; build every other view
   from it when needed. *Names:* transcribe once per source, then derive the timeline view, the
   SRT, the Premiere transcript. You already do this for words. Source:
   [Event Sourcing (Fowler)](https://martinfowler.com/eaaDev/EventSourcing.html).
   *Ask:* "Make audio levels a cached, derived view per source like the transcript is."
10. **Rule of three.** Extract shared code once something is written the third time; two copies
    can wait. *Names:* when to stop "building everything new". Quiet is at four, so it is past
    due; fillers are at two. Source:
    [Rule of three](https://en.wikipedia.org/wiki/Rule_of_three_(computer_programming)).
    *Ask:* "List every rule implemented three or more times."
11. **Command pattern.** Requests as objects so one invoker can run, queue and log them.
    *Names:* the `COMMANDS` table you already have, so you can say it is done. Source:
    [Command pattern](https://en.wikipedia.org/wiki/Command_pattern).

## Neighbouring fields that solved this shape

**Compilers (LLVM).** Many languages in, many chips out, one IR in the middle, so a new language
or a new chip is one piece of work, not N×M. *Carries over:* engines and sources are front ends,
Premiere / SRT / HKS builds are back ends, the timeline transcript is the IR, and passes (clean
speech, cut words, tighten) run on the IR. *Breaks:* an IR is exact; your middle carries
uncertainty (engine confidence, a pause that is room tone). The IR has to carry that, not hide
it. *Terms back:* IR, pass, front end / back end.

**Internet (hourglass).** IP is the one layer every link type and every app agrees on, which is
why both sides can grow on their own. *Carries over:* keep the waist small and stable, change
the edges freely. *Breaks:* the Internet has many independent owners; you have one, so you can
change the waist when the evidence says so, as long as the eval harness and VERIFY.md gate it.
*Terms back:* narrow waist, spanning layer.

**Film post-production (EDL / OpenTimelineIO).** Editors moved cuts between tools through one
edit list, and OTIO is "a modern Edit Decision List" with adapters to other formats. *Carries
over:* a cut plan should be one data object (keeps / removes in source time) that any tool can
produce and Premiere applies through `cut_copy`. *Breaks:* EDL and OTIO record the cut, not why
or the words; your plan also needs the words and the pause evidence. *Terms back:* edit decision
list, interchange format, adapter. Sources:
[OpenTimelineIO](https://opentimelineio.readthedocs.io/en/latest/),
[Edit decision list](https://en.wikipedia.org/wiki/Edit_decision_list).

## What you didn't mention but should care about

- **This is a correctness problem, not just tidiness.** `hks_draft` places cuts in −35 dB
  ffmpeg silences; `hks_cut_check` judges them with floor + 6 dB. On the user's own edges those
  two rules disagree on about a third of cut points (measured above).
- **The eval gate only covers the engine.** `cer_thai` and `cue_boundary_error_rate` guard
  transcription. Nothing measures the middle (is a cut in a pause?) on one shared set, so
  merging the quiet finders has no score to prove it didn't get worse. `hks_cut_check` and
  the timecode ruler (14 clips) are the start of one.
- **Project code vs core code.** The 24 `hks_*` modules are one show's recipe. That's fine
  (product code may be specific), but they should call the core for words, quiet and cuts, not
  carry their own. The same applies to 1RaceClub before it grows its own stack.
- **`driver_commands.py` is 1,750 lines.** The table is right, but it also holds the logic of
  many commands. The table should stay a thin list of rows that call core functions.

## Your description, rewritten

> Our ASR (`transcribe.service`) and our Premiere command table (`COMMANDS`) are already single.
> The layer between them, the **narrow waist**, is not: "words with times on a timeline", "is
> this moment quiet" and "is this a filler" each have several implementations that disagree. I
> want one **intermediate representation** of a timeline (canonical words + audio levels per
> source, projected through the clip list) as the **single source of truth**, every cut tool
> (Rough Cut, clean speech, cut words, HKS) built as a pass on it, the old paths moved over
> **strangler-fig** style and deleted, and a **layers contract** that fails the build when a
> project module rolls its own.

## Sharpened: the prompt to hand an agent

A senior architect wouldn't start from the docs or from a feeling. They would:

1. **Do what you didn't ask for:** measure how often the duplicates disagree before merging
   anything, and decide which definition wins on evidence, not taste.
2. **Start from the rawest material:** the import graph and call graph of `cutdeck/` and
   `transcribe/`, the source audio of real cuts, and the user's own finished cuts. Not
   `FEATURES.md`.
3. **Use these tools:** an import-graph dump (`pydeps` or a short `ast` script), import-linter
   contracts, one disagreement test that runs every quiet finder on the same clips, and the
   existing replay ruler / `hks_cut_check`.
4. **Let something other than us judge it:** the user's own finished cuts (every edge they kept
   is, by definition, a good cut point), plus the eval harness and `VERIFY.md` staying green.

> **Prompt.** In `E:\Me\5.Claude\Transcriber_v2`, on branch `docs/system-map-reframe`, map and
> measure the middle layer between `transcribe.service` and the `COMMANDS` table, and
> recommend one core for it. Don't consolidate yet.
>
> 1. Build the import graph of `cutdeck/` and `transcribe/` from the code, not the docs, and
>    draw the layers: engine → transcript store → timeline IR → passes → commands / project
>    recipes. List every module that reaches past its layer.
> 2. Run every "is it quiet" implementation (`hks_tighten.silences`, `rules.silence_cuts` via
>    ingest VAD, `timeline_transcript.tighten` / `_nearest_quiet_ms`, `word_align.snap_to_sound`)
>    on the same sources and on the cut edges of the user's finished HKS and 1RaceClub cuts.
>    Report where they disagree and which definition matches the user's kept edges best.
>    Recommend one based on that result. Do the same for the two filler lists.
> 3. Propose the timeline IR (canonical word type + per-source levels + clip projection), using
>    what `timeline_transcript` already has. Prototype moving one caller (HKS word pieces or
>    Rough Cut silences) onto it and show the before/after on the same evidence.
> 4. Recommend whether an import-linter layers contract (known violations as exceptions) is
>    worth adding, from what the import graph showed. Don't add it.
> 5. Also check the parts not yet read: `uxp/cutdeck/`, `subtitle_desk/`, the subtitle writers
>    and the web editor.
> 6. Leave to me: which project recipes (HKS, 1RaceClub) stay as separate modules, and whether
>    Rough Cut v1 is retired or kept as a mode. Don't delete anything without my yes; don't
>    commit until I ask.
