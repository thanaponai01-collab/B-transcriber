# reference features

## Vendored Adobe samples (not this system)
- what: Adobe's sample OAuth panel and a local UXP split probe. They sit in the repo for reference and are not part of the transcriber or CutDeck runtime.
- route: `/login` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- route: `/callback` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- route: `/getCredentials` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- route: `/getRequestId` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- click: `#runVideo` @ uxp/spike18_split_probe/index.html
- click: `#runAudio` @ uxp/spike18_split_probe/index.html
- click: `#copyLog` @ uxp/spike18_split_probe/index.html
- trace: `login` @ reference/adobe/samples/sample-panels/oauth-workflow-sample/server/index.js
- verify: CutDeck panel (UXP)
- status: suspected: found by the scan; not opened and not part of any check

**Not built** (roadmap or reserved, not features):

- No second ASR engine (`passthrough` stands in for engine B), so no agreement signal.
- LLM reconciler tiebreak exists but is off (`reconciler.llm_enabled: false`).
- Speaker diarization: `token.speaker_id` is reserved, always null.
