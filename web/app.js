// Demo screen for Monica. Talks only to the endpoints in docs/API.md.
const $ = (s) => document.querySelector(s);
const CAL_NAMES = { thriveworks: "Thriveworks", book: "Book", podcast: "Podcast" };
const calColor = (c) => getComputedStyle(document.documentElement).getPropertyValue(`--cal-${c}`).trim() || "#888";

let today = null;   // demo "today" from the server
let current = null; // day being viewed

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const timeOf = (iso) => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" });
const dateLabel = (d) => new Date(d + "T12:00:00").toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });
const shortDate = (iso) => new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" });
const addDays = (d, n) => { const x = new Date(d + "T12:00:00"); x.setDate(x.getDate() + n); return x.toISOString().slice(0, 10); };
const tags = (cals) => cals.map((c) => `<span class="tag" style="background:${calColor(c)}">${esc(CAL_NAMES[c] || c)}</span>`).join("");
const mins = (m) => (m >= 60 ? `${Math.floor(m / 60)} hr${m % 60 ? ` ${m % 60} min` : ""}` : `${m} min`);

// ------------------------------------------------------------------ tabs
function show(tab) {
  document.querySelectorAll(".tab").forEach((s) => (s.hidden = s.id !== `tab-${tab}`));
  document.querySelectorAll(".tabs button").forEach((b) =>
    b.setAttribute("aria-selected", String(b.dataset.tab === tab || (tab === "email" && b.dataset.tab === "inbox"))));
  window.scrollTo(0, 0);
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => show(b.dataset.tab)));

// ------------------------------------------------------------------ today
async function loadDay(day) {
  current = day;
  $("#dayTitle").textContent = day === today ? `Today · ${dateLabel(day)}` : dateLabel(day);
  const v = await api(`/api/calendar/day?date=${day}`);
  const clashIds = new Set(v.conflicts.flatMap((c) => [c.a.id, c.b.id]));

  if (day === today) {
    const n = v.events.length;
    $("#briefing").innerHTML = `Good morning, Monica. You have <b>${n} appointment${n === 1 ? "" : "s"}</b> today` +
      (v.conflicts.length ? ` and <b>${v.conflicts.length} scheduling conflict${v.conflicts.length === 1 ? "" : "s"}</b>.` : ", with no conflicts.") +
      (v.next_event ? `<br><span class="muted">Next: ${esc(v.next_event.title)} at ${timeOf(v.next_event.start)}.</span>` : "");
  }

  $("#conflicts").innerHTML = v.conflicts.map((c) =>
    `<div class="card warn">⚠️ <strong>Overlap:</strong> ${esc(c.a.title)} (${timeOf(c.a.start)}) and ${esc(c.b.title)} (${timeOf(c.b.start)}) overlap.</div>`).join("");
  $("#allDay").innerHTML = v.all_day.map((e) =>
    `<div class="card">📌 <strong>${esc(e.title)}</strong> ${tags(e.calendars)}</div>`).join("");

  // Merge events and free gaps into one ordered timeline.
  const items = [
    ...v.events.map((e) => ({ at: e.start, html: eventHtml(e, day === today && v.next_event && v.next_event.id === e.id, clashIds.has(e.id)) })),
    ...v.free_slots.filter((f) => f.minutes >= 30).map((f) => ({
      at: f.start, html: `<div class="free">Open · ${timeOf(f.start)}–${timeOf(f.end)} (${mins(f.minutes)})</div>` })),
  ].sort((a, b) => new Date(a.at) - new Date(b.at));

  $("#timeline").innerHTML = items.length
    ? items.map((i) => `<li><div class="time">${timeOf(i.at)}</div>${i.html}</li>`).join("")
    : `<li><div></div><div class="card muted">Nothing scheduled.</div></li>`;
}

function eventHtml(e, isNext, isClash) {
  const who = e.attendees.length ? ` · with ${esc(e.attendees.join(", "))}` : "";
  const where = e.location ? ` · ${esc(e.location)}` : "";
  return `<div class="event${isNext ? " next" : ""}${isClash ? " clash" : ""}" style="border-left-color:${calColor(e.calendars[0])}">
    ${isNext ? '<div class="nextpill">Up next</div>' : ""}
    <div class="title">${esc(e.title)}</div>
    <div class="meta">${timeOf(e.start)}–${timeOf(e.end)}${where}${who}</div>
    <div>${tags(e.calendars)}${e.calendars.length > 1 ? '<span class="meta">on more than one calendar</span>' : ""}</div>
  </div>`;
}

$("#prevDay").addEventListener("click", () => loadDay(addDays(current, -1)));
$("#nextDay").addEventListener("click", () => loadDay(addDays(current, 1)));
$("#legend").innerHTML = Object.entries(CAL_NAMES).map(([k, n]) => `<span><span class="dot" style="background:${calColor(k)}"></span>${n}</span>`).join("");

// ------------------------------------------------------------------ inbox
async function loadInbox() {
  const { emails } = await api("/api/emails");
  $("#inbox").innerHTML = emails.map((e) => `
    <li tabindex="0" data-id="${e.id}">
      <div class="row"><span class="from">${esc(e.from_name)}</span><span class="when">${shortDate(e.received_at)}</span></div>
      <div class="subject">${esc(e.subject)}</div>
      <div class="preview">${esc(e.preview.replace(/\s+/g, " "))}</div>
    </li>`).join("");
  $("#inbox").querySelectorAll("li").forEach((li) => {
    li.addEventListener("click", () => openEmail(li.dataset.id));
    li.addEventListener("keydown", (ev) => ev.key === "Enter" && openEmail(li.dataset.id));
  });
}

async function openEmail(id) {
  show("email");
  $("#emailDetail").innerHTML = "Loading…";
  const [e, p] = await Promise.all([api(`/api/emails/${id}`), api(`/api/emails/${id}/privacy`)]);
  const history = e.history.map((h) =>
    `<div class="thread"><strong>Earlier · ${esc(h.from)} · ${shortDate(h.date)}</strong>\n${esc(h.body)}</div>`).join("");
  const privacy = p.hidden_count
    ? `🔒 <strong>${p.hidden_count} private detail${p.hidden_count === 1 ? "" : "s"}</strong> will be hidden before the AI reads this email.`
    : "🔒 No private details found. The AI would see this email as written.";
  $("#emailDetail").innerHTML = `
    <div class="row"><span class="from">${esc(e.from_name)}</span><span class="when">${shortDate(e.received_at)}</span></div>
    <h2>${esc(e.subject)}</h2>
    <div class="body">${esc(e.body)}</div>
    ${history}
    <details class="privacy"><summary>${privacy}</summary>
      <p>This is exactly what the AI would receive:</p>
      <pre>${esc(p.sent_to_ai.body)}</pre>
    </details>
    <div class="actions">
      <button disabled title="Coming soon">Summarize (coming soon)</button>
      <button disabled title="Coming soon">Suggest a reply (coming soon)</button>
      <button disabled title="Coming soon">Find meeting times (coming soon)</button>
    </div>`;
}
$("#backToInbox").addEventListener("click", () => show("inbox"));

// ------------------------------------------------------------------ follow-ups
async function loadFollowups() {
  const { waiting_for_response } = await api("/api/followups");
  $("#waiting").innerHTML = waiting_for_response.map((w) => `
    <li><div class="row"><strong>${esc(w.subject)}</strong><span class="when">${w.days_waiting} days</span></div>
    <div class="muted">To ${esc(w.to)} · sent ${shortDate(w.sent_at)}</div></li>`).join("") || "<li>Nothing outstanding.</li>";
}

// ------------------------------------------------------------------ start
(async function init() {
  try {
    const h = await api("/api/health");
    today = h.now.slice(0, 10);
    await Promise.all([loadDay(today), loadInbox(), loadFollowups()]);
  } catch (err) {
    $("#briefing").textContent = "Couldn't reach the assistant. Is the server running?";
    console.error(err);
  }
})();
