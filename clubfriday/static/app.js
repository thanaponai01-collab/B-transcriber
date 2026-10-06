const $ = id => document.getElementById(id);
const {breakLines, timestamp} = ClubFridayQuotes;
let session = null, pollTimer = null, dirty = false;

function message(text, error = false) { $("message").textContent = text; $("message").classList.toggle("error", error); }
async function api(path, method = "GET", body) {
  const response = await fetch(path, {method, headers: {"Content-Type":"application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === "string" ? data.detail : "Check the quote format: use one to three non-empty lines.");
  return data;
}
async function refresh() {
  try {
    const status = await api("/api/premiere");
    if (!status.connected) throw Error(status.error || "Open the CutDeck panel in Premiere to connect.");
    const seq = status.sequence;
    $("sequence").textContent = seq.name;
    $("range").textContent = seq.in_seconds === null || seq.out_seconds === null ? "Set timeline In and Out marks in Premiere." : `${timestamp(Math.round(seq.in_seconds * 1000))} → ${timestamp(Math.round(seq.out_seconds * 1000))}`;
    $("track").replaceChildren(new Option("First active audio track", ""));
    for (let i = 0; i < seq.audio_track_count; i++) $("track").add(new Option(`A${i + 1}`, String(i)));
    message("Premiere connected. Mark an advice section, then transcribe it.");
  } catch (error) { message(error.message, true); }
}
async function sessions() {
  const list = await api("/api/sessions");
  $("sessions").replaceChildren(new Option("Choose a range…", ""));
  for (const s of list) $("sessions").add(new Option(`${s.sequence_name} · ${timestamp(s.in_ms)}–${timestamp(s.out_ms)}`, s.id));
  if (session) $("sessions").value = session.id;
  return list;
}
async function openSession(id) {
  clearTimeout(pollTimer);
  session = await api(`/api/sessions/${id}`); dirty = false;
  $("sessions").value = id;
  renderSession();
  if (["extracting","transcribing"].includes(session.state)) pollTimer = setTimeout(() => poll(id), 2000);
}
async function poll(id) {
  try {
    const result = await api(`/api/sessions/${id}`);
    if (!session || session.id !== id) return;
    session = result; renderSession();
    if (["extracting","transcribing"].includes(result.state)) pollTimer = setTimeout(() => poll(id), 2000);
  } catch (error) { message(error.message, true); pollTimer = setTimeout(() => poll(id), 4000); }
}
function element(tag, text, className) {
  const el = document.createElement(tag); if (text !== undefined) el.textContent = text;
  if (className) el.className = className; return el;
}
function renderSession() {
  $("export-transcript").disabled = session.state !== "ready" || !session.cues.length;
  $("export").disabled = session.state !== "ready" || !session.quotes.length;
  $("start").disabled = ["extracting","transcribing"].includes(session.state);
  $("summary").textContent = `${session.sequence_name} · ${timestamp(session.in_ms)} → ${timestamp(session.out_ms)}`;
  if (session.state === "failed") {
    message(session.error, true); $("cues").replaceChildren(); $("quotes").replaceChildren();
    $("add").disabled = true; $("save").disabled = true; $("count").textContent = "0";
    $("audio").removeAttribute("src"); return;
  }
  if (session.state !== "ready") {
    message(session.connection_error || (session.state === "extracting" ? "Preparing audio from your marked range…" : "Transcribing Thai audio with your existing helper…"), !!session.connection_error);
    $("add").disabled = true; $("save").disabled = true;
    $("cues").replaceChildren(element("p", "This range is being prepared. You can leave this window and reopen it later.", "empty"));
    $("quotes").replaceChildren(); $("count").textContent = "0"; $("audio").removeAttribute("src"); return;
  }
  message(session.cues.length ? `${session.cues.length} transcript sentences ready. Review the words and select your highlights.` : "No speech was detected in this range. Mark a section where the hosts are speaking.");
  $("audio").src = `/api/sessions/${session.id}/audio`;
  $("cues").replaceChildren();
  session.cues.forEach((cue, i) => {
    const row = element("div", undefined, "cue"), check = document.createElement("input");
    check.type = "checkbox"; check.value = i; check.setAttribute("aria-label", `Select quote at ${timestamp(cue.start_ms)}`);
    check.onchange = () => $("add").disabled = !document.querySelector(".cue input:checked");
    const content = element("div"), time = element("button", `${timestamp(cue.start_ms)} → ${timestamp(cue.end_ms)}`, "time");
    time.onclick = () => { $("audio").currentTime = Math.max(0, (cue.start_ms - session.offset_ms) / 1000); $("audio").play().catch(e => message(e.message, true)); };
    content.append(time, element("p", cue.text, "words")); row.append(check, content); $("cues").append(row);
  });
  if (!session.cues.length) $("cues").append(element("p", "No transcript sentences in this range.", "empty"));
  $("add").disabled = true; renderQuotes();
}
async function copy(text) {
  try { await navigator.clipboard.writeText(text); message("Copied. Paste into your styled Premiere graphic."); }
  catch (_) { message("Clipboard is unavailable. Select the quote text and copy it manually.", true); }
}
function renderQuotes() {
  $("export").disabled = !session.quotes.length;
  $("quotes").replaceChildren(); $("count").textContent = session.quotes.length;
  $("save").disabled = !session.quotes.length;
  if (!session.quotes.length) $("quotes").append(element("p", "Select the advice you want to highlight, then add it here.", "empty"));
  session.quotes.forEach((quote, index) => {
    const card = element("article", undefined, "quote"), head = element("div", undefined, "quotehead");
    head.append(element("span", `QUOTE ${index + 1} · ${timestamp(quote.start_ms)} → ${timestamp(quote.end_ms)}`));
    const remove = element("button", "Remove", "remove"); remove.onclick = () => { session.quotes.splice(index, 1); dirty = true; renderQuotes(); $("save").disabled = false; }; head.append(remove);
    const text = element("textarea"); text.value = quote.lines.join("\n"); text.setAttribute("aria-label", `Quote ${index + 1} text`);
    const status = element("p", "", "linecount"), preview = element("div", "", "preview"), controls = element("div", undefined, "quotecontrols");
    const select = document.createElement("select"); for (let n = 1; n <= 3; n++) select.add(new Option(`${n} line${n > 1 ? "s" : ""}`, n)); select.value = quote.lines.length;
    select.setAttribute("aria-label", `Quote ${index + 1} line count`);
    const reflow = element("button", "Suggest breaks");
    const copyAll = element("button", "Copy quote"), copies = element("span");
    function update() {
      quote.lines = text.value.replace(/\r/g, "").split("\n");
      const valid = quote.lines.length <= 3 && quote.lines.some(l => l.trim());
      status.textContent = valid ? `${quote.lines.length} / 3 lines · Review against the audio before copying.` : "Use at most three lines. Split a longer passage into another quote.";
      status.classList.toggle("invalid", !valid); copyAll.disabled = !valid;
      preview.textContent = text.value; copies.replaceChildren();
      quote.lines.slice(0, 3).forEach((line, n) => { const b = element("button", `Copy line ${n + 1}`); b.onclick = () => copy(line); b.disabled = !valid; copies.append(b); });
    }
    text.oninput = () => { dirty = true; update(); };
    reflow.onclick = () => { text.value = breakLines(text.value, Number(select.value)).join("\n"); dirty = true; update(); };
    copyAll.onclick = () => copy(text.value);
    controls.append(select, reflow, copyAll, copies); card.append(head, text, status, preview, controls); $("quotes").append(card); update();
  });
}
$("refresh").onclick = refresh;
$("start").onclick = async () => {
  if (dirty && !confirm("You have unsaved quote edits. Start a new range without saving them?")) return;
  $("start").disabled = true;
  try { session = await api("/api/sessions", "POST", {audio_track: $("track").value === "" ? null : Number($("track").value)}); dirty = false; await sessions(); await openSession(session.id); }
  catch (error) { message(error.message, true); $("start").disabled = false; }
};
$("sessions").onchange = async () => {
  const id = $("sessions").value; if (!id) return;
  if (dirty && !confirm("You have unsaved quote edits. Open another range without saving them?")) { $("sessions").value = session.id; return; }
  try { await openSession(id); } catch (error) { message(error.message, true); }
};
$("add").onclick = () => {
  const indices = Array.from(document.querySelectorAll(".cue input:checked"), el => Number(el.value));
  if (!indices.length) return;
  if (indices.some((value, i) => i && value !== indices[i - 1] + 1)) { message("Choose consecutive sentences for one quote, or add them as separate quotes.", true); return; }
  const selected = indices.map(i => session.cues[i]), text = selected.map(c => c.text).join(" ");
  const count = text.length > 80 ? 3 : text.length > 40 ? 2 : 1;
  session.quotes.push({cue_indices:indices, lines:breakLines(text, count), start_ms:selected[0].start_ms, end_ms:selected.at(-1).end_ms});
  dirty = true; renderQuotes(); document.querySelectorAll(".cue input:checked").forEach(el => el.checked = false); $("add").disabled = true;
};
$("save").onclick = async () => {
  try { session = await api(`/api/sessions/${session.id}/quotes`, "PUT", {quotes:session.quotes.map(q => ({cue_indices:q.cue_indices, lines:q.lines}))}); dirty = false; renderQuotes(); message("Quotes saved. You can reopen this range later."); }
  catch (error) { message(error.message, true); }
};
$("export").onclick = async () => {
  $("export").disabled = true;
  try {
    session = await api(`/api/sessions/${session.id}/quotes`, "PUT", {quotes:session.quotes.map(q => ({cue_indices:q.cue_indices, lines:q.lines}))});
    dirty = false;
    const response = await fetch(`/api/sessions/${session.id}/quotes.srt`);
    if (!response.ok) { const error = await response.json(); throw Error(error.detail); }
    message(`Saved SRT: ${decodeURIComponent(response.headers.get("X-ClubFriday-Export-Path") || "")}. Import it at sequence start (00:00) in Premiere.`);
  } catch (error) { message(error.message, true); }
  finally { $("export").disabled = !session.quotes.length; }
};
window.addEventListener("beforeunload", event => { if (dirty) { event.preventDefault(); event.returnValue = ""; } });
$("export-transcript").onclick = async () => {
  $("export-transcript").disabled = true;
  try {
    const response = await fetch(`/api/sessions/${session.id}/transcript.srt`);
    if (!response.ok) { const error = await response.json(); throw Error(error.detail); }
    message(`Saved SRT: ${decodeURIComponent(response.headers.get("X-ClubFriday-Export-Path") || "")}. Import it at sequence start (00:00) in Premiere.`);
  } catch (error) { message(error.message, true); }
  finally { $("export-transcript").disabled = !session.cues.length; }
};
(async () => { await refresh(); try { const list = await sessions(); if (list.length) await openSession(list[0].id); } catch (error) { message(error.message, true); } })();
