# ARCH-DESIGN
- at: e2f4c14
- question: UXP panel (uxp/cutdeck): after the earlier splits landed (main.js → features/, host/ layer, structure test), where does the next change still cost too much?
- yardstick: add a Transform/Align operation (5 modules: core/alignPanel.js, index.html, main.js, features/align.js, features/driver.js; commit 61587cf + 5874fbe); add an Adj & FX effect or preset kind (6 modules: core/panel.js, index.html, main.js, features/adjust.js, timeline/*, host; commit 17da2d2); add a Premiere workaround to Rough Cut / Sync (3 modules: features/roughCut.js, timeline/native*.js, host/*; commits 3ec84e9, aa2337c). Source: `git log` since 2026-09-20 and the rehearsal walk.
- status: landed
- verdict: messy in places
- context: UXP stays the only panel; the layer order in tests/cutdeck_structure.test.cjs (main → core UI → features → domain → host) stays; no behavior change in any move.

Not read: probe bodies (capabilityProbe.js, roughCutProbe.js, syncProbe.js, layoutProbe.js), spike18_split_probe/ (a spike, not the shipped panel), the helper (cutdeck/*.py).

Earlier designs (docs/arch-design-cutdeck-panel.md, arch-design-helper-v2.md) are landed: main.js is 224 lines of wiring, `KNOWN_EXCEPTIONS` in the structure test is all empty, 588 node tests pass (proven, `node --test tests/*.cjs`). This file does not reopen them.

## Finding 1: features/align.js became a domain module inside the feature layer
- where: uxp/cutdeck/features/align.js:16 (domain starts) to :756 (domain ends); controller `createAlignFeature` at :796; consumer uxp/cutdeck/features/driver.js:27
- cost: 980 lines, of which 741 (lines 16-756) are Premiere transform operations (read model, edit clips, anchor, align, distribute, text-layer maths, setField); 14 commits since 09-20 (its whole life); driver.js imports 5 domain functions from a feature file (feature → feature); 6 test files import domain functions through the feature path. Its own header says it owns "display state ... polling" (align.js:1-4); the prior design table said the same (arch-design-cutdeck-panel.md:219). The layer test cannot see the drift because features and features are the same layer.
- badge: strong
- evidence: proven, `git log --oneline -- uxp/cutdeck/features/align.js | wc -l` = 14; `grep -n "transformProbe\|PROBES\|runProbe\|createProbesFeature" features/align.js` shows probe use only at :12,:14,:798,:954, so lines 16-756 have no controller dependency (traced). A fresh-subagent recount was not run (this session may not spawn agents); the counts were re-derived with separate git/grep commands instead.

## Finding 2: addFrameHold is one 344-line function
- where: uxp/cutdeck/timeline/frameHold.js:403
- cost: 344 lines in one function; 4 commits since 09-24 (5660b5f, 777516f, b9384e3, and the 17da2d2 origin). Deletion test: it is a linear sequence of Premiere workarounds (isolate track, export, import, organize); named steps would only move the lines, not shrink them.
- badge: speculative
- evidence: traced, read the function list of the file; not read line by line.

## Finding 3: diagnostic probes are 18% of the panel source
- where: uxp/cutdeck/capabilityProbe.js (1118 lines), uxp/cutdeck/roughCutProbe.js (364), uxp/cutdeck/syncProbe.js (276), uxp/cutdeck/layoutProbe.js (146); uxp/cutdeck/timelineRange.js is reached only through them; tests/cutdeck_structure.test.cjs:156-162 names a `probes/*` folder that does not exist
- cost: 1904 of 10745 source lines sit at the panel root next to main.js; they load lazily (features/probes.js:5-8) so runtime cost is nil. No dead-code claim is made.
- badge: speculative
- evidence: traced, `wc -l` and the require lines in features/probes.js; usage of timelineRange.js checked by grep (only capabilityProbe.js, plus tests).

## Decision 1: keep the panel.js / index.html co-change as is
- options: keep the ids as strings guarded by tests/panel_ui_contract.test.cjs | generate the DOM ids from one shared manifest
- forces: the pair changed together 18 times (confidence 0.86); the owner already exists and holds (id-resolution test); a manifest adds a layer with one consumer and no requirement behind it
- door: two-way
- evidence: traced, change-map.py output and the test file header

## Decision 2: where transform operations live
- options: `transform/edit.js` next to the existing transform/apply.js, params.js, geometry.js | leave in features/align.js and only add a structure rule
- forces: driver.js needs the operations without the panel controller; transform/ already owns the write path (apply.js) and the layer test allows features → domain; a rule alone leaves 741 domain lines in the feature layer
- door: two-way
- evidence: traced, imports listed with grep across features/, timeline/, transform/

## Move 1: lift the transform operations out of features/align.js into transform/edit.js
- cost: 741 domain lines in a feature file; driver.js reaches domain code through a feature (1 of 3 feature → feature edges: driver → align, driver → probes, align → probes)
- pays: add a Transform/Align operation: the operation code goes to a domain file and the feature file only wires it (align.js 980 → about 240 lines); driver → align edge 1 → 0, so an agent command for a new operation never imports a feature
- files: uxp/cutdeck/features/align.js:16-756 (move), uxp/cutdeck/features/driver.js:27-33 (import path)
- owner: transform/edit.js owns reading the clip model and every write a Transform/Align action performs; features/align.js owns display state, polling and status wording
- callers: features/driver.js:27-33; tests/cutdeck_align_panel.test.cjs:595,656; tests/cutdeck_feature_align.test.cjs:7; tests/cutdeck_transform_edit.test.cjs:16; tests/cutdeck_transform_flicker.test.cjs:86; features/align.js itself (imports the moved functions back). Grep `features/align.js` again before starting.
- door: two-way, land it and go
- proof: `node --test tests/*.cjs` prints `# pass 588` and `# fail 0` before and after; `wc -l uxp/cutdeck/features/align.js` under 260; a new test in tests/cutdeck_structure.test.cjs (which also drops its stale `probes/*` mention at :156-162, Finding 3) fails when any features/*.js requires another features/*.js file other than probes.js
- effort: M
- after: nothing
