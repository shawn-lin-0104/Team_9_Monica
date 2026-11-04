// Monica's assistant: demo screen. Talks only to the endpoints in docs/API.md.
const $ = (s, root = document) => root.querySelector(s);
const CAL_NAMES = { thriveworks: "Thriveworks", book: "Book", podcast: "Podcast" };
const CAT_NAMES = { reply_needed: "Reply needed", scheduling: "Scheduling", fyi: "For your information" };
const calColor = (c) => getComputedStyle(document.documentElement).getPropertyValue(`--cal-${c}`).trim() || "#888";

let today = null, current = null, aiOn = false;
const chatHistory = [];

async function api(path, opts = {}) {
  const r = await fetch(path, {
    method: opts.method || (opts.body ? "POST" : "GET"),
    headers: opts.body !== undefined ? { "Content-Type": "application/json" } : {},
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.message || data.detail || `Something went wrong (${r.status}).`);
  return data;
}
const post = (path, body = {}) => api(path, { method: "POST", body });

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const tz = { timeZone: "America/New_York" };
const timeOf = (iso) => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", ...tz });
const dateLabel = (d) => new Date(d + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
const whenLabel = (iso) => new Date(iso).toLocaleString("en-US", { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", ...tz });
const shortDate = (iso) => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", ...tz });
const addDays = (d, n) => { const x = new Date(d + "T12:00:00"); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10); };
const tags = (cals) => cals.map((c) => `<span class="tag" style="background:${calColor(c)}">${esc(CAL_NAMES[c] || c)}</span>`).join("");
const mins = (m) => (m >= 60 ? `${Math.floor(m / 60)} hr${m % 60 ? ` ${m % 60} min` : ""}` : `${m} min`);
const urgentTag = (t) => (t && t.urgent ? '<span class="urgent">Urgent</span>' : "");

async function busy(btn, label, fn) {
  const old = btn.textContent; btn.disabled = true; btn.textContent = label;
  try { return await fn(); } finally { btn.disabled = false; btn.textContent = old; }
}
function showError(container, err) {
  const d = document.createElement("div"); d.className = "card err"; d.textContent = err.message;
  container.prepend(d); setTimeout(() => d.remove(), 8000);
}

// ------------------------------------------------------------------ tabs
function show(tab) {
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== `tab-${tab}`));
  document.querySelectorAll(".tabs button").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.tab === tab || (tab === "email" && b.dataset.tab === "inbox"))));
  window.scrollTo(0, 0);
  if (tab === "today") { loadBriefing(); loadPending(); }
  if (tab === "followups") loadFollowups();
  if (tab === "inbox") loadInbox();
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));

// ------------------------------------------------------------------ approval cards (shared)
function renderAction(a, container, onDone) {
  const card = document.createElement("div");
  card.className = "card approval";
  const p = a.payload;
  if (a.type === "send_email") {
    card.innerHTML = `<div class="label">Waiting for your OK · email</div>
      <h4>To ${esc(p.to)}</h4>
      <input class="subj" value="${esc(p.subject)}" aria-label="Subject" style="width:100%;margin-bottom:8px;padding:8px;border-radius:8px;border:1px solid var(--line);font:inherit;background:var(--bg);color:var(--ink)">
      <textarea aria-label="Email text">${esc(p.body)}</textarea>
      <div class="btnrow"><button class="primary go">Approve &amp; send</button><button class="secondary no">Discard</button></div>`;
  } else {
    const opts = p.options.length
      ? p.options.map((o, i) => `<label class="opt"><input type="radio" name="opt-${a.id}" value="${i}" ${i === 0 ? "checked" : ""}>
          <span><strong>${whenLabel(o.start)}</strong> – ${timeOf(o.end)}<br><span class="muted">${esc(o.why)}</span></span></label>`).join("")
      : `<p class="muted">No free time found in that window. Try asking Sage for another day.</p>`;
    card.innerHTML = `<div class="label">Waiting for your OK · calendar</div>
      <h4>${esc(p.title)}</h4>
      <div class="muted">${mins(p.minutes || 30)} · ${tags([p.calendar])}${p.attendees && p.attendees.length ? " · with " + esc(p.attendees.join(", ")) : ""}</div>
      ${opts}
      <div class="btnrow">${p.options.length ? '<button class="primary go">Approve booking</button>' : ""}<button class="secondary no">Discard</button></div>`;
  }
  const go = $(".go", card), no = $(".no", card);
  if (go) go.addEventListener("click", () => busy(go, "Working…", async () => {
    try {
      let body = {};
      if (a.type === "send_email") {
        await api(`/api/actions/${a.id}`, { method: "PATCH", body: { subject: $(".subj", card).value, body: $("textarea", card).value } });
      } else {
        body = { choice: Number(($(`input[name="opt-${a.id}"]:checked`, card) || {}).value || 0) };
      }
      await post(`/api/actions/${a.id}/approve`, body);
      card.className = "card done";
      card.innerHTML = a.type === "send_email" ? "✓ Sent (simulated). Marked as replied." : "✓ Booked. It's on your calendar now.";
      onDone && onDone();
    } catch (e) { showError(card, e); }
  }));
  no.addEventListener("click", async () => {
    await post(`/api/actions/${a.id}/reject`);
    card.className = "card"; card.innerHTML = '<span class="muted">Discarded.</span>';
    onDone && onDone();
  });
  container.appendChild(card);
  return card;
}

async function loadPending() {
  const { actions } = await api("/api/actions");
  const box = $("#pending"); box.innerHTML = "";
  if (actions.length) {
    box.insertAdjacentHTML("beforeend", `<h2>Waiting for your OK (${actions.length})</h2>`);
    actions.forEach((a) => renderAction(a, box, () => { loadBriefing(); }));
  }
}

// ------------------------------------------------------------------ today
async function loadBriefing() {
  const b = await api("/api/briefing");
  const next = b.next_event ? `<br><span class="muted">Next: ${esc(b.next_event.title)} at ${timeOf(b.next_event.start)}.</span>` : "";
  $("#briefing").innerHTML = `Good morning, Monica. ${esc(b.text).replace(/(\d+ [a-z ]+?)(?=[,.(])/g, "<b>$1</b>")}${next}` +
    (!b.emails_sorted && aiOn ? `<br><span class="muted">Your inbox hasn't been sorted yet. Open Inbox to sort it.</span>` : "");
}

async function loadDay(day) {
  current = day;
  $("#dayTitle").textContent = day === today ? `Today · ${dateLabel(day)}` : dateLabel(day);
  const v = await api(`/api/calendar/day?date=${day}`);
  const clashIds = new Set(v.conflicts.flatMap((c) => [c.a.id, c.b.id]));
  $("#conflicts").innerHTML = v.conflicts.map((c) =>
    `<div class="card warn">⚠️ <strong>Overlap:</strong> ${esc(c.a.title)} (${timeOf(c.a.start)}) and ${esc(c.b.title)} (${timeOf(c.b.start)}) overlap.</div>`).join("");
  $("#allDay").innerHTML = v.all_day.map((e) => `<div class="card">📌 <strong>${esc(e.title)}</strong> ${tags(e.calendars)}</div>`).join("");
  const items = [
    ...v.events.map((e) => ({ at: e.start, html: eventHtml(e, day === today && v.next_event && v.next_event.id === e.id, clashIds.has(e.id)) })),
    ...v.free_slots.filter((f) => f.minutes >= 30).map((f) => ({ at: f.start, html: `<div class="free">Open · ${timeOf(f.start)}–${timeOf(f.end)} (${mins(f.minutes)})</div>` })),
  ].sort((a, b) => new Date(a.at) - new Date(b.at));
  $("#timeline").innerHTML = items.length
    ? items.map((i) => `<li><div class="time">${timeOf(i.at)}</div>${i.html}</li>`).join("")
    : `<li><div></div><div class="card muted">Nothing scheduled.</div></li>`;
  document.querySelectorAll(".event").forEach((el) => el.addEventListener("click", () => togglePrep(el)));
}

function eventHtml(e, isNext, isClash) {
  const who = e.attendees.length ? ` · with ${esc(e.attendees.join(", "))}` : "";
  const where = e.location ? ` · ${esc(e.location)}` : "";
  return `<div class="event${isNext ? " next" : ""}${isClash ? " clash" : ""}" data-id="${esc(e.id)}" tabindex="0" style="border-left-color:${calColor(e.calendars[0])}">
    ${isNext ? '<div class="nextpill">Up next</div>' : ""}
    <div class="title">${esc(e.title)}</div>
    <div class="meta">${timeOf(e.start)}–${timeOf(e.end)}${where}${who}</div>
    <div>${tags(e.calendars)}${e.calendars.length > 1 ? '<span class="meta">on more than one calendar</span>' : ""}</div>
    <div class="prep" hidden></div>
  </div>`;
}

async function togglePrep(el) {
  const box = $(".prep", el);
  if (!box.hidden) { box.hidden = true; return; }
  box.hidden = false;
  if (box.dataset.loaded) return;
  if (!aiOn) { box.innerHTML = '<span class="muted">Meeting prep needs the AI to be switched on.</span>'; return; }
  box.innerHTML = '<span class="muted">Sage is looking for related emails…</span>';
  try {
    const p = await api(`/api/meetings/${encodeURIComponent(el.dataset.id)}/prep`);
    box.dataset.loaded = "1";
    box.innerHTML = `<strong>Prep:</strong> ${esc(p.summary)}` +
      (p.open_questions.length ? `<br><strong>Open questions:</strong><ul>${p.open_questions.map((q) => `<li>${esc(q)}</li>`).join("")}</ul>` : "") +
      (p.related_emails.length ? `<span class="muted">Related: ${p.related_emails.map((r) => esc(r.subject)).join("; ")}</span>` : "");
  } catch (e) { box.innerHTML = `<span class="muted">${esc(e.message)}</span>`; }
}

$("#prevDay").addEventListener("click", () => loadDay(addDays(current, -1)));
$("#nextDay").addEventListener("click", () => loadDay(addDays(current, 1)));
$("#legend").innerHTML = Object.entries(CAL_NAMES).map(([k, n]) => `<span><span class="dot" style="background:${calColor(k)}"></span>${n}</span>`).join("");

// ------------------------------------------------------------------ inbox
async function loadInbox() {
  const { emails, sorted, total } = await api("/api/emails");
  const box = $("#sortBox");
  if (sorted < total && aiOn) {
    box.innerHTML = `<div class="card soon">${sorted ? `${total - sorted} emails aren't sorted yet.` : "Sage can sort your inbox into Reply needed, Scheduling, and For your information."}
      <div class="btnrow"><button class="primary" id="sortBtn">Sort my inbox</button></div></div>`;
    $("#sortBtn").addEventListener("click", (ev) => busy(ev.target, "Sorting… (about a minute)", async () => {
      try { await post("/api/triage/run"); loadInbox(); } catch (e) { showError(box, e); }
    }));
  } else box.innerHTML = "";

  const row = (e) => `<li tabindex="0" data-id="${e.id}">
      <div class="row"><span class="from">${esc(e.from_name)}${urgentTag(e.triage)}</span><span class="when">${shortDate(e.received_at)}</span></div>
      <div class="subject">${esc(e.subject)}</div>
      ${e.triage && e.triage.reason ? `<div class="reason">${esc(e.triage.reason)}</div>` : `<div class="preview">${esc(e.preview.replace(/\s+/g, " "))}</div>`}
    </li>`;
  let html;
  if (sorted) {
    const groups = { reply_needed: [], scheduling: [], fyi: [], unsorted: [] };
    emails.forEach((e) => groups[(e.triage && e.triage.category) || "unsorted"].push(e));
    Object.values(groups).forEach((g) => g.sort((a, b) => (b.triage?.urgent ? 1 : 0) - (a.triage?.urgent ? 1 : 0)));
    html = Object.entries(groups).filter(([, g]) => g.length).map(([k, g]) =>
      `<div class="group"><h3>${CAT_NAMES[k] || "Not sorted yet"} <span class="count">${g.length}</span></h3><ul class="inbox">${g.map(row).join("")}</ul></div>`).join("");
  } else html = `<ul class="inbox">${emails.map(row).join("")}</ul>`;
  $("#inbox").innerHTML = html;
  $("#inbox").querySelectorAll("li").forEach((li) => {
    li.addEventListener("click", () => openEmail(li.dataset.id));
    li.addEventListener("keydown", (ev) => ev.key === "Enter" && openEmail(li.dataset.id));
  });
}

let draftAction = null;
async function openEmail(id) {
  show("email");
  draftAction = null;
  $("#emailDetail").innerHTML = "Loading…"; $("#emailTools").innerHTML = "";
  const [e, p] = await Promise.all([api(`/api/emails/${id}`), api(`/api/emails/${id}/privacy`)]);
  const history = e.history.map((h) => `<div class="thread"><strong>Earlier · ${esc(h.from)} · ${shortDate(h.date)}</strong>\n${esc(h.body)}</div>`).join("");
  const privacy = p.hidden_count
    ? `🔒 <strong>${p.hidden_count} private detail${p.hidden_count === 1 ? "" : "s"}</strong> hidden before Sage reads this email.`
    : "🔒 No private details found. Sage sees this email as written.";
  $("#emailDetail").innerHTML = `
    <div class="row"><span class="from">${esc(e.from_name)}${urgentTag(e.triage)}</span><span class="when">${shortDate(e.received_at)}</span></div>
    <h2>${esc(e.subject)}</h2>
    ${e.triage ? `<div class="reason">${esc(CAT_NAMES[e.triage.category])} · ${esc(e.triage.reason)}</div>` : ""}
    <div class="body" style="margin-top:10px">${esc(e.body)}</div>
    ${history}
    <details class="privacy"><summary>${privacy}</summary><p>This is exactly what Sage receives:</p><pre>${esc(p.sent_to_ai.body)}</pre></details>
    <div class="btnrow">
      <button class="secondary" id="btnSummary">Summarize</button>
      <button class="secondary" id="btnDraft">Suggest a reply</button>
      <button class="secondary" id="btnSchedule">Find meeting times</button>
    </div>`;
  const tools = $("#emailTools");
  $("#btnSummary").addEventListener("click", (ev) => busy(ev.target, "Reading…", async () => {
    try {
      const s = await post(`/api/emails/${id}/summary`);
      $("#sumCard")?.remove();
      tools.insertAdjacentHTML("afterbegin", `<div class="card summary" id="sumCard"><dl>
        <dt>Main request</dt><dd>${esc(s.main_request)}</dd>
        <dt>Deadline</dt><dd>${esc(s.deadline || "None mentioned")}</dd>
        <dt>Already agreed</dt><dd>${s.already_agreed.length ? s.already_agreed.map(esc).join("; ") : "Nothing yet"}</dd>
        <dt>Suggested next step</dt><dd>${esc(s.suggested_next_step)}</dd></dl></div>`);
    } catch (err) { showError(tools, err); }
  }));
  $("#btnDraft").addEventListener("click", (ev) => busy(ev.target, "Writing…", () => makeDraft(id, {})));
  $("#btnSchedule").addEventListener("click", (ev) => busy(ev.target, "Checking your calendar…", async () => {
    try {
      const r = await post(`/api/emails/${id}/schedule`);
      if (!r.is_meeting_request) { showError(tools, new Error(r.message)); return; }
      renderAction(r.action, tools);
    } catch (err) { showError(tools, err); }
  }));
}

async function makeDraft(id, opts) {
  const tools = $("#emailTools");
  try {
    const a = await post(`/api/emails/${id}/draft`, { ...opts, previous_action_id: draftAction ? draftAction.id : null });
    $("#draftWrap")?.remove();
    draftAction = a;
    const wrap = document.createElement("div"); wrap.id = "draftWrap"; tools.appendChild(wrap);
    renderAction(a, wrap, () => { draftAction = null; $("#toneRow")?.remove(); });
    wrap.insertAdjacentHTML("beforeend", `<div class="chips" id="toneRow">
      <button class="chip" data-tone="shorter">Shorter</button>
      <button class="chip" data-tone="friendlier">More friendly</button>
      <button class="chip" data-tone="formal">More formal</button></div>`);
    wrap.querySelectorAll("[data-tone]").forEach((b) => b.addEventListener("click", () =>
      busy(b, "Rewriting…", () => makeDraft(id, { tone: b.dataset.tone }))));
  } catch (err) { showError(tools, err); }
}
$("#backToInbox").addEventListener("click", () => show("inbox"));

// ------------------------------------------------------------------ follow-ups
async function loadFollowups() {
  const f = await api("/api/followups");
  $("#needReply").innerHTML = f.need_to_reply.length
    ? f.need_to_reply.map((x) => `<li><div class="row"><strong>${esc(x.subject)}${x.urgent ? '<span class="urgent">Urgent</span>' : ""}</strong></div>
        <div class="muted">${esc(x.from)} · ${esc(x.why)}</div>
        <div class="btnrow"><button class="small" data-open="${x.email_id}">Open</button>
        <button class="small" data-snooze="${x.email_id}">Snooze 1 day</button><button class="small" data-done="${x.email_id}">Mark done</button></div></li>`).join("")
    : `<li class="muted">${f.emails_sorted ? "You're all caught up." : "Sort your inbox first (Inbox tab) to see what needs a reply."}</li>`;
  $("#waiting").innerHTML = f.waiting_for_response.map((w) => `<li><div class="row"><strong>${esc(w.subject)}</strong><span class="when">${w.days_waiting} days</span></div>
      <div class="muted">To ${esc(w.to)} · sent ${shortDate(w.sent_at)}</div>
      <div class="btnrow"><button class="small" data-done="${w.id}">Got a reply / done</button></div></li>`).join("") || "<li class='muted'>Nothing outstanding.</li>";
  document.querySelectorAll("[data-done]").forEach((b) => b.addEventListener("click", async () => { await post(`/api/followups/${b.dataset.done}/done`); loadFollowups(); }));
  document.querySelectorAll("[data-snooze]").forEach((b) => b.addEventListener("click", async () => { await post(`/api/followups/${b.dataset.snooze}/snooze`, { days: 1 }); loadFollowups(); }));
  document.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => openEmail(b.dataset.open)));
}

// ------------------------------------------------------------------ chat
function bubble(text, who) {
  const d = document.createElement("div"); d.className = `bubble ${who}`; d.textContent = text;
  $("#chatLog").appendChild(d); d.scrollIntoView({ behavior: "smooth", block: "end" }); return d;
}
async function sendChat(text) {
  if (!text.trim()) return;
  bubble(text, "me");
  const thinking = bubble("…", "bot");
  const btn = $("#chatForm button"); btn.disabled = true;
  try {
    const r = await post("/api/chat", { message: text, history: chatHistory.slice(-10) });
    thinking.textContent = r.reply;
    chatHistory.push({ role: "user", content: text }, { role: "assistant", content: r.reply });
    r.proposed_actions.forEach((a) => a && renderAction(a, $("#chatLog")));
  } catch (e) { thinking.textContent = e.message; }
  finally { btn.disabled = false; }
}
$("#chatForm").addEventListener("submit", (ev) => { ev.preventDefault(); const t = $("#chatInput").value; $("#chatInput").value = ""; sendChat(t); });
document.querySelectorAll("#chatChips .chip").forEach((c) => c.addEventListener("click", () => sendChat(c.textContent)));

// ------------------------------------------------------------------ start
(async function init() {
  try {
    const h = await api("/api/health");
    today = h.now.slice(0, 10); aiOn = h.ai_available;
    $("#aiBanner").hidden = aiOn;
    if (!aiOn) { $("#chatForm").hidden = true; $("#chatChips").hidden = true;
      bubble("Chat needs the AI to be switched on (API key on the server).", "bot"); }
    await Promise.all([loadDay(today), loadBriefing(), loadPending(), loadInbox()]);
  } catch (err) {
    $("#briefing").textContent = "Couldn't reach the assistant. Is the server running?";
    console.error(err);
  }
})();
