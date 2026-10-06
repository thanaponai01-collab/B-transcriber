// The separate ClubFriday panel reuses the local editor and its persisted jobs.
const BASE = "http://127.0.0.1:8010";
function createClubFriday({ fetch, ensureHelper, launch, importSrt, render, sleep = ms => new Promise(r => setTimeout(r, ms)) }) {
  let session = null;
  let busy = false;
  async function request(path, options) {
    const response = await fetch(BASE + path, options);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || "ClubFriday request failed");
    }
    return response;
  }
  async function connect() {
    await ensureHelper();
    try { await request("/api/sessions"); }
    catch (_) {
      await launch();
      let connected = false;
      for (let i = 0; i < 30; i++) {
        await sleep(500);
        try { await request("/api/sessions"); connected = true; break; } catch (_) {}
      }
      if (!connected) throw new Error("ClubFriday did not start. Run Start ClubFriday.cmd to see the error.");
    }
  }
  function update(message) { render({ busy, session, message }); }
  async function act(work) {
    if (busy) return;
    busy = true; update("Connecting…");
    try { await connect(); await work(); }
    catch (error) { update(error.message); }
    finally { busy = false; render({ busy, session }); }
  }
  async function poll() {
    while (session && ["extracting", "transcribing"].includes(session.state)) {
      update(session["connection_error"] || (session.state === "extracting" ? "Preparing marked audio…" : "Transcribing Thai audio…"));
      await sleep(1500);
      session = await (await request("/api/sessions/" + session.id)).json();
    }
    if (session.state === "failed") throw new Error(session.error || "Transcription failed");
    update(`Ready: ${session.cues.length} captions. Import SRT next.`);
  }
  return {
    start: audioTrack => act(async () => {
      session = await (await request("/api/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ audio_track: audioTrack }) })).json();
      await poll();
    }),
    restore: () => act(async () => {
      const sessions = await (await request("/api/sessions")).json();
      if (!sessions.length) { update("Mark timeline In/Out, then Transcribe In/Out."); return; }
      session = await (await request("/api/sessions/" + sessions[0].id)).json();
      await poll();
    }),
    import: () => act(async () => {
      if (!session || session.state !== "ready") throw new Error("Transcribe a range first.");
      const response = await request("/api/sessions/" + session.id + "/transcript.srt");
      const path = response.headers.get("X-ClubFriday-Export-Path");
      if (!path) throw new Error("Export did not return a saved SRT path.");
      await response.text();
      await importSrt(decodeURIComponent(path), session.context);
      update("Imported into CutDeck / ClubFriday. Drag the SRT onto the timeline; choose Source timecode.");
    }),
  };
}
module.exports = { createClubFriday, BASE };
