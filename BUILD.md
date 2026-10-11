# Current work

Foundation refresh, 2026-10-11: existing ClubFriday progress is retained in
[ClubFriday work history](work/clubfriday-history.md); read it for live-run details,
unfinished caption/graphics integration and evidence paths.

Context scope: repository overview, with the ClubFriday backend as the selected
requirement-backed path. No product behavior changes are authorized by this setup.
13 backend tests and 3 panel tests passed. Offset mutation caused 3 failures; the
isolated backend recipe finished strict green (verification/foundation.md).
Historical Python 3.11.9 runtime remains
required for the GPU setup. See [commands](docs/commands.md) and [verification](VERIFY.md).

## Blockers and limits
- Repository-wide current strict green is not established by the selected checks.
- Real Premiere, browser interactions, range extraction and GPU ASR were not run.
- Next owner priority is unknown; historical deferred styled graphic insertion remains
  blocked by the text-write API evidence in the linked work record.

## Rough Cut reliability - 2026-10-11
Owner priority supersedes the earlier transcription CLI foundation next step.
- Proof: `node --test tests/cutdeck_native_cut.test.cjs tests/cutdeck_cut_plan_apply.test.cjs tests/cutdeck_feature_rough_cut.test.cjs` must pass exact golden output, fresh-handle recovery, bounded failure and unchanged-source assertions.
- First-action stale failure reproduced: 14 passed / 4 failed before the fix.
- Bounded recovery implemented in existing split/move transaction loops; 37 targeted
  checks and all 635 panel checks passed. Committed with this recovery record;
  source map: docs/rough-cut.md.
- Evidence: output/rough-cut-reliability/; scoped mutation challenge caught all four
  original failure cases; .verify-evidence/rough-cut-reliability finished strict green.
  Details and limits: verification/rough-cut-reliability.md.

## Next
Run the repaired Rough Cut on the previously failing sequence in live Premiere;
verify read-back and retained original. Read-only readiness currently fails because
Premiere is not running. No real-host success is claimed from the offline tests.
