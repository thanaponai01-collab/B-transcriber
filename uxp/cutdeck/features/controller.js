// Owns one panel's mutable state, action serialization (act), status updates, and render dispatch.
// Must not know: the DOM, Premiere APIs, or feature-specific logic.

function createController({ render, initialState = {} }) {
  if (typeof render !== "function") {
    throw new Error("createController requires a render function");
  }

  const state = {
    ...initialState,
    busy: false,
    showBusy: false,
    status: (initialState && initialState.status) || { text: "Ready", level: "ready" },
  };

  function setStatus(text, level = "ready") {
    state.status = { text, level };
    render(state);
  }

  async function act(fn) {
    if (state.busy) return;
    state.busy = true;
    state.showBusy = false;
    state.lastStatus = state.status;
    state.status = { text: "Processing…", level: "busy" };
    let busyTimer = setTimeout(() => {
      if (state.busy) {
        state.showBusy = true;
        render(state);
      }
    }, 150);
    render(state);
    try {
      await fn();
      if (state.status.level === "busy") {
        state.status = { text: "Ready", level: "ready" };
      }
    } catch (error) {
      const text = (error && error.message) || String(error);
      state.status = { text, level: "error" };
      console.error(error);
    } finally {
      clearTimeout(busyTimer);
      state.busy = false;
      state.showBusy = false;
      render(state);
    }
  }

  return {
    state,
    act,
    setStatus,
    render: () => render(state),
  };
}

module.exports = {
  createController,
};
