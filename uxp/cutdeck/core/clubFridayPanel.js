function createClubFridayPanel(document) {
  const get = id => document.getElementById(id);
  return {
    mount(root) {
      const view = get("view-clubfriday");
      root.appendChild(view); view.hidden = false;
    },
    render({ busy, session, message }) {
      if (message) get("cf-status").textContent = message;
      get("cf-start").disabled = busy;
      get("cf-restore").disabled = busy;
      get("cf-import").disabled = busy || !session || session.state !== "ready";
      if (session) get("cf-range").textContent = `${session.sequence_name}: ${(session["in_ms"] / 1000).toFixed(2)}–${(session["out_ms"] / 1000).toFixed(2)} seconds`;
    },
    bind(feature, openEditor) {
      get("cf-start").addEventListener("click", () => {
        const value = get("cf-track").value.trim();
        const track = value === "" ? null : Number(value) - 1;
        if (track !== null && (!Number.isInteger(track) || track < 0 || track > 127)) {
          get("cf-status").textContent = "Enter an audio track number from 1 to 128, or leave blank for automatic."; return;
        }
        feature.start(track);
      });
      get("cf-restore").addEventListener("click", feature.restore);
      get("cf-import").addEventListener("click", feature.import);
      get("cf-editor").addEventListener("click", () => openEditor().catch(error => { get("cf-status").textContent = error.message; }));
    },
  };
}
module.exports = { createClubFridayPanel };
