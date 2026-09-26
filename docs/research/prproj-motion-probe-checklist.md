# Probe: what a saved .prproj holds for Motion / Text transform

Goal: check the Transform & Align panel's proven facts (`uxp/cutdeck/transform/params.js`)
against a real saved project, using `cutdeck/prproj_reader.py`. The 10 existing probe projects
contain no Motion component, so this needs a new one.

Save as `test_projects/motion_probe.prproj` (a manual save, not Auto-Save). Do the steps in
order; each one changes exactly one thing so the diff is unambiguous.

## Setup
- [ ] New sequence, **1920x1080**.
- [ ] Import a **1280x720** clip (source frame differs from sequence frame, which is what
      separates Position's space from Anchor's).
- [ ] Put it on V1, then a second copy on V2. V1 stays **untouched** (default Motion).

## Ordinary clip (V2), Effect Controls > Motion
Enter exactly these values; they are chosen so each normalization is recognisable.
- [ ] Position: `960, 540` -> then `100, 200`
- [ ] Scale: `50`
- [ ] Uniform Scale: unticked, then Scale Width `80`
- [ ] Rotation: `15`
- [ ] Anchor Point: `100, 200`  (compare with Position `100, 200`: 1920x1080 vs 1280x720)
- [ ] Crop Left `10`, Top `20`, Right `30`, Bottom `40`
- [ ] Opacity: `70`

## Keyframes (clip V3, a third copy)
- [ ] Position keyframed at 2 times (0s and 2s) with different values.
- [ ] Scale keyframed at 1 time only (a single keyframe is a different case).
- [ ] Rotation left static, to sit beside the keyframed fields.

## Text clip
- [ ] Legacy Text (Type tool), on V4. Set Position, Scale, Rotation, Anchor in its own
      Transform group to values that differ from the ordinary clip.
- [ ] A second text clip with no transform edits.

Save. Also record, for each value above, what Effect Controls displayed (screenshot is fine).

## What to diff (I do this part)
1. Does V1 (untouched) serialize a Motion component at all, or is it absent until edited?
2. Which element holds Motion, and how do its params map to `PARAM_INDEX` (0,1,2,3,4,5,7-10)?
3. Position `100,200` vs Anchor `100,200`: are the saved numbers `/1920x1080` and `/1280x720`?
4. How are Uniform Scale, Crop and Opacity stored (units, percent vs fraction)?
5. How does a keyframed param differ from a static one (keyframe list, time unit)?
6. Does a text clip's own Transform group need the same handling as Motion, and does the
   panel currently show it as unavailable?

Record results in `docs/PREMIERE_FACTS.md` (rows for anything proven), then extend
`prproj_reader.py` and its tests from the saved file.
