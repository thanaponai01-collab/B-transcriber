# Rough Cut XML retirement contract

Owner authorization: "do them", 2026-10-11, following the XML architecture review.
Target: local source and offline verification. No live timeline edits or release.

- Rough Cut analyses the panel's JSON sequence snapshot and returns frame cuts.
- The shared helper, extraction and sequence timing have names independent of XML.
- XML-file MCP tools and XML rewriting are retired; old commands explain the replacement.
- Old prepared XML jobs fail clearly without starting a worker. Existing JSON jobs remain readable.
- Analysis preserves reference-track selection, range offsets, speech protection, cut rules,
  duration guards and the captured native-plan golden output.
- Newly analysed cuts carry their source audio snapshot. Applying them after audio timing,
  source media, speed, enabled state, track state or sequence duration changes must fail before
  cloning or editing. Clip enumeration order alone must not invalidate the snapshot.
- Both panel and agent apply paths use the same guard. A stale result is discarded by the panel
  so the next Rough Cut can analyse again; an unrelated wrong sequence remains resumable.
- Native application keeps bounded fresh-handle recovery, original preservation and exact read-back.

Historical XML samples remain test data, never runtime input. Project-file XML for adjustment
layers, color mattes and read-only .prproj inspection is a separate format and remains supported.

Live Premiere transaction semantics and real GPU ASR are outside the offline proof.
