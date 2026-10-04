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
const IDLE_POLL_MS = 1000;
const ACTIVITY_WINDOW_MS = 2000;

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
  let lastActivityTime = 0;

  function noteActivity() {
    lastActivityTime = Date.now();
  }

  let lastStateJson = "";
  async function refreshAlignSequence() {
    const next = await readAlignState(ppro);
    lastStateJson = JSON.stringify(next);
    ctl.state.sequence = next.sequence;
    ctl.state.transform = next.transform;
    ctl.render();
  }

  let slideInFlight = false;
  let pendingSlide = null;
  let slidePromise = null;

  let emptyPollCount = 0;
  // Coalesces bursts (a drag-select fires many events): one read at a time, plus one
  // follow-up if more arrived meanwhile.
  async function pollAlignTransform() {
    if (ctl.state.busy) return;
    if (typeof isMainBusy === "function" && isMainBusy()) return;
    if (typeof isMounted === "function" && !isMounted()) return;
    if (slideInFlight) return;
    if (pollInFlight) { pollAgain = true; return; }
    pollInFlight = true;
    try {
      do {
        pollAgain = false;
        const next = await readAlignState(ppro);
        // Avoid flapping the UI to disabled on transient empty reads during timeline selection transitions (up to ~300 ms)
        if (!next.transform.available && ctl.state.transform && ctl.state.transform.available && emptyPollCount < 2) {
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

  function currentPollInterval() {
    return (Date.now() - lastActivityTime < ACTIVITY_WINDOW_MS) ? FAST_POLL_MS : IDLE_POLL_MS;
  }

  function startAlignPolling() {
    if (started) return;
    started = true;
    noteActivity();
    unsubscribeEvents = subscribeSequenceEvents(ppro, () => {
      noteActivity();
      pollAlignTransform();
    });
    alignPollTimer = setInterval(() => {
      const isFastWindow = (Date.now() - lastActivityTime < ACTIVITY_WINDOW_MS);
      if (!isFastWindow) {
        // In idle period: execute poll on every tick (every 1000ms)
        pollAlignTransform();
      } else {
        // In fast period: execute poll on every tick (every 150ms)
        pollAlignTransform();
      }
    }, FAST_POLL_MS);
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

  async function applySlide(field, text) {
    noteActivity();
    if (slideInFlight) {
      pendingSlide = { field, text };
      return slidePromise;
    }
    slideInFlight = true;
    slidePromise = (async () => {
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
    })();
    return slidePromise;
  }

  function slideField(field, text) {
    return applySlide(field, text);
  }

  async function commitField(field, text) {
    noteActivity();
    pendingSlide = null;
    if (slidePromise) {
      await slidePromise;
    }
    return executeWithOptimisticConfirm(
      () => setField(ppro, field, text),
      (st) => {
        const num = parseFloat(String(text).replace(/[%°]/g, "").trim());
        if (Number.isFinite(num) && st && st.fields) {
          if (field === "position-x" && st.fields.position) st.fields.position.x = num;
          else if (field === "position-y" && st.fields.position) st.fields.position.y = num;
          else if (field === "anchor-x" && st.fields.anchor) st.fields.anchor.x = num;
          else if (field === "anchor-y" && st.fields.anchor) st.fields.anchor.y = num;
          else if (field === "scale" && st.fields.scale) st.fields.scale.value = num;
          else if (field === "rotation" && st.fields.rotation) st.fields.rotation.value = num;
        }
      },
      (res) => editSummary(`Set ${field}`, res),
      (res) => editLevel(res),
    );
  }

  async function confirmBackgroundSnapshot() {
    try {
      const next = await readAlignState(ppro);
      const nextJson = JSON.stringify(next);
      if (nextJson !== lastStateJson) {
        lastStateJson = nextJson;
        ctl.state.sequence = next.sequence;
        ctl.state.transform = next.transform;
        ctl.render();
      }
    } catch (e) {
      console.error("CutDeck: background transform confirm failed", e);
    }
  }

  async function executeWithOptimisticConfirm(writeFn, optimisticMutator, summaryFn, levelFn) {
    noteActivity();
    return ctl.act(async () => {
      if (typeof optimisticMutator === "function" && ctl.state.transform) {
        optimisticMutator(ctl.state.transform);
        ctl.render();
      }
      let result;
      try {
        result = await writeFn();
      } finally {
        await confirmBackgroundSnapshot();
      }
      ctl.setStatus(summaryFn(result), levelFn(result));
    });
  }

  return {
    onRefresh: () => ctl.act(async () => {
      noteActivity();
      frameBounds.clearBoundsCache();
      await refreshAlignSequence();
    }),
    onSetField: (field, text) => {
      return executeWithOptimisticConfirm(
        () => setField(ppro, field, text),
        (st) => {
          const num = parseFloat(String(text).replace(/[%°]/g, "").trim());
          if (Number.isFinite(num) && st && st.fields) {
            if (field === "position-x" && st.fields.position) st.fields.position.x = num;
            else if (field === "position-y" && st.fields.position) st.fields.position.y = num;
            else if (field === "anchor-x" && st.fields.anchor) st.fields.anchor.x = num;
            else if (field === "anchor-y" && st.fields.anchor) st.fields.anchor.y = num;
            else if (field === "scale" && st.fields.scale) st.fields.scale.value = num;
            else if (field === "rotation" && st.fields.rotation) st.fields.rotation.value = num;
          }
        },
        (res) => editSummary(`Set ${field}`, res),
        (res) => editLevel(res),
      );
    },
    onSlideField: (field, text) => slideField(field, text),
    onCommitField: (field, text) => commitField(field, text),
    onAnchor: (target) => {
      return executeWithOptimisticConfirm(
        () => setAnchor(ppro, target, measure),
        null,
        (res) => editSummary(`Anchor set to ${target}`, res),
        (res) => editLevel(res),
      );
    },
    onAlign: (edge, to = "frame") => {
      const toSelection = to === "selection";
      return executeWithOptimisticConfirm(
        () => (toSelection ? alignToSelection : alignToFrame)(ppro, edge, measure),
        null,
        (res) => editSummary(`Aligned ${edge}${toSelection ? " to selection" : ""}`, res),
        (res) => editLevel(res),
      );
    },
    onDistribute: (kind, to = "frame") => {
      return executeWithOptimisticConfirm(
        () => distribute(ppro, kind, measure, to),
        null,
        (res) => editSummary(`Distributed ${kind}${to === "frame" ? " across frame" : ""}`, res),
        (res) => editLevel(res),
      );
    },
    onProbe: (name) => ctl.act(async () => {
      noteActivity();
      if (name === "copystatus") {
        await copier.handleProbe("copystatus");
        ctl.setStatus(ctl.state.status.text, "info");
        return;
      }
      await refreshAlignSequence();
      await runProbe(transformProbe, ppro, ctl);
      if (ctl.state.status.level === "ready") ctl.setStatus(ctl.state.status.text, "info");
    }),
    noteActivity,
    currentPollInterval,
    measure,
    refresh: refreshAlignSequence,
    poll: () => {
      noteActivity();
      return pollAlignTransform();
    },
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
