---
name: cold-open-titles
description: How CFD cold-open titles are made: pink caller / blue host text from the template .mogrt, transcribed from the user's In/Out
type: preference
status: current
updated: 2026-11-27
---
- **The user builds the cold open** on `Editing` (CFD 99: 0–16.06, six pieces of clip 06), marks it In/Out and
  leaves a sample title. The agent transcribes the marked span and puts one title per piece. *(confirmed 2026-11-27)*
- **Colour by speaker:** caller = **pink**, host = **blue**. *(confirmed: "the host is the blue one, caller is pink")*
  On CFD 99 every piece was the caller, so all five titles were pink.
- **How it was placed (CFD 99):** `place_text` from `6. ASSETS\20261111 - template.mogrt`, with `styles` on all
  4 text layers: fill #FF37F3, stroke #FFDEFD. Vector Motion scale 82. Position (0.6556, 0.315) on the close-up
  and (0.6556, 0.145) on wide shots, so the text clears the caller's head. The user's sample title was then removed.
  *(seen: the user's own pink title has a different layout, so the agent matched it on screen and didn't copy it)*
- `place_text` refuses if any clip sits later on the track: place in time order, then trim each title to its piece.

**Why it matters:** the cold open is the long form's hook; the wrong colour reads as the wrong speaker.
**How to apply:** read which speaker each piece is before choosing a colour, check one frame per title, and
put the wording through [[wording-check]]. Related: [[host-quote-style]], [[long-form-layout]]
