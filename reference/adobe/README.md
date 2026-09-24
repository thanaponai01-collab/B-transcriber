# Adobe reference (local, pinned)

Everything needed to check a Premiere / UXP API **without going online**. Text only, pinned in
[`sources.json`](sources.json), Adobe's Apache-2.0 licenses kept beside each part.

| Folder | What | From |
|---|---|---|
| `api/premierepro.txt` | **Start here.** Every Premiere member, one line: `Owner.member(signature) [static, since, NOT IN 26.2.1]  -- doc` | generated from `typings/` |
| `api/uxp.txt` | Same for the UXP platform (storage, shell, xmp, os, fs, DOM) | generated from `typings/` |
| `typings/premierepro-26.5.1.d.ts` | Adobe's Premiere typings for the **installed** Premiere 26.5 | `@adobe/premierepro@26.5.1` |
| `typings/premierepro-26.2.1.d.ts` | The manifest's `minVersion` line; anything absent here needs 26.3+ | `@adobe/premierepro@26.2.1` |
| `typings/uxp-7.3.1.d.ts` | UXP platform typings (has gaps: e.g. `storage.localFileSystem` is missing) | `@adobe/cc-ext-uxp-types@7.3.1` |
| `docs/` | Adobe's Premiere UXP docs: `ppro-reference/` (classes, constants, events), `uxp-api/` (platform), `resources/recipes/`, `plugins/` (manifest, entrypoints) | `AdobeDocs/uxp-premiere-pro` |
| `samples/` | Adobe's own working sample panels (`sample-panels/premiere-api/src/*.ts`) | `AdobeDocs/uxp-premiere-pro-samples` |

**What happens when you call it** is not here. That's [`docs/PREMIERE_FACTS.md`](../../docs/PREMIERE_FACTS.md),
the live-proven behaviour. Typings don't give runtime enum values or semantics (e.g.
`InterpolationMode` really is LINEAR 0 / HOLD 4 / BEZIER 5, not the typings' 0/1/2).

## Look something up

```bash
grep "^SequenceEditor\." reference/adobe/api/premierepro.txt          # a class's members
grep -i "keyframe" reference/adobe/api/premierepro.txt                # by topic
grep "NOT IN 26.2.1" reference/adobe/api/premierepro.txt              # needs Premiere 26.3+
grep -rl "createEmptySelection" reference/adobe/docs reference/adobe/samples   # docs + real usage
```

## Check the panel against it

```bash
node --test tests/*.cjs            # includes the check; installs the tools on first run
node tools/adobe/check-api.mjs     # the check alone (needs the tools: npm ci --prefix tools/adobe)
```

## Update

Change a pin in `sources.json` (a new Premiere, new docs commit), then:

```bash
node tools/adobe/refresh.mjs       # re-downloads the pinned sources, rebuilds api/*.txt
node tools/adobe/check-api.mjs     # see what the new version changes for the panel
```

Diff `api/premierepro.txt` in git to see exactly which APIs came or went.
