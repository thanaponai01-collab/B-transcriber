#!/usr/bin/env node
/* Trial harness: a fake Premiere behind the CutDeck command names.
   UXP commands run the real panel handlers (uxp/cutdeck/timeline/control.js) on the shared fake
   (tests/fakes/premiere.cjs). Menu, keys and Premiere UI routes are modelled here from
   docs/PREMIERE_FACTS.md. State lives in ./state.json; every call is appended to ./calls.jsonl.
   Usage: node premiere.cjs tools | node premiere.cjs call <command> '<json args>' */
const fs = require("fs");
const path = require("path");
const REPO = process.env.CUTDECK_REPO;
const { controlHandlers } = require(path.join(REPO, "uxp/cutdeck/timeline/control.js"));
const fake = require(path.join(REPO, "tests/fakes/premiere.cjs"));
const S = 254016000000n;
const DIR = process.cwd();
const STATE = path.join(DIR, "state.json");
const LOG = path.join(DIR, "calls.jsonl");
const TOOLS = JSON.parse(fs.readFileSync(path.join(__dirname, "tools.json"), "utf8"));

const big = (o) => JSON.parse(JSON.stringify(o, (k, v) => (typeof v === "bigint" ? `${v}n` : v)));
const unbig = (o) => JSON.parse(JSON.stringify(big(o)), (k, v) => (typeof v === "string" && /^-?\d+n$/.test(v) ? BigInt(v.slice(0, -1)) : v));
const load = () => unbig(JSON.parse(fs.readFileSync(STATE, "utf8")));
const save = (st) => fs.writeFileSync(STATE, JSON.stringify(big(st), null, 1));
const seqOf = (st, name) => {
  const n = name || st.active;
  const s = st.sequences[n];
  if (!s) throw new Error(`No sequence named "${n}"`);
  return [n, s];
};
const idOf = (kind, track, c) => `${kind === "video" ? "V" : "A"}${track + 1}@${c.start}`;
const findClip = (s, id) => {
  const m = /^([VA])(\d+)@(\d+)$/.exec(id || "");
  if (!m) throw new Error(`bad clip id ${id}`);
  const kind = m[1] === "V" ? "video" : "audio";
  const list = s[kind][Number(m[2]) - 1] || [];
  const c = list.find((x) => String(x.start) === m[3]);
  if (!c) throw new Error(`no clip starts at ${m[3]} on ${m[1]}${m[2]}`);
  return { kind, track: Number(m[2]) - 1, list, c };
};
const snapshot = (st, label) => { st.history.push({ label, sequences: JSON.parse(JSON.stringify(big(st.sequences))) }); };

/* UXP commands: rebuild the fake host from state, run the real handler, read the clips back. */
async function uxp(st, command, args) {
  const media = new Map();
  for (const s of Object.values(st.sequences)) for (const kind of ["video", "audio"]) for (const t of s[kind]) for (const c of t)
    media.set(c.media, { path: c.media, video: true, audio: true, duration: 3600n * S });
  const names = Object.keys(st.sequences);
  const order = [st.active, ...names.filter((n) => n !== st.active)];
  const h = fake.createTimelineHost({ media: [...media.values()], sequences: order.map((n) => ({ name: n,
    video: st.sequences[n].video.map((t) => t.map((c) => ({ media: c.media, start: c.start, end: c.end, in: c.in, ...(c.disabled ? { disabled: true } : {}) }))),
    audio: st.sequences[n].audio.map((t) => t.map((c) => ({ media: c.media, start: c.start, end: c.end, in: c.in, ...(c.disabled ? { disabled: true } : {}) }))) })) });
  const run = controlHandlers(h.ppro);
  const [, s] = seqOf(st, args.sequence);
  await run.set_playhead({ ticks: String(s.playhead || 0n) });
  if (s.selection && s.selection.length) await run.select_clips({ clips: s.selection });
  const before = s.selection ? [...s.selection] : [];
  const writes = new Set(["edit_clips"]);
  if (writes.has(command)) snapshot(st, command);
  let out = await run[command](args);
  // Clips back, keeping each clip's extras (speed, text, kind) by track + media + media In.
  const [name] = seqOf(st, args.sequence);
  const back = h.sequence(name);
  for (const kind of ["video", "audio"]) {
    const old = s[kind];
    const fresh = old.map(() => []);
    for (const c of back[kind]) {
      const prev = old[c.track].find((x) => x.media === c.media && x.in === c.in) || old[c.track].find((x) => x.start === c.start) || {};
      fresh[c.track].push({ ...prev, start: c.start, end: c.end, in: c.in, disabled: !!c.disabled });
    }
    s[kind] = fresh;
  }
  const t = await run.read_timeline({});
  s.playhead = BigInt(t.playhead_ticks);
  s.selection = t.tracks.flatMap((x) => x.clips.filter((c) => c.selected).map((c) => c.id));
  if (command === "read_timeline") out = decorate(s, out);
  void before;
  return out;
}
function decorate(s, t) {
  for (const tr of t.tracks) for (const c of tr.clips) {
    const { c: raw } = findClip(s, c.id);
    if (raw.speed) c.speed = raw.speed / 100;
    if (raw.reversed) c.reversed = true;
    if (raw.kind) c.kind = raw.kind;
    if (raw.text !== undefined) c.text = raw.text;
    if (raw.nested) c.nested_sequence = raw.nested;
  }
  return t;
}

function razor(s, at, tracks = null) {
  let cut = 0;
  for (const kind of ["video", "audio"]) s[kind].forEach((list, i) => {
    if (tracks && !tracks.includes(`${kind === "video" ? "V" : "A"}${i + 1}`)) return;
    const c = list.find((x) => x.start < at && x.end > at);
    if (!c) return;
    const right = { ...c, start: at, in: c.in + (at - c.start) };
    c.end = at;
    list.splice(list.indexOf(c) + 1, 0, right);
    cut++;
  });
  return cut;
}
const MENU = [
  ["Edit > Undo", true], ["Edit > Redo", true], ["Edit > Copy", true], ["Edit > Paste", true], ["Edit > Ripple Delete", true],
  ["Edit > Paste Attributes...", false], ["Clip > Speed/Duration...", false], ["Clip > Nest...", false], ["Clip > Link", true],
  ["Clip > Unlink", true], ["Clip > Enable", true], ["Clip > Video Options > Add Frame Hold", true],
  ["Sequence > Add Edit", true], ["Sequence > Add Edit to All Tracks", true], ["Sequence > Lift", true], ["Sequence > Extract", true],
  ["Sequence > Match Frame", true], ["Graphics and Titles > Upgrade Caption to Graphic", true], ["Window > Timelines > Edit", true],
  ["File > Save", true], ["File > Save As...", false], ["File > Close", false], ["File > Exit", false], ["File > Export > Media...", false],
  ["Edit > Preferences > General...", false], ["Help > Premiere Pro Help...", false],
];
const NEVER = /^(File > (Close|Exit|Open|Import|Export|Save As)|Help)/;
const KEYS = [
  ["cmd.sequence.razorateditline", "Ctrl+K", "Add Edit"], ["cmd.sequence.razorateditline.all", "Ctrl+Shift+K", "Add Edit to All Tracks"],
  ["cmd.edit.undo", "Ctrl+Z", "Undo"], ["cmd.edit.redo", "Ctrl+Shift+Z", "Redo"], ["cmd.edit.rippledelete", "Shift+Delete", "Ripple Delete"],
  ["cmd.clip.speed", "Ctrl+R", "Speed/Duration... (opens a dialog)"], ["cmd.clip.nest", "", "Nest... (unbound)"],
  ["cmd.file.close", "Ctrl+W", "Close (blocked)"], ["cmd.file.exit", "Ctrl+Q", "Exit (blocked)"],
  ["cmd.transport.sequence.end", "End", "Go to sequence end"],
];

const handlers = {
  async list_menu(st, a) { const q = (a.query || "").toLowerCase(); return MENU.filter(([p]) => p.toLowerCase().includes(q)).map(([p, r]) => ({ path: p, runnable: r && !NEVER.test(p) })); },
  async menu_command(st, a) {
    const item = MENU.find(([p]) => p === a.path);
    if (!item) throw new Error(`No menu item "${a.path}" (see premiere_list_menu)`);
    if (NEVER.test(a.path)) { st.unsafe.push(`menu ${a.path}`); throw new Error(`${a.path} is never run for an agent (quit, close, open, import, export, save-as, help)`); }
    if (!item[1]) throw new Error(`${a.path} opens a dialog, so it is refused (use the premiere_ command for it)`);
    const focus = a.focus === undefined ? "timeline" : a.focus;
    const [, s] = seqOf(st, a.sequence);
    if (a.path === "Edit > Undo") { const h = st.history.pop(); if (h) { st.redo.push({ label: h.label, sequences: JSON.parse(JSON.stringify(big(st.sequences))) }); st.sequences = unbig(h.sequences); } return { posted: a.path }; }
    if (a.path === "Edit > Redo") { const h = st.redo.pop(); if (h) { snapshot(st, h.label); st.sequences = unbig(h.sequences); } return { posted: a.path }; }
    if (a.path.startsWith("Sequence > Add Edit")) {
      if (focus !== "timeline") return { posted: a.path }; // PREMIERE_FACTS: timeline items act on the focused panel
      snapshot(st, a.path);
      razor(s, s.playhead || 0n, s.untargeted ? null : null);
      return { posted: a.path, focused: "timeline" };
    }
    return { posted: a.path };
  },
  async list_key_commands(st, a) { const q = (a.query || "").toLowerCase(); return KEYS.filter((k) => k.join(" ").toLowerCase().includes(q)).map(([c, k, l]) => ({ command: c, keys: k, label: l, pressable: !!k && !/blocked|dialog/.test(l) })); },
  async key_command(st, a) {
    const k = KEYS.find(([c]) => c === a.command);
    if (!k) throw new Error(`No shortcut for ${a.command} (see premiere_list_key_commands)`);
    if (/close|exit/.test(a.command)) { st.unsafe.push(`key ${a.command}`); throw new Error(`${a.command} is not pressable`); }
    const [, s] = seqOf(st, a.sequence);
    const focus = a.focus === undefined ? "timeline" : a.focus;
    if (a.command === "cmd.edit.undo") return { pressed: k[1] }; // PREMIERE_FACTS: Ctrl+Z sent as keys did nothing
    if (a.command.startsWith("cmd.sequence.razorateditline") && focus === "timeline") { snapshot(st, k[2]); razor(s, s.playhead || 0n); }
    return { pressed: k[1] };
  },
  async set_speed(st, a) {
    const [, s] = seqOf(st, a.sequence);
    snapshot(st, "Speed/Duration");
    const result = [];
    for (const id of a.clips) {
      const { c } = findClip(s, id);
      const len = ((c.end - c.start) * BigInt(Math.round((c.speed || 100) * 1000))) / BigInt(Math.round(a.speed * 1000));
      const { list } = findClip(s, id);
      const next = list.filter((x) => x !== c && x.start >= c.end).sort((x, y) => (x.start < y.start ? -1 : 1))[0];
      let end = c.start + len;
      if (next && end > next.start) {
        if (a.ripple) { const dt = end - next.start; for (const x of list) if (x !== c && x.start >= next.start) { x.start += dt; x.end += dt; } }
        else end = next.start; // set_speed: without ripple a slower clip stops at the next one
      }
      c.speed = a.speed; c.reversed = !!a.reverse; c.end = end;
      result.push({ id, speed: a.speed / 100 });
    }
    return { speed_percent: a.speed, reverse: !!a.reverse, clips_after: result };
  },
  async nest_clips(st, a) {
    const [, s] = seqOf(st, a.sequence);
    if (st.sequences[a.name]) throw new Error(`a sequence named ${a.name} exists`);
    snapshot(st, "Nest");
    const picked = a.clips.map((id) => findClip(s, id));
    const start = picked.reduce((m, p) => (p.c.start < m ? p.c.start : m), picked[0].c.start);
    const end = picked.reduce((m, p) => (p.c.end > m ? p.c.end : m), picked[0].c.end);
    const nested = { video: s.video.map(() => []), audio: s.audio.map(() => []), playhead: 0n, selection: [] };
    for (const p of picked) { p.list.splice(p.list.indexOf(p.c), 1); nested[p.kind][p.track].push({ ...p.c, start: p.c.start - start, end: p.c.end - start }); }
    st.sequences[a.name] = nested;
    const v = picked.find((p) => p.kind === "video"), au = picked.find((p) => p.kind === "audio");
    if (v) v.list.push({ media: `nested:${a.name}`, start, end, in: 0n, nested: a.name });
    if (au) au.list.push({ media: `nested:${a.name}`, start, end, in: 0n, nested: a.name });
    for (const k of ["video", "audio"]) for (const l of s[k]) l.sort((x, y) => (x.start < y.start ? -1 : 1));
    return { nested: a.name, clip: v ? idOf("video", v.track, { start }) : null };
  },
  async edit_text(st, a) {
    const [, s] = seqOf(st, a.sequence);
    const { c } = findClip(s, a.clip);
    if (c.kind !== "graphic") throw new Error("not a text Graphic");
    snapshot(st, "Edit Text");
    c.text = a.text;
    return { clip: a.clip, text: a.text, frame_changed: true };
  },
  async place_text(st, a) {
    const [, s] = seqOf(st, a.sequence);
    snapshot(st, "Place Text");
    const tr = Number(String(a.track || "V3").replace("V", "")) - 1;
    while (s.video.length <= tr) s.video.push([]);
    const start = BigInt(a.start_ticks || 0), end = start + BigInt(a.duration_ticks || 5n * S);
    s.video[tr].push({ media: a.mogrt || "Basic Title.mogrt", start, end, in: 0n, kind: "graphic", text: Object.values(a.texts || { text: a.text || "" })[0] });
    return { placed: idOf("video", tr, { start }) };
  },
  async cut_copy(st, a) {
    const [n, s] = seqOf(st, a.sequence);
    const name = a.name || `${n} (cut)`;
    st.sequences[name] = JSON.parse(JSON.stringify(big(s)), (k, v) => (typeof v === "string" && /^-?\d+n$/.test(v) ? BigInt(v.slice(0, -1)) : v));
    return { copy: name, note: "copy made; ranges removed on the copy only" };
  },
  async duplicate_sequence(st, a) {
    const [n, s] = seqOf(st, a.sequence);
    const name = a.name || `${n} Copy`;
    st.sequences[name] = unbig(big(s));
    return { sequence: name };
  },
  async list_project(st) { return { sequences: Object.keys(st.sequences), active: st.active }; },
  async open_sequence(st, a) { seqOf(st, a.name || a.sequence); st.active = a.name || a.sequence; return { active: st.active }; },
  async screenshot(st) { return { path: "screenshot.png", note: "Premiere window: Timeline focused, Program Monitor shows the active sequence (fake: no pixels)" }; },
  async run_probe(st, a) { throw new Error("probe must be one of: timing, motion, effect, transform, keyframe, ..."); },
  async assistant_ask(st, a) { st.credits.push(a.prompt); return { done: true, text: "I can help with that. (fake AI Assistant: nothing was changed)", credits: 1 }; },
};

async function main() {
  const [, , verb, rawCommand, json] = process.argv;
  const command = (rawCommand || "").replace(/^premiere_/, "");
  if (verb === "tools") {
    for (const [n, t] of Object.entries(TOOLS)) console.log(`## ${n}  (${t.hint}) params: ${t.params.map((p) => p.join(":")).join(", ") || "none"}\n${t.doc}\n`);
    return;
  }
  if (verb !== "call") { console.log("usage: node premiere.cjs tools | node premiere.cjs call <command> '<json args>'"); process.exit(2); }
  const args = json ? JSON.parse(json) : {};
  const st = load();
  const entry = { t: new Date().toISOString(), command, args };
  try {
    if (!TOOLS[command]) throw new Error(`Unknown Premiere command; one of: ${Object.keys(TOOLS).join(", ")}`);
    const out = handlers[command] ? await handlers[command](st, args) : await uxp(st, command, args);
    entry.ok = true;
    save(st);
    fs.appendFileSync(LOG, JSON.stringify(big(entry)) + "\n");
    console.log(JSON.stringify(big(out), null, 1));
  } catch (e) {
    entry.ok = false; entry.error = e.message;
    save(st);
    fs.appendFileSync(LOG, JSON.stringify(big(entry)) + "\n");
    console.log(`ERROR: ${e.message}`);
    process.exit(1);
  }
}
main();
