# Main principles

The principles every project follows, and the index of every project's own principles. Read this
first, then the project's `principles.md`. **The more specific file wins:** a project principle may
depart from a main one, and then it names the main ID and says why.

Coding and engineering rules (how to write code, proving an Adobe API, VRAM, the eval gate) are not
here. They live in [CLAUDE.md](../CLAUDE.md).

**Status tags:** **confirmed** = the user said so; **seen** = read from the user's own work;
**guess** = inferred, still to ask. Never upgrade a tag without the user.

## How a principle gets here

A principle starts in the project where it was learned. It moves here (word for word, with a pointer
left behind) only when **the user says it applies everywhere**, or it is **confirmed in a second
project**. IDs never change once given; a retired principle stays listed as *retired*.

## Working with the user

**M-1. Learn the why, not presets.** Every observed choice is recorded as the intent behind it
(viewer effect, constraint, story role). Values (109%, −12 dB, Posterize 0.2) are today's example,
not a setting to replay. *(confirmed, 2026-11-21: "not that copy everything i do … i want you to
understand why i do that … i want to like teach you how to edit, in terms of you doing it, not copy
me")*

**M-2. The user exports.** The agent never runs an export or queues Media Encoder, not even to a
scratch folder to check its own build. Check a build by read-back, frames and audio pulled from the
source media, and the transcript; hand it over unrendered and say so. *(confirmed on 1RaceClub,
2026-11-21: "dont export your self that me to do it")* For HKS the user asked on 2026-11-20 for
`python -m cutdeck.honekasae_export` to queue and start the export. *(guess: the rule is "no export
unless the user asks for it"; ask which holds)* On 2026-11-24 the HKS user asked "all done export for me" after approving every cut, and the
agent exported with BAS4 (seen: on HKS, the export follows the user's ask). Again on 2026-11-25 ("export now i finished editing", then "export the D2"): exported
only when asked, and only what had changed.

**M-6. A correction isn't learned until it's a gate.** *(confirmed, HKS 2026-11-25: "I want to know why
you broke them, even though you have the rules ... we can have rules for you to maybe read before doing it
... adaptable, improvable, and scalable ... as memory principle as well")* On 20261125 the agent had the
rules and broke them anyway: it let a passing check stand in for the rule, read "drop backstory" as "cut
the context", and handed over a draft it knew failed a check because the user was waiting. So every
correction from the user goes three places, the same day:
1. **memory**: what happened, with numbers (the project's `memory/`);
2. **principle**: the why (the project's `principles.md`, or here);
3. **gate**: how it's checked before handover (the project's `before-you-cut.md` for HKS): a script check if
   it can be counted, a question for a reviewer that doesn't share the agent's context if it needs
   judgment, a step that must come first if it's about order.
A failed gate is never handed over quietly: the handover opens with it. Time pressure is not a reason
to skip a gate.

## Editing

**M-4. Each point is told once.** *(confirmed in both projects)* The user's words and rules stay at
the source: HKS cut rule 2 in [hks/rules.md](hks/rules.md) (user: "each point is told once") and
1RaceClub "Say each point once" in [shorts-rules.md](1raceclub/shorts-rules.md) section 3.

**M-5. Check the frame before handing over.** For every piece, look at what the frame actually shows
(a reframed 16:9 source loses its edges, where captions and banners live). A cut that's right on
time can still show nothing. *(confirmed on 1RaceClub, 2026-11-21: "dont forget to check the
frame")* *(guess: it applies wherever a picture is reframed, not only Shorts)*

## Candidates (seen in one project, ask before promoting)

- **M-3 (held): never edit the user's working project in place.** The HKS build plan says "nothing
  edits the user's day project" (agent-written); 1RaceClub "copy the rough cut and work from there" is
  confirmed, but its reason is that the layers and audio tracks come along. Same principle or not?
- **Watch time:** judge every second by whether it keeps the viewer watching longer
  (1RaceClub Shorts, [shorts-rules.md](1raceclub/shorts-rules.md) section 0). HKS: **partly** (user,
  2026-11-24): after honesty and fairness ([hks/principles.md](hks/principles.md) HKS-C18).
- **No other brand's marks on screen:** 1RaceClub removes every F1 logo; HKS blurs the TV clock and
  other sources' watermarks. One principle (rights), or two different reasons?
- **Verify from the footage what each line is about** before cutting it (1RaceClub).
- **Keep the source untouched under every edit** (1RaceClub RC-15, 2026-11-22: "always keep the raw footage";
  holds and crops sit above the synced clip). Same idea as M-3 (never edit the user's work in place)? HKS: **yes**
  (HKS-C30, 2026-11-25: J/L cuts on a duplicate above, raw below as backup). Confirmed in two projects;
  ask the user before promoting it to M-7.
- **Use what's already in the project; keep agent-made files beside the .prproj** (1RaceClub RC-16). Everywhere?
- **Test a check on the user's finished cut before trusting it** (agent, HKS 2026-11-25; guess). The
  agent's "0 edges inside a word" was true by its own measure and false to the ear, and a pause rule it
  proposed would have failed the user's own cut. A check is kept if it separates the user's cut from
  the agent's; otherwise it's a list to look at, and the handover says so.

## Index: every project's principles and rules

| Project | Principles (why) | Rules (how, today) | Start here |
|---|---|---|---|
| 1RaceClub (F1 channel) | [1raceclub/principles.md](1raceclub/principles.md) `RC-n`; Shorts principles (incl. watch time) in [shorts-rules.md](1raceclub/shorts-rules.md) | [1raceclub/shorts-rules.md](1raceclub/shorts-rules.md) | [1raceclub/README.md](1raceclub/README.md) |
| HKS / โหนกระแส | [hks/principles.md](hks/principles.md) `HKS-n` | [hks/rules.md](hks/rules.md) `HKS-Rn` | [hks/README.md](hks/README.md) |
