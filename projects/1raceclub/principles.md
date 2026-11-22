# 1RaceClub principles (the why)

The F1 channel's own principles. Read [the main principles](../PRINCIPLES.md) first; where this file
departs from them, this file wins for 1RaceClub. Moved word for word on 2026-11-22 from the "Editing
principles" section of [workflow-log.md](workflow-log.md), which holds the evidence.

**IDs:** `RC-<n>` = principle *n* below (RC-5 = principle 5). Rules and code cite these IDs.
**Shorts:** [shorts-rules.md](shorts-rules.md) is the later, consolidated version of principles 5–14
(principle, rule today, status). Where the two differ, shorts-rules.md wins; its section 0 (watch time)
is the Short's top principle.


Status: **confirmed** = the user said so; **guess** = inferred from the timeline, needs the user.

### The channel
- **What the viewer comes for:** the user's live reaction to an F1 session. The face and voice
  are the product; F1 footage is context. *(guess)*

### Long reaction video
1. **Keep the moments worth knowing and the hot spots: action, something happening, the
   climax.** Cut everything that isn't one of those (waiting, repeats, setup, off-topic).
   *(confirmed: "pick one that's worth knowing, and the hot spots like action, something
   happened, climax")* Evidence: 80 min → 15 min; cuts heaviest in slow stretches (~40–55%),
   lighter during the action (~27%); whole blocks dropped (pre-show, a 10.7 min gap, post-show).
   Still to learn from the transcript: what "worth knowing" looks like in the user's words.
2. **Chronological, no hook at the start: the session itself is the story arc; the title
   and thumbnail do the hooking.** *(confirmed: "no HL, just plain cutting"; reason is a guess)*
3. **F1 footage is there to give a sense of the moment, as pictures, not as video.** Reason:
   **copyright** (confirmed). Posterize Time 0.2 turns the broadcast into a still image that
   changes every 5 s. That's a **shortcut**: the honest goal is "a still picture of each
   highlight", and capturing a still by hand for every HL took too long. Small + blended for
   the same reason. *(confirmed)*
   - **Also a rate limit** *(confirmed)*: when highlights come close together, posterize
     guarantees the picture changes **at most once every ~5 s**, so it never turns into a
     rapid stream of pictures (which would read as video again).
   - **For the agent:** the goal is *one clear still per highlight, no running broadcast
     video, and never pictures changing faster than ~every 5 s*. Posterize gets both for
     free; picking the frames myself is allowed ("if you want to pick it yourself that's up
     to you") but must keep that minimum gap, e.g. merge highlights that are close together
     under one picture.
1a. **Follow every story along the live, not only the lead fight.** A side story (the Ferraris fighting each other,
   a penalty, a driver coming through the field) keeps each of its beats in the long video: the start of it, each
   turn, and how it ends. *(confirmed: user, 2026-11-22, on the agent's first race cut: "you miss some story there
   like contact of ferrari, dont miss those along the live")* How to check: list every storyline from the
   transcript (driver/team names), then make sure each one's beats are in the keep list.
1b. **Every kept moment is a whole sentence: never cut out mid-sentence or inside a word.** A moment starts
   and ends at a real pause in the voice (on this channel a gap of 0.6 s or more between transcript lines, where the
   median gap is 0.19 s). The silence cut then runs with speech protection on. *(confirmed: user, 2026-11-22, on the
   agent's v3 race cut: "dont cut the sentence out like mid way, finish it")* How to check: extend each keep range
   back and forward to the nearest pause, then read the final with `premiere_timeline_transcript`; its
   `cuts_in_sound` must show no cut with a word in it.
4. **Cut method: delete pieces and leave gaps, close them in batches.** Keeps the timeline
   readable against the source while reviewing. *(guess)*

### Short
5. **The first 1–2 s must stop the scroll before anything is explained.** Two ways seen:
   (a) move the peak to the front, then play the build-up (Ferrari: the "oh no" reaction);
   (b) open on the strongest *source* moment itself when the story starts with it (Russell:
   the real team radio plays first, nothing moved). Not a rule that the peak always goes
   first. **The opener can be anything; the principle is watch time: choose whatever will
   make people keep watching. (a) and (b) are examples, not a menu.** *(confirmed)*
6. **Prove the claim on screen, readable on a phone:** zoom into the timing tower so the
   viewer sees LEC/HAM in the drop zone in under 2 s. *(guess)*
7. **Title text on the hook = the story in a few words, for viewers with sound off.**
   *(guess)*
8. **Shorts frame layout** *(confirmed)*:
   - **With an image/video under me:** the top part (face cam) ends at **~740 px from the
     top**, and **my chin must sit above that line**. The image below fills the rest
     (740–1920). Today's file matches: F1 at 109%, bottom-anchored = 1177 px tall, so its top
     edge is at 1920 − 1177 = **743 px**.
   - **Only me on screen:** fill the visible Shorts frame with the face cam (the full-screen
     face beat at ~0:12.5 today).
   - Why (guess): face is the reaction, F1 is the cause; the face stays big and readable, and
     the chin above the seam keeps the face from being cut by the image.
   - The face-cam position is re-set per Short to put *this* chin above the line (y 0.257 in
     Ferrari, 0.273 in Russell): the rule is the chin line, not a number. *(seen in both)*
   - The "picture changes at most every ~5 s" limit (principle 3) is a **long-video** rule.
     In a Short the still changes with each spoken line, every 1–2 s at the fast part.
     *(seen in both)*
9. **Shorts copyright limits:** F1 video **at most 3 s**; normally a **frame hold / captured
   still** stretched across the whole part where the user commentates on it. **Cut out every
   F1 logo** (F1 / F1 TV bugs in the corners: the 109% framing crops ~500 px off each side).
   *(confirmed)*
10. **What to show below is a story choice, not a fixed crop:** the timing tower, sector
   times, the onboard, whatever proves what the user is talking about at that moment. Crop
   and zoom it to follow the story. The agent decides this itself. *(confirmed: "as you want,
   following the story")*
11. **SFX mark emotional beats and never compete with the voice:** a boom on the hook and the
    payoff, a ticking clock for suspense before a reveal, a meme sound on a reaction. They sit
    well under the voice. *(guess)*
12. **Punch-in = point the viewer at one thing** (the full Q2 tower at that beat). *(guess)*
13. **Pick the Short while cutting the long video:** a self-contained ~20–25 s moment with
    setup, peak and payoff that needs no context. *(guess)*

14. **Controversy is a top Short pick.** A moment people will argue about (team orders, a
   radio row, a driver told "no") is worth a Short on its own, e.g. Russell on the Mercedes
   radio wanting to go after Antonelli and the team saying no. *(confirmed: user, 2026-11-21:
   "that's a controversial clip, put that in principle")*

