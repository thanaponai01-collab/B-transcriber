const test = require("node:test");
const assert = require("node:assert/strict");
const { createClubFriday } = require("../uxp/cutdeck/features/clubFriday.js");

const reply = (body, headers = {}) => ({
  ok: true, json: async () => body, text: async () => "srt",
  headers: { get: name => headers[name] ?? null },
});

function setup(sessionStates) {
  const calls = [], renders = [], imported = [];
  const states = [...sessionStates];
  const fetch = async (url, options = {}) => {
    const path = url.replace("http://127.0.0.1:8010", "");
    calls.push([options.method || "GET", path, options.body]);
    if (path === "/api/sessions" && options.method === "POST") return reply({ id: "a".repeat(32), state: "extracting", cues: [], context: { project_id: "p" } });
    if (path === "/api/sessions") return reply([]);
    if (path.endsWith("/transcript.srt")) return reply({}, { "X-ClubFriday-Export-Path": encodeURIComponent("C:\proj\ep 1.srt") });
    return reply({ id: "a".repeat(32), state: states.shift(), cues: [1, 2], context: { project_id: "p" } });
  };
  const cf = createClubFriday({
    fetch, ensureHelper: async () => {}, launch: async () => { throw new Error("must not launch"); },
    importSrt: async (path, context) => imported.push([path, context]),
    render: state => renders.push(state), sleep: async () => {},
  });
  return { cf, calls, renders, imported };
}

test("start posts the chosen track, polls until ready, then import uses the saved SRT path", async () => {
  const { cf, calls, renders, imported } = setup(["transcribing", "ready"]);
  await cf.start(2);
  const post = calls.find(c => c[0] === "POST");
  assert.deepEqual(JSON.parse(post[2]), { audio_track: 2 });
  assert.equal(calls.filter(c => c[1] === "/api/sessions/" + "a".repeat(32)).length, 2);
  assert.match(renders.map(r => r.message).filter(Boolean).at(-1), /Ready: 2 captions/);
  await cf.import();
  assert.deepEqual(imported, [["C:\proj\ep 1.srt", { project_id: "p" }]]);
});

test("import before a range is ready is refused and imports nothing", async () => {
  const { cf, renders, imported } = setup([]);
  await cf.import();
  assert.equal(imported.length, 0);
  assert.ok(renders.some(r => r.message === "Transcribe a range first."));
});

test("a failed session surfaces its error", async () => {
  const { cf, renders } = setup(["failed"]);
  await cf.start(null);
  assert.ok(renders.some(r => r.message === "Transcription failed"));
});
