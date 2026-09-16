/* TEMPORARY DIAGNOSTIC — delete once the permitted socket URL form is known.

   Premiere 26.5 (uxp-9.3.0-local) denies `ws://127.0.0.1:7891` with "Manifest entry
   not found." even though the manifest declares exactly that string, and even when the
   plugin is loaded through UXP Developer Tool. So the denial is not the cold-start
   timing bug — UXP is not matching the entry at all.

   This probe runs each candidate URL once and records which are permitted, so the
   manifest can be corrected from evidence instead of guesswork. Results are written to
   the plugin's own data folder, which needs no file picker. */
const CANDIDATES = [
  "ws://127.0.0.1:7891",
  "ws://localhost:7891",
  "ws://127.0.0.1",
  "ws://localhost",
  "wss://127.0.0.1:7891",
  "wss://localhost:7891",
];

/* A denial throws out of the constructor; anything else is a real connection outcome. */
function probeOne(url) {
  return new Promise((resolve) => {
    const started = Date.now();
    const done = (outcome, detail) => {
      if (socket) { try { socket.onopen = socket.onerror = socket.onclose = null; socket.close(); } catch (_) {} }
      clearTimeout(timer);
      resolve({ url, outcome, detail, ms: Date.now() - started });
    };
    let socket = null;
    const timer = setTimeout(() => done("timeout", "no event within 3s"), 3000);
    try {
      socket = new WebSocket(url);
    } catch (error) {
      done("threw", String((error && error.message) || error));
      return;
    }
    socket.onopen = () => done("OPEN", "permitted and connected");
    socket.onerror = (event) => done("error-event", String((event && event.message) || "onerror"));
    socket.onclose = (event) => done("close-event", `code=${event && event.code}`);
  });
}

async function run() {
  const results = [];
  for (const url of CANDIDATES) results.push(await probeOne(url));
  const report = { when: new Date().toISOString(), results };
  let written = null;
  try {
    const storage = require("uxp").storage.localFileSystem;
    const folder = await storage.getDataFolder();
    const file = await folder.createFile("probe.json", { overwrite: true });
    await file.write(JSON.stringify(report, null, 2));
    written = file.nativePath || "(data folder)";
  } catch (error) {
    written = "write failed: " + String((error && error.message) || error);
  }
  console.log("CutDeck probe", JSON.stringify(report, null, 2), "written to", written);
  return { report, written };
}

module.exports = { run, CANDIDATES };
