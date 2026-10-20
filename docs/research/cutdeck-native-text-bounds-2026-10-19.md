# Native text bounds for Transform & Align

Owner request (2026-10-19): reverse engineer Premiere's backend to supply accurate
text bounds for alignment and anchor placement in the existing Transform UXP panel.

## Status

Native callback registration and its geometry reducer are traced in machine code.
The callback is registered in the running Premiere process. A lower-level layout
function returned native rectangle records after a user font-size change. The
selected layer's live Source Text binary was also recovered and decoded, despite
the public UXP read returning empty. No production panel integration is claimed.

## Target identity and evidence

- Installed target: `C:\Program Files\Adobe\Adobe Premiere Pro 2026\Adobe Premiere Pro.exe`.
- File size: 780886536 bytes.
- SHA-256: `b24e2b442a8e0350edbc0c214d2fcae2f68c7d9843ae399e5058d5b5a6786094`.
- Preferred image base: `0x140000000`. Addresses below are preferred virtual
  addresses, not addresses to reuse in a running process. Runtime addresses must
  be module base + RVA and validated against the current build.
- Static observations: local PE parsing, RIP-relative LEA candidates, direct CALL
  candidates, and MSVC dumpbin 14.44.35229.0 disassembly. These are shell evidence,
  not REA native-decompiler Evidence. Byte-pattern reference searches are candidate
  searches; the inspected instructions corroborate the selected references.
- REA runtime Evidence: `ev_53fe173d8f3897ef3968ba6544a5480866d7fc10d762644bf54f1b8bb15a05bc`.
  Read the retained JSON in `output/native-text-bounds/runtime-registration.json`.
  Frida attached to Premiere PID 22880, checked the candidate function's first
  eight bytes, read the callback storage, and reported `registered: true`.
  No callback invocation was observed during the three-second window. REA did
  not bind artifact identity to this runtime observation; the eight-byte check
  is a local corroboration, not a runtime image digest.

## Traced native path

| Role | Preferred VA | RVA |
| --- | --- | --- |
| `BE::GetGetBoxTextBoundsCallback` string | `0x166605048` | `0x26605048` |
| Getter entry | `0x1599ce330` | `0x199ce330` |
| `BE::RegisterGetBoxTextBoundsCallback` string | `0x166605020` | `0x26605020` |
| Registration entry | `0x1599ce4f0` | `0x199ce4f0` |
| Registration call site | `0x15ba8b35f` | `0x1ba8b35f` |
| Registered callback | `0x15ba92460` | `0x1ba92460` |
| Layout acquisition called by callback | `0x15ba78320` | `0x1ba78320` |
| Geometry reducer called by callback | `0x15ba91db0` | `0x1ba91db0` |
| Callback storage | `0x16d40f230` | `0x2d40f230` |

The registration site puts `0x15ba92460` into the callback wrapper, then calls
registration. The getter copies the wrapper whose implementation pointer is at
storage + `0x38`. Two inspected getter call sites are `0x1596ba730` and
`0x1596babd0`; the first invokes the wrapper through vtable + `0x10`.

The callback zeroes a 16-byte output, calls layout acquisition with the incoming
second argument and two true flags, then calls the geometry reducer with the
layout and incoming third argument. It copies the resulting 16 bytes to output.
The third argument is read as two float scale factors by the geometry reducer.
Exact input ownership, thread requirements and public object correspondence
remain unresolved. Do not call this address directly from a plugin yet.

## Geometry observed in instructions

The reducer checks layout byte + `0x10`. On the enabled path it reads:

- Four floats at layout + `0xb60`, `0xb84`, `0xb88`, `0xb8c`.
- A vector between pointers at + `0xbd0` and + `0xbd8`.
- Vector elements are 20 bytes. It unions four float fields at element offsets
  +4, +8, +12, +16 using min/min/max/max.
- It calculates two minima and two extents, expands them using the layout
  floats, multiplies each axis by the respective incoming scale float, and
  writes four floats to output at offsets 0, 4, 8, 12.

An x/y/width/height interpretation is plausible from the subtraction and extent
arithmetic, but has NOT been validated against a selected text graphic. The
records' semantic type and the expansion fields' meanings are unknown. A name
containing `BoxText` does not prove that this covers point text or matches the
blue selection box, glyph ink, shadow/stroke bounds, or final sequence bounds.

`sourceRectAtTime` also occurs in the executable, beside expression-engine
identifiers. This does not establish a Premiere UXP method or a callable shortcut.

## Panel seam and acceptance

- Existing text transform reads: `uxp/cutdeck/transform/params.js`,
  `readGraphicLayers` (`AE.ADBE Text`).
- Existing consumers: `uxp/cutdeck/transform/edit.js` align and anchor operations.
- Existing measurement provider: `uxp/cutdeck/transform/frameBounds.js`,
  `measureDrawnBounds`, returning `{left, top, right, bottom}` in sequence pixels.
- Existing helper: `cutdeck/frame_bounds.py`. It measures rendered pixels;
  native layout bounds must be distinguished from that meaning.

The next required experiment is to observe native calls on a selected test text
graphic, compare the returned rectangle with Premiere's own box, and establish
which input identifies the selected text layer. Then prove point text, paragraph
text, Thai shaping, multiple lines, mixed styles, stroke/shadow, rotation,
nonuniform scale, Vector Motion and clip Motion before replacing measurement.
No font-metric estimate should be presented as Premiere's exact geometry.

## Remaining blockers

Initial port inspection was inconclusive. A diagnostic helper launch was attempted
with the existing Python 3.11 runtime and virtualenv packages, using the separate
`output/native-text-bounds/helper-jobs` directory, but failed with bind error 10048
because the port was already occupied (see `helper.stderr.log`). The existing
helper's driver connected and accepted read-only commands.
Read-only selection inspection subsequently confirmed exactly one Graphic in
`Editing`, 1920x1080, with one text layer and default clip/Vector Motion. Evidence:
`output/native-text-bounds/selected-graphic.json`. No transform was written.
The native engines advertised by REA were unavailable (Ghidra not configured,
Hopper unsupported on Windows, IDA not configured); local dumpbin allowed the
bounded static trace above without installing anything.

## Live findings after owner-operated changes

- Evidence `ev_65cec0dbd3ae3db79fc4a9c074359aa70344979af91f52e8a1ac0e3a44263017`
  (retained in `output/native-text-bounds/live-layout.json`) captured sixteen
  layout calls. The first 16-event display bound was explicit in the observer.
  Records included `[5.7789903, -58.5384789, 589.9660645, 17.4866867]`.
  Layout byte +0x10 was zero: the box-text reducer would return zeros for this
  layout, so that callback alone is insufficient for the selected point-text case.
- Native `MF::BinaryData` Source Text getter entry: preferred VA `0x159d43d10`,
  RVA `0x19d43d10`. It writes a keyframe whose +0x38 field is a shared-pointer
  pair. Its first pointer references a binary descriptor: data pointer at +0,
  byte count at +8. This was observed on the selected Graphic during the panel's
  existing read-only `transform` probe, not by calling an invented UXP API.
- Evidence `ev_af0bfee3d137fd665ae84703fc4b3b233655c8aca52ff907bf4499705e8a0450`
  recovered 372 bytes, SHA-256
  `9b5e3db179e2c3d4e5b5e22d83f09dfd2be3e0cac3626b5007f4d2f8c2668bf3`.
  The existing decoder read `New Text Layer`, `DBHeavent-Med`, size
  `194.01219177246094`, leading -20, fill [220,211,179]. Evidence bytes:
  `output/native-text-bounds/source-text-binary.json`.
- Layout acquisition's second argument begins with pointer-like fields, but its
  exact type is unresolved. The input header was captured in
  `output/native-text-bounds/live-correlation.json`. A later observer tried one
  extra dereference; the controlled font-size test showed that the resulting
  object's +8 field was another pointer, not a byte count. The attempted
  same-call source/geometry pairing was therefore rejected. Scrubbing alone
  produced no new acquisition during its observation window; cache reuse is an
  inference, not a proven explanation.

Still required: a same-call document/geometry pair, exact equality with the
selected Source Text blob, and a visual/renderer comparison that establishes
what these rectangle records bound. Reading a document and reading a rectangle
separately does not establish that they belong to each other.

## Controlled check and stopping state

The owner entered font size 207.13 and pressed Enter. Evidence
`ev_a30a2776d6b5f786b9fc3353618ec831977c8dbc851460b1ed988d2e7a9e7465`
captured eight layout entries under the observer's explicit eight-entry limit,
but no validated source-bytes/rectangle pair. The alleged byte counts were
pointer-sized values, so no bytes were read through those guessed descriptors.
Do not describe the 194.0122 Source Text capture or the earlier rectangle as
proven to represent the final 207.13 selected-layer state. Both are real native
observations; their association remains unproven.

The advertised SDK does not close that gap: the Control Surface host suites
provide no selected text-document handle. `PrSDKVideoSegmentSuite.h` exposes
graphics transforms through native timeline/render-node handles, but no proven
conversion from the selected UXP clip/layer to this layout input. An optional
native plugin could carry requests, but cannot yet resolve them correctly.

Also required before integration: the current bounds cache keys transform values
without a Source Text/font revision (`edit.js`, `boundsSignature`). A native
provider must key by document revision/hash as well as clip/layer/time, or avoid
reusing stale rectangles after text edits.

No product code was changed. All diagnostic Frida hooks were detached. The
attempted diagnostic helper had already exited after its bind failure; it was
not left running, and the existing helper was not stopped. Existing project/job
storage was not modified. No transform or anchor write was issued. Full retained
runtime observations and observer sources are under `output/native-text-bounds/`.

Next: resolve the layout input's object type and document ownership from its
producer, then prove an exact selected-document-to-layout association. Only
after that, implement the provider at `measureDrawnBounds` and test its rectangle
semantics against the renderer and Premiere's selection box.

## Resumed producer trace

- Native layout acquisition is `0x15ba78320` through `0x15ba79149`, bounded by
  PE unwind records. Its input's first owner is passed to `0x1595a53c0`, which
  copies a shared-pointer pair. The copied document goes to `0x1599be7b0` to
  contribute to a layout cache key. This disproves treating the first owner
  as an MF::BinaryData descriptor.
- `0x1599bed10` materializes a FlatBuffer-backed document: it follows the
  document's owned data, reads a table pointer at data +0x18, parses fields,
  then clears the retained serialized owner and table pointer. A layout
  document may therefore no longer retain its original serialized bytes.
- Decoder `0x1599b5b90` checks the marker `0x11223344`, retains the binary
  owner, and sets that table pointer. Caller `0x1595a3b50` copies an incoming
  Source Text buffer from offset +8 into an owned descriptor and constructs
  a shared TextDocument through this decoder. This gives a specific producer
  to observe, rather than guessing a descriptor in the layout input.
- Saved disassembly: `layout-acquisition-resume.asm.txt`,
  `document-materialize.asm.txt`, `source-document-decode.asm.txt`, and
  `text-document-factory.asm.txt` under `output/native-text-bounds/`.
- The executable also registers scripting `TextDocument`, `TextLayerObject`,
  `GraphicsTrackItemObject`, and graphics operations. A read-only runtime
  export inventory was added to the existing `textcanvas` diagnostic and run
  after the owner reloaded CutDeck. All five candidate graphics/text class
  names were undefined in `require('premierepro')`; TextSegments is exposed
  but does not provide these native graphics classes. Evidence:
  `output/native-text-bounds/runtime-graphics-exports-reloaded.json`.
- Diagnostic regression check: all 7 `cutdeck_layout_probe.test.cjs` checks
  passed. Adobe API member check passed across 48 panel files. No graphics
  accessor was called speculatively.

### Live observation approval blocker

Prepared `tools/native-text-bounds/trace-document-layout.js` to observe the
document factory and layout acquisition, matching native document identity.
Automatic approval review rejected the initial script because it would send
live Source Text bytes through REA. A revision computes SHA-256 in Premiere
and sends only the digest, byte count, identifiers and rectangle geometry;
automatic review rejected this too because that derived payload and external
REA destination were not specifically authorized. Neither script was loaded.
The new, empty Frida session was closed. No workaround was executed.

The next live step needs explicit owner authorization for those derived values
through REA. The prepared revision does not send text or binary contents.
Selected-document/layout identity and accurate bounds integration remain
unproven pending that observation and subsequent renderer comparison.

Owner explicitly approved running that revision ("yes run it"). The unchanged
hash/count/geometry-only probe loaded successfully in Premiere PID 22880:
`ev_e6ecce90dd44ee777f3bc03907560ec1211c591fce4c82efebae079dc6373a78`,
script SHA-256 `2ecc8a8c30ae9a72a892ae8e60400c22d592c6805778a297e339d13ed9147c9d`.
It reported ready after checking the two function prologues. This establishes
observer readiness only; capture and document/layout identity remain pending.

### Lifetime-corrected producer/layout capture

The first approved capture exposed address reuse after the observer's unique-address
limit. Its late source-ID associations are unreliable and must not establish revision
identity (`approved-document-layout-capture.json`). The replacement tracks destruction
at RVA `0x199b6410`, invalidates output addresses for every factory return (including
skipped captures), uses a total factory-call limit, and checks record generation again
at layout return. The destructor is reached from shared-control-block destroy
`0x1595ae290` after adding 0x10 to the control block pointer.

After another owner font-size edit, corrected evidence
`ev_79f24bc3297f6b2b3d837c0595695c41479e62f197842188d8e7708c1179f0c1`
contains 512 constructed and 512 destroyed documents and 256 layout observations.
All 256 carry a live source ID; no observer errors or truncated messages were reported.
Seven distinct 372-byte Source Text hashes each consistently pair with one rectangle.
Example local rectangle: [18.159832, -183.950623, 1853.902344, 54.949955].
Complete evidence: `output/native-text-bounds/lifetime-document-layout-capture.json`.
Observer SHA-256: `1c89313171c67ce1a4d38ba99447189d5411b6aa751fd089f558387ae9deb2ed`.
Only hashes, counts, native identifiers and geometry were sent; no source bytes/text.
The observer session was closed after collection.

Three Node tests pass for destruction/address reuse, replacement during layout, and
capture-limit invalidation (`tests/native_text_observer.test.cjs`); syntax check passes.
These validate the observer's bookkeeping, not production bounds accuracy.

This establishes observed producer-to-layout instance correspondence. It does not yet
establish selected clip/layer attribution, in-place document revision detection, exact
rectangle semantics, sequence coordinate conversion, or a deployable native provider.
Transform integration remains pending those checks and a renderer comparison. UXP's
transform-only cache signature also needs source-revision invalidation before use.
