# FEATURES

What the system has and how each feature is reached. `features.py check` tests every entry
point against the code. This is a draft found from the code: regroup by real feature, write
what each does, add the entry points a scan cannot see, link each to VERIFY.md, label it,
and replace every TODO.

## Apply
- what: TODO one sentence: what this feature does for its user
- cli: `apply` @ tools/subtitle_layout.py
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## Callback
- what: TODO one sentence: what this feature does for its user
- route: `/callback` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## Draft
- what: TODO one sentence: what this feature does for its user
- cli: `draft` @ tools/make_gold.py
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## Freeze
- what: TODO one sentence: what this feature does for its user
- cli: `freeze` @ tools/make_gold.py
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## From Corrections
- what: TODO one sentence: what this feature does for its user
- cli: `from-corrections` @ tools/make_finetune_set.py
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## From Srt
- what: TODO one sentence: what this feature does for its user
- cli: `from-srt` @ tools/make_finetune_set.py
- cli: `from-srt` @ tools/make_gold.py
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## Getcredentials
- what: TODO one sentence: what this feature does for its user
- route: `/getCredentials` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## Getrequestid
- what: TODO one sentence: what this feature does for its user
- route: `/getRequestId` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## Home
- what: TODO one sentence: what this feature does for its user
- route: `/` @ transcribe/editor/server.py
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## Index
- what: TODO one sentence: what this feature does for its user
- click: `#btn-load` @ transcribe/editor/static/index.html
- click: `#btn-srt` @ transcribe/editor/static/index.html
- click: `#btn-vtt` @ transcribe/editor/static/index.html
- click: `#btn-save` @ transcribe/editor/static/index.html
- click: `#runVideo` @ uxp/spike18_split_probe/index.html
- click: `#runAudio` @ uxp/spike18_split_probe/index.html
- click: `#copyLog` @ uxp/spike18_split_probe/index.html
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## Jobs
- what: TODO one sentence: what this feature does for its user
- route: `/jobs` @ transcribe/editor/server.py
- route: `/jobs/{job_id}` @ transcribe/editor/server.py
- route: `/jobs/{job_id}/audio` @ transcribe/editor/server.py
- route: `/jobs/{job_id}/save` @ transcribe/editor/server.py
- route: `/jobs/{job_id}/export/srt` @ transcribe/editor/server.py
- route: `/jobs/{job_id}/export/vtt` @ transcribe/editor/server.py
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## Learn
- what: TODO one sentence: what this feature does for its user
- cli: `learn` @ tools/subtitle_layout.py
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## Login
- what: TODO one sentence: what this feature does for its user
- route: `/login` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## Review Report
- what: TODO one sentence: what this feature does for its user
- click: `#export` @ transcribe/review_report.py
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know

## Stats
- what: TODO one sentence: what this feature does for its user
- cli: `stats` @ tools/make_finetune_set.py
- trace: TODO `handler` @ file > `what it calls` @ file > `effect` @ file
- verify: TODO name of the VERIFY.md section that proves it
- status: TODO proven | traced | suspected, then how you know
