// Owns the Transform panel display state and polling loop; the reads and edits themselves
// live in transform/edit.js (docs/research/cutdeck-transform-panel-plan.md).
// Must not know: the DOM, UI panels, Rough Cut or Sync job semantics.

const frameBounds = require("../transform/frameBounds.js");
const { activeProjectAndSequence } = require("../host/project.js");
const {
  describeField, readAlignTransform, readAlignState, clipModel, editLevel, editSummary,
  setField, setAnchor, alignToFrame, alignToSelection, distribute,
} = require("../transform/edit.js");
const { PROBES, runProbe, createProbesFeature } = require("./probes.js");

const transformProbe = PROBES.find((p) => p.id === "transform");


// The panel keeps this heartbeat poll even with events: Premiere fires no event for a timeline
// click or a Position drag in Effect Controls, so the poll is what picks those up
// (tests/cutdeck_align_panel.test.cjs pins it).
const FAST_POLL_MS = 150;

// Subscribes `handler` to selection changes and sequence switches. EventManager and
// Constants.SequenceEvent {ACTIVATED, SELECTION_CHANGED} are in @adobe/premierepro 26.2.1
// d.ts. Live (2026-09-24): a global ACTIVATED listener fires on sequence switch, but a
// global SELECTION_CHANGED does not — so selection is attached to the active sequence and
// moved on every switch. Returns false if unavailable.
function subscribeSequenceEvents(ppro, handler) {
  const em = ppro && ppro.EventManager;
  const ev = ppro && ppro.Constants && ppro.Constants.SequenceEvent;
  if (!em || typeof em.addGlobalEventListener !== "function" || typeof em.addEventListener !== "function" || !ev) {
    return null;
  }
  let attached = null;
  const attachToActive = async () => {
    try {
      const { sequence } = await activeProjectAndSequence(ppro, { requireProject: false, requireSequence: false });
      if (sequence === attached) return;
      if (attached && typeof em.removeEventListener === "function") {
        try { em.removeEventListener(attached, ev.SELECTION_CHANGED, handler); } catch (_) {}
      }
      attached = sequence || null;
      if (attached) em.addEventListener(attached, ev.SELECTION_CHANGED, handler);
    } catch (error) {
      console.error("CutDeck: could not attach selection listener", error);
    }
  };
  const globalHandler = () => { attachToActive(); handler(); };
  try {
    em.addGlobalEventListener(ev.ACTIVATED, globalHandler);
    attachToActive();
    return () => {
      if (attached && typeof em.removeEventListener === "function") {
        try { em.removeEventListener(attached, ev.SELECTION_CHANGED, handler); } catch (_) {}
        attached = null;
      }
      if (typeof em.removeGlobalEventListener === "function") {
        try { em.removeGlobalEventListener(ev.ACTIVATED, globalHandler); } catch (_) {}
      }
    };
  } catch (error) {
    console.error("CutDeck: sequence event subscribe failed, polling instead", error);
    return null;
  }
}

function createAlignFeature({ ppro, ctl, uxp = null, rpc = null, ensureHelper = null, isMounted = null, isMainBusy = null }) {
  // Copy uses the probes feature's clipboard code, against this panel's own status.
  const copier = createProbesFeature({ ppro, ctl, uxp });
  // Measuring a Graphic's text needs the helper (it compares the two saved frames).
  const measure = rpc && uxp ? async (args) => {
    if (ensureHelper) await ensureHelper();
    return frameBounds.measureDrawnBounds({ ppro, rpc, uxp, ...args });
  } : null;
  let alignPollTimer = null;
  let pollInFlight = false;
  let pollAgain = false;

  let lastStateJson = "";
  async function refreshAlignSequence() {
    const next = await readAlignState(ppro);
    lastStateJson = JSON.stringify(next);
    ctl.state.sequence = next.sequence;
    ctl.state.transform = next.transform;
    ctl.render();
  }

  let emptyPollCount = 0;
  // Coalesces bursts (a drag-select fires many events): one read at a time, plus one
  // follow-up if more arrived meanwhile.
  async function pollAlignTransform() {
    if (ctl.state.busy) return;
    if (typeof isMainBusy === "function" && isMainBusy()) return;
    if (typeof isMounted === "function" && !isMounted()) return;
    if (pollInFlight) { pollAgain = true; return; }
    pollInFlight = true;
    try {
      do {
        pollAgain = false;
        const next = await readAlignState(ppro);
        // Avoid flapping the UI to disabled on a transient 1-tick empty read during timeline selection transitions
        if (!next.transform.available && ctl.state.transform && ctl.state.transform.available && emptyPollCount < 1) {
          emptyPollCount++;
          continue;
        }
        emptyPollCount = 0;
        const nextJson = JSON.stringify(next);
        if (nextJson !== lastStateJson) {
          lastStateJson = nextJson;
          ctl.state.sequence = next.sequence;
          ctl.state.transform = next.transform;
          ctl.render();
        }
      } while (pollAgain);
    } catch (error) {
      console.error("CutDeck: transform poll failed", error);
    } finally {
      pollInFlight = false;
    }
  }

  let started = false;
  let unsubscribeEvents = null;
  function startAlignPolling() {
    if (started) return;
    started = true;
    unsubscribeEvents = subscribeSequenceEvents(ppro, () => { pollAlignTransform(); });
    alignPollTimer = setInterval(pollAlignTransform, FAST_POLL_MS);
  }

  function stopAlignPolling() {
    started = false;
    if (alignPollTimer !== null) {
      clearInterval(alignPollTimer);
      alignPollTimer = null;
    }
    if (typeof unsubscribeEvents === "function") {
      unsubscribeEvents();
      unsubscribeEvents = null;
    }
  }

  let slideInFlight = false;
  let pendingSlide = null;

  async function applySlide(field, text) {
    if (slideInFlight) {
      pendingSlide = { field, text };
      return;
    }
    slideInFlight = true;
    try {
      await setField(ppro, field, text);
    } catch (e) {
      console.error("CutDeck: slide update failed", e);
    } finally {
      slideInFlight = false;
      if (pendingSlide) {
        const next = pendingSlide;
        pendingSlide = null;
        await applySlide(next.field, next.text);
      }
    }
  }

  function slideField(field, text) {
    return applySlide(field, text);
  }

  async function commitField(field, text) {
    pendingSlide = null;
    while (slideInFlight) {
      await new Promise((resolve) => setTimeout(resolve, 10));
    }
    return ctl.act(async () => {
      let result;
      try {
        result = await setField(ppro, field, text);
      } finally {
        await refreshAlignSequence();
      }
      ctl.setStatus(editSummary(`Set ${field}`, result), editLevel(result));
    });
  }

  return {
    onRefresh: () => ctl.act(async () => {
      frameBounds.clearBoundsCache();
      await refreshAlignSequence();
    }),
    onSetField: (field, text) => ctl.act(async () => {
      let result;
      try {
        result = await setField(ppro, field, text);
      } finally {
        await refreshAlignSequence();
      }
      ctl.setStatus(editSummary(`Set ${field}`, result), editLevel(result));
    }),
    onSlideField: (field, text) => slideField(field, text),
    onCommitField: (field, text) => commitField(field, text),
    onAnchor: (target) => ctl.act(async () => {
      const result = await setAnchor(ppro, target, measure);
      await refreshAlignSequence();
      ctl.setStatus(editSummary(`Anchor set to ${target}`, result), editLevel(result));
    }),
    onAlign: (edge, to = "frame") => ctl.act(async () => {
      const toSelection = to === "selection";
      const result = await (toSelection ? alignToSelection : alignToFrame)(ppro, edge, measure);
      await refreshAlignSequence();
      ctl.setStatus(editSummary(`Aligned ${edge}${toSelection ? " to selection" : ""}`, result), editLevel(result));
    }),
    onDistribute: (kind, to = "frame") => ctl.act(async () => {
      const result = await distribute(ppro, kind, measure, to);
      await refreshAlignSequence();
      ctl.setStatus(editSummary(`Distributed ${kind}${to === "frame" ? " across frame" : ""}`, result), editLevel(result));
    }),
    onProbe: (name) => ctl.act(async () => {
      if (name === "copystatus") {
        await copier.handleProbe("copystatus");
        ctl.setStatus(ctl.state.status.text, "info");
        return;
      }
      await refreshAlignSequence();
      await runProbe(transformProbe, ppro, ctl);
      if (ctl.state.status.level === "ready") ctl.setStatus(ctl.state.status.text, "info");
    }),
    measure,
    refresh: refreshAlignSequence,
    poll: pollAlignTransform,
    startPolling: startAlignPolling,
    stopPolling: stopAlignPolling,
    describeField,
    readAlignTransform: (seq) => readAlignTransform(seq, ppro),
    readAlignState: () => readAlignState(ppro),
  };
}

module.exports = {
  createAlignFeature,
  subscribeSequenceEvents,
};
