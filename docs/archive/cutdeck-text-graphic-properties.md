# CutDeck Research: Text Graphic Properties & Transform in Premiere Pro

**Date:** 2026-09-24  
**Scope:** Adobe Premiere Pro UXP API (`@adobe/premierepro` 26.2.1 / 26.5.1), ExtendScript / CEP API, `.prproj` XML schema, and CutDeck's Transform & Align panel (`uxp/cutdeck/`).  
**Investigated against:** Primary source definitions (`reference/adobe/typings/premierepro-26.5.1.d.ts`, `api/premierepro.txt`), runtime probe logs (`UXPLogs_2026-09-24`), Adobe Developer documentation, and community findings.

---

## 1. Executive Summary & Root Cause Analysis

### The Problem / Weakness
In the current Transform & Align panel (`uxp/cutdeck/core/alignPanel.js`, `features/align.js`, `transform/params.js`), Graphic clips (created with the Type Tool or Essential Graphics) represent the biggest functional gap:
1. **Misleading Transform Readout & Edits:** The panel inspects and edits `AE.ADBE Motion` (fixed clip motion). On a text graphic, `AE.ADBE Motion` remains at the sequence center (`[0.5, 0.5]` $\rightarrow$ 960, 540 in 1080p), while the text was actually positioned, scaled, and rotated via its **Text Layer component** (`AE.ADBE Text`) or **Vector Motion** (`AE.ADBE Graphic Group`). The panel shows default values (960, 540), and typing new values moves the entire clip canvas rather than the text itself.
2. **Heavyweight & Fragile Bounds Measurement (Phase 5 Alignment):** Because Premiere Pro provides no direct bounding box or text dimension API (no `sourceRectAtTime`), CutDeck currently measures text bounds using an image diff (`transform/frameBounds.js`):
   - Exports the sequence frame with the clip enabled (`exportSequenceFrame`).
   - Hides the clip via `item.createSetDisabledAction(true)` (**burns an undo step in Premiere!**).
   - Exports the frame again without the clip.
   - Unhides the clip via `item.createSetDisabledAction(false)` (**burns a second undo step!**).
   - Sends both frames over WebSocket to the Python helper (`cutdeck/frame_bounds.py`) to run PIL `ImageChops.difference`.
   - *Failure modes:* Requires Python helper running, requires playhead to be over the clip, creates screen flicker, pollutes user's undo stack with 2 unwanted steps, and fails or skews if video underneath has noise/motion.
3. **Inaccessible Text Content & Typography Properties via Standard UXP:** Param index 0 (`Source Text`) of `AE.ADBE Text` is a black box in Premiere's UXP API: `getStartValue()` resolves empty, and `getValueAtTime()` throws errors.

---

## 2. Anatomy of a Text Graphic in Premiere Pro

When a user creates text on the timeline (Type Tool or Essential Graphics), Premiere Pro creates a `VideoClipTrackItem` with a specific component chain hierarchy:

```
[VideoClipTrackItem: "Graphic"]
  ├── [0] Opacity        ("AE.ADBE Opacity")
  ├── [1] Motion         ("AE.ADBE Motion")       <-- Clip-level fixed motion (CutDeck currently reads this)
  ├── [2] Vector Motion  ("AE.ADBE Graphic Group")<-- Essential Graphics root container
  └── [3] Text Layer     ("AE.ADBE Text")         <-- Individual text layer (can have multiples)
      └── (Optional: Shape Layer "AE.ADBE Shape", etc.)
```

### Parameter Map for `AE.ADBE Text` (22 Parameters)
Verified via runtime inspection (`UXPLogs_2026-09-24_17-50-04_158157.log`, Premiere Pro 26.5.1):

| Param Index | Display Name / Role | Stored Type & Structure | UXP API Access Status | Effect Controls / Properties Mapping |
| :--- | :--- | :--- | :--- | :--- |
| **0** | **Source Text** | `ArbVideoComponentParam` (binary blob) | ❌ **FAILS** in UXP & ExtendScript (`getStartValue` empty) | Text string, font, size, styles, colors |
| **1** | Transform Enable | Boolean | ✅ Readable / Writable | Text Transform toggle |
| **2** | **Position** | `PointF` (`[x, y]` array, sequence fraction) | ✅ **WORKS** (`getStartValue`, `createSetValueAction`) | Text Position in pixels: `(x * W, y * H)` |
| **3** | **Scale** | Number (percentage, e.g. 100) | ✅ **WORKS** | Text Scale (Height / Uniform) |
| **4** | **Horizontal Scale** | Number (percentage, e.g. 100) | ✅ **WORKS** | Text Horizontal Scale Width |
| **5** | Uniform Scale | Boolean (`true`/`false`) | ✅ **WORKS** | Lock Aspect Ratio checkbox |
| **6** | **Rotation** | Number (degrees) | ✅ **WORKS** | Text Rotation angle |
| **7** | Opacity | Number (percentage) | ✅ **WORKS** | Text Layer Opacity |
| **8** | **Anchor Point** | `PointF` (`[x, y]` canvas fraction) | ✅ **WORKS** | Text Anchor Point relative to baseline |
| 9–17 | Internal / Keyframe flags | Flags & integers | Internal | Interpolation / baseline anchors |
| **18** | Parent Width | Number | ⚠️ Always reads `0` for Point Text | Container width (Box text only) |
| **19** | Parent Height | Number | ⚠️ Always reads `0` for Point Text | Container height (Box text only) |
| 20 | Parent Rotation | Number | Reads `0` | Container rotation |
| 21 | Flag | Boolean | Internal | - |

---

## 3. Investigating Every API Route

### Route A: Adobe UXP API (`@adobe/premierepro` 26.2.1 / 26.5.1)

#### 1. What Works 100% in UXP Today
*   **Text Layer Transform:** Param indices 2 (Position), 3 (Scale), 4 (Horizontal Scale), 6 (Rotation), and 8 (Anchor Point) on `AE.ADBE Text` are fully readable and writable using standard UXP:
    ```javascript
    // Reading Text Position
    const keyframe = await textParam.getStartValue();
    const [normX, normY] = keyframe.value.value; // e.g. [0.4778, 0.4574]
    const pxX = normX * seqFrame.width;
    const pxY = normY * seqFrame.height;

    // Writing Text Position
    const kf = textParam.createKeyframe(new ppro.PointF(newNormX, newNormY));
    compoundAction.addAction(textParam.createSetValueAction(kf));
    ```
*   **Vector Motion Transform:** `AE.ADBE Graphic Group` (indices 0 Position, 1 Scale, 2 Scale Width, 4 Rotation, 5 Anchor Point) is also fully readable and writable.

#### 2. What Fails in UXP
*   **`Source Text` (Parameter 0):**
    - `param.getStartValue()`: Resolves empty object `{ present: false }`.
    - `param.getValueAtTime(tickTime)`: Throws `"not supported for these value types. Use GetKeyframeAtTime"`.
    - `param.getKeyframePtr(tickTime)`: Throws `"Illegal Parameter type"`.
    - `param.areKeyframesSupported()`: Returns `false`.
*   **Cause:** Adobe has not implemented native JavaScript marshalling for Premiere's internal `ArbVideoComponentParam` (Arbitrary Data Type) in UXP.

---

### Route B: Adobe ExtendScript / CEP API

*   **Native Text Clips:**
    - `trackItem.components[i].properties[0].getValue()` returns a corrupted binary character (e.g. `\u0164`), not text.
    - Calling `.setValue("string")` causes the text element to become blank or corrupts the component.
    - Official Adobe CEP sample (`PProPanel`) and commercial plugin developers (e.g., Mamoworld / Automation Blocks, Easify) confirm that native Premiere Pro text layers cannot be manipulated via ExtendScript.
*   **MOGRTs Authored in After Effects:**
    - `trackItem.getMGTComponent()` exposes custom properties defined in After Effects Essential Graphics.
    - These properties return JSON strings containing `textEditValue` and `fontTextRunLength`.
    - **Limitation:** Does **not** work on native Premiere Pro text layers (`getMGTComponent()` returns `null` or undefined).

---

### Route C: Project File (`.prproj` XML) & Binary Stream Parsing

Premiere Pro `.prproj` files are gzip-compressed XML documents.
When inspecting a Graphic Text layer in the project XML:

```xml
<Component ObjectUID="..." ClassID="...">
  <DisplayName>Text</DisplayName>
  <MatchName>AE.ADBE Text</MatchName>
  <ComponentParams Version="1">
    <ArbVideoComponentParam ObjectID="..." ClassID="...">
      <ParamName>Source Text</ParamName>
      <StartKeyframeValue>
        AAAA/wAAAA... [Base64-encoded binary stream]
      </StartKeyframeValue>
    </ArbVideoComponentParam>
  </ComponentParams>
</Component>
```

#### Binary Structure of `StartKeyframeValue`:
The decoded Base64 stream contains an Adobe Text Document binary structure:
1. **Header & Versioning:** Adobe FlatBuffers / serialization header.
2. **Text String:** UTF-8 / UTF-16 text payload with length prefix.
3. **Font Specification:** PostScript font name (e.g., `LucidaCalligraphy-Italic`, `THSarabunNew-Bold`).
4. **Style Runs:** Font size (float), tracking, leading, faux bold/italic flags, justification (0=Left, 1=Center, 2=Right).
5. **Color Blocks:** RGBA fill and stroke color values.

*Feasibility:* Fast offline extraction is possible by reading the project file or auto-save via Python helper. However, live runtime extraction of unsaved edits is restricted because Premiere does not expose this buffer to plugins in real time.

---

### Route D: Font Metrics & Glyph Geometry (Bypassing Pixel Diff)

In `docs/PREMIERE_FACTS.md` (proven live on 2026-09-24):
*   In the text layer's anchor coordinate space (`storedAnchor * sequenceSize`):
    - **Left edge:** $x = 0$
    - **Baseline:** $y = 0$
    - **Width:** Exact sum of glyph advances: $\sum \text{glyph\_advance} \times \frac{\text{fontSize}}{\text{UPM}} \times \text{scaleX}$.
    - **Height / Bounds:** Defined by font ascender, descender, and glyph bounding boxes.

By calculating text width and height mathematically from the font file (`fonttools` / FreeType in Python helper):
- **Execution time:** $\approx 1 \text{ ms}$ (instantaneous vs $\approx 500\text{–}1500 \text{ ms}$ for two frame exports).
- **Undo Stack Impact:** **Zero undo steps** (eliminates the 2 undo steps caused by hiding/showing the clip).
- **Reliability:** 100% immune to background video noise or playhead position.

---

## 4. Comparison Matrix: How to Get Text Graphic Properties

| Property Category | Property Name | UXP API (`ppro`) | ExtendScript / CEP | `.prproj` XML / Binary | Font Metrics Engine |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Layer Transform** | Position | ✅ `param[2]` (`PointF`) | ⚠️ Index fragile | ✅ Available | N/A |
| | Scale / H-Scale | ✅ `param[3], [4]` | ⚠️ Index fragile | ✅ Available | N/A |
| | Rotation | ✅ `param[6]` | ⚠️ Index fragile | ✅ Available | N/A |
| | Anchor Point | ✅ `param[8]` (`PointF`) | ⚠️ Index fragile | ✅ Available | N/A |
| **Vector Motion** | Position / Scale / Anchor | ✅ `AE.ADBE Graphic Group` | ⚠️ Index fragile | ✅ Available | N/A |
| **Text Content** | Source Text String | ❌ Blocked (`param[0]`) | ❌ Corrupted / U+0164 | ✅ Base64 decodable | N/A |
| **Typography** | Font PostScript Name | ❌ Not exposed | ❌ Not exposed | ✅ In binary stream | N/A |
| | Font Size / Leading | ❌ Not exposed | ❌ Not exposed | ✅ In binary stream | N/A |
| | Alignment (L/C/R) | ❌ Not exposed | ❌ Not exposed | ✅ In binary stream | N/A |
| **Bounding Box** | Rendered Width / Height | ❌ (`param[18/19]=0`) | ❌ No `sourceRect` | ❌ Not precomputed | ✅ **Instant & Exact** |
| | Drawn Pixel Extent | ⚠️ Via pixel diff (slow) | ⚠️ Screenshot diff | ❌ Not precomputed | ✅ Matches glyph box |

---

## 5. Strategic Recommendations for the Transform & Align Panel

To eliminate the current weaknesses of the Transform & Align panel, implement the following four-tier enhancement:

### Tier 1: Graphic-Aware Transform & Input Seam (Immediate Win)
*   **Fix `readAlignTransform`:**
    Detect whether the active track item is a Graphic (`isGraphic(item)`).
    If it is a Graphic with text layers, read the **Text Layer transform** (`AE.ADBE Text` params 2, 3, 4, 6, 8) or Vector Motion, rather than `AE.ADBE Motion`.
*   **Display:** Show the actual text layer coordinates in the panel inputs instead of `960, 540`.
*   **Fix `setField`:** When the user types a position or scale value, write to `AE.ADBE Text` Position / Scale directly.

### Tier 2: Eliminate the 2-Undo-Step Pixel Diff in Alignment
*   Currently, `alignToFrame` toggles clip disabled state (`item.createSetDisabledAction(true)` then `false`) to capture before/after PNGs. This litters the user's undo history.
*   **Short-term improvement:** If frame diffing must be used, perform the diff against a clean background or avoid toggling track item properties if another capture path is available.
*   **Long-term improvement:** Replace image diffing with geometric text metrics (Tier 3).

### Tier 3: Font Metrics Bounding Box Engine
*   Feed the font PostScript name and text string to the Python helper (`fonttools`).
*   Compute glyph advances and exact bounding box analytically ($W = \sum \text{advances}$, $H = \text{ascent} - \text{descent}$).
*   Eliminates all frame exports, disk writes, playhead position restrictions, and undo steps.

### Tier 4: Text Content Inspection via XML Parser
*   For workflows needing text inspection (e.g. subtitle sync, text replacement, auto-captioning):
    Expose a helper service that reads the project's XML or auto-save cache and unpacks the `ArbVideoComponentParam` Base64 stream to extract text strings, fonts, and font sizes.
