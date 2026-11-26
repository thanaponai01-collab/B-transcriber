// Owns the HKS gates section: asks the helper for every sequence's gate status (hks_status) and
// keeps its reply in state as given. The verdict is the helper's; this file never judges a draft.
// Must not know: the DOM, Premiere APIs, or how the gates run.
//
// No Adobe API here: the only route is the helper request over core/rpc.js.
// hks_status reads the open project through this panel's own driver (list_project), so a refresh
// is skipped while the panel is busy (the driver would refuse it), never runs inside ctl.act, and
// puts back the status the driver's "Done" message replaced. Each poll costs one list_project
// call and one read of the last save in the helper; while it runs the panel is busy for an instant.

const POLL_MS = 30000;
const DRIVER_DONE = "Done: list project for an outside request.";

function createHksFeature({ ctl, rpc, setTimer = setTimeout, clearTimer = clearTimeout }) {
  let inFlight = null;
  let timer = null;
  let polling = false;

  function refresh() {
    if (inFlight) return inFlight;
    if (ctl.state.busy) return Promise.resolve();
    const before = ctl.state.status;
    let failure = null;
    inFlight = rpc({ type: "premiere", command: "hks_status", args: {} })
      .then((reply) => {
        ctl.state.hks = { ...reply.result, error: null };
      }, (error) => {
        failure = (error && error.message) || String(error);
        ctl.state.hks = { ...(ctl.state.hks || {}), error: failure };
      })
      .finally(() => {
        const now = ctl.state.status;
        if (now !== before && now && (now.text === DRIVER_DONE || now.text === failure)) ctl.state.status = before;
        inFlight = null;
        ctl.render();
      });
    return inFlight;
  }

  function tick() {
    timer = null;
    if (!polling) return;
    refresh().finally(() => {
      if (polling && !timer) timer = setTimer(tick, POLL_MS);
    });
  }

  function startPolling() {
    if (polling) return;
    polling = true;
    timer = setTimer(tick, POLL_MS);
  }

  function stopPolling() {
    polling = false;
    if (timer) clearTimer(timer);
    timer = null;
  }

  return { onRefresh: () => { refresh(); }, refresh, startPolling, stopPolling };
}

module.exports = { createHksFeature, POLL_MS };
