// Pure planning logic for CutDeck adjustment-layer placement — no host APIs, no DOM.
// Owned by uxp/cutdeck/timeline/adjustmentLayer.js via planPlacements() and assignPlacementLanes().
// See docs/arch-design-cutdeck-panel.md Move 9 (issue #56).

// Groups planned placements into "lanes" so any two that overlap in time never end up in
// the same lane — classic interval-scheduling greedy assignment (sort by start, drop each
// into the first lane whose last-placed end is already <= this start, else open a new lane).
// Needed because transition mode (Shift+Click) centers each AL independently on its own cut:
// when cuts sit closer together than the requested frame width, neighboring ALs' spans can
// genuinely overlap, and placements within one lane never do, by construction.
function assignPlacementLanes(placements) {
  const order = placements.map((_, idx) => idx).sort((a, b) => {
    const pa = placements[a], pb = placements[b];
    if (pa.startTicks < pb.startTicks) return -1;
    if (pa.startTicks > pb.startTicks) return 1;
    return a - b;
  });
  const laneEnds = [];
  const laneOf = new Array(placements.length).fill(0);
  for (const idx of order) {
    const p = placements[idx];
    let lane = laneEnds.findIndex((end) => end <= p.startTicks);
    if (lane === -1) {
      lane = laneEnds.length;
      laneEnds.push(p.endTicks);
    } else {
      laneEnds[lane] = p.endTicks;
    }
    laneOf[idx] = lane;
  }
  return laneOf;
}

// Cover every selected clip's own span, any track — not just V1 (confirmed
// 2026-09-21: the user wants AL over a region where only V2/V3 have a selected
// clip and V1 has nothing there too).
//
// Where more than one selected clip covers the same stretch, only the TOPMOST
// track's clip should drive it — a lower clip hidden underneath a higher one
// must not introduce its own split point there (confirmed 2026-09-21: a V2 clip
// straddling the real boundary between a V4 clip and a V3 clip fragmented what
// should have been 2 clean AL segments into 4 — "it like spot the V2 that is
// under both V3, V4 ... i want it to spot only top layer"). So this is a
// layering resolve, not a plain interval union: assign each breakpoint-bounded
// sub-interval to whichever covering clip has the highest track, tagged with that
// clip's identity, then merge adjacent sub-intervals that resolve to the SAME
// clip. A boundary between two DIFFERENT top clips (even same track, different
// clip) still survives — this only removes splits contributed by a clip that
// never actually wins the region it overlaps.
function resolveTopLayer(rawClipsWithTimes) {
  const taggedClips = rawClipsWithTimes.map((cl, idx) => ({ ...cl, idx }));
  const breakpoints = [];
  for (const cl of taggedClips) {
    breakpoints.push(cl.startTicks, cl.endTicks);
  }
  breakpoints.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const uniqueBreakpoints = breakpoints.filter((b, idx) => idx === 0 || b !== breakpoints[idx - 1]);

  const clipsWithTimes = [];
  for (let i = 0; i < uniqueBreakpoints.length - 1; i++) {
    const segStart = uniqueBreakpoints[i];
    const segEnd = uniqueBreakpoints[i + 1];
    const covering = taggedClips.filter((cl) => cl.startTicks <= segStart && cl.endTicks >= segEnd);
    if (covering.length === 0) continue; // real gap between separate, non-touching selections

    let winner = covering[0];
    for (const cl of covering) {
      if (cl.track > winner.track) winner = cl;
    }

    const last = clipsWithTimes[clipsWithTimes.length - 1];
    if (last && last.winnerIdx === winner.idx && last.endTicks === segStart) {
      last.endTicks = segEnd;
    } else {
      clipsWithTimes.push({ startTicks: segStart, endTicks: segEnd, winnerIdx: winner.idx });
    }
  }
  return clipsWithTimes;
}

function planPlacements({
  mode = "span",
  spans = [],
  frames = 16,
  tpf = 10594584000n,
  cti = 0n,
  clamp = true,
  effectName = "",
  inPoint = 0n,
  outPoint = 0n,
}) {
  const f = BigInt(frames);
  const t = BigInt(tpf);
  const c = BigInt(cti);
  const inP = BigInt(inPoint);
  const outP = BigInt(outPoint);
  const placements = [];

  if (mode === "transition") {
    // -------------------------------------------------------------
    // TRANSITION MODE (Shift+Click): Centered at cuts between adjacent selected clips
    // -------------------------------------------------------------
    const halfFrames = f / 2n;
    const halfTicks = halfFrames * t;

    if (spans.length >= 2) {
      for (let i = 0; i < spans.length - 1; i++) {
        const cLeft = spans[i];
        const cRight = spans[i + 1];

        const diff = cRight.startTicks > cLeft.endTicks
          ? (cRight.startTicks - cLeft.endTicks)
          : (cLeft.endTicks - cRight.startTicks);

        if (diff <= (t * 2n)) {
          const cutTick = cLeft.endTicks;
          let curHalfLeft = halfTicks;
          let curHalfRight = halfTicks;

          if (clamp) {
            const durLeft = cLeft.endTicks - cLeft.startTicks;
            const durRight = cRight.endTicks - cRight.startTicks;
            const maxHalfLeft = (durLeft * 45n) / 100n;
            const maxHalfRight = (durRight * 45n) / 100n;
            if (curHalfLeft > maxHalfLeft) curHalfLeft = maxHalfLeft;
            if (curHalfRight > maxHalfRight) curHalfRight = maxHalfRight;
          }

          const sT = cutTick > curHalfLeft ? (cutTick - curHalfLeft) : 0n;
          const eT = cutTick + curHalfRight;
          placements.push({
            startTicks: sT,
            endTicks: eT,
            name: effectName ? `ADJ_${effectName}_${f}f` : `ADJ_Cut_${f}f`
          });
        }
      }
    }

    // Fallback: If no internal cuts found (e.g. 0-1 clip selected, or clips separated), place at CTI
    if (placements.length === 0) {
      const sT = c > halfTicks ? (c - halfTicks) : 0n;
      const eT = sT + (f * t);
      placements.push({
        startTicks: sT,
        endTicks: eT,
        name: effectName ? `ADJ_${effectName}_${f}f` : `ADJ_Cut_${f}f`
      });
    }
  } else if (mode === "per_clip") {
    // -------------------------------------------------------------
    // PER-CLIP MODE (Ctrl+Click): Dedicated AL per selected clip
    // -------------------------------------------------------------
    if (spans.length > 0) {
      for (let i = 0; i < spans.length; i++) {
        const cl = spans[i];
        placements.push({
          startTicks: cl.startTicks,
          endTicks: cl.endTicks,
          name: effectName
            ? `ADJ_${effectName}`
            : (spans.length === 1 ? "ADJ_Fit" : `ADJ_Clip_${i + 1}`)
        });
      }
    } else {
      // If nothing selected, check In/Out or playhead
      if (outP > inP && inP >= 0n) {
        placements.push({
          startTicks: inP,
          endTicks: outP,
          name: effectName ? `ADJ_${effectName}` : "ADJ_InOut"
        });
      } else {
        const half = (f / 2n) * t;
        const sT = c > half ? c - half : 0n;
        const eT = sT + (f * t);
        placements.push({
          startTicks: sT,
          endTicks: eT,
          name: effectName ? `ADJ_${effectName}_${f}f` : `ADJ_${f}f`
        });
      }
    }
  } else {
    // -------------------------------------------------------------
    // SPAN MODE (Normal Click): Spans the full selection
    // -------------------------------------------------------------
    if (spans.length > 0) {
      let minStart = spans[0].startTicks;
      let maxEnd = spans[0].endTicks;
      for (const cl of spans) {
        if (cl.startTicks < minStart) minStart = cl.startTicks;
        if (cl.endTicks > maxEnd) maxEnd = cl.endTicks;
      }
      placements.push({
        startTicks: minStart,
        endTicks: maxEnd,
        name: effectName
          ? `ADJ_${effectName}`
          : (spans.length === 1 ? "ADJ_Fit" : "ADJ_Span")
      });
    } else {
      // If nothing selected, check In/Out or playhead
      if (outP > inP && inP >= 0n) {
        placements.push({
          startTicks: inP,
          endTicks: outP,
          name: effectName ? `ADJ_${effectName}` : "ADJ_InOut"
        });
      } else {
        const half = (f / 2n) * t;
        const sT = c > half ? c - half : 0n;
        const eT = sT + (f * t);
        placements.push({
          startTicks: sT,
          endTicks: eT,
          name: effectName ? `ADJ_${effectName}_${f}f` : `ADJ_${f}f`
        });
      }
    }
  }

  return placements;
}

module.exports = {
  assignPlacementLanes,
  resolveTopLayer,
  planPlacements,
};
