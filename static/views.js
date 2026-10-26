/* Dispatch: Applications, Insights and Radar views */
const SC = {pending: "#628CDA", interview: "#BE8710", offer: "#27A07F", rejected: "#E0604F", no_response: "#8B93A7"};  // validated on the dark surface
const SL = {pending: "Pending", interview: "Interviewing", offer: "Offer", rejected: "Not selected", no_response: "No response"};
const SORDER = ["pending", "interview", "offer", "rejected", "no_response"];
const EV_LABEL = {received: "Application confirmed", assessment: "Assessment sent", withdrawn: "Position closed", followed_up: "You followed up",
  interview: "Interview / next step", offer: "Offer", rejected: "Not selected"};
const AMBER = "#F5B841", MUTED = "#93A0BA", GRID = "rgba(45,60,94,.55)", CARD = "#1C2843";
const V = {apps: [], ins: null, appFilter: "", sortKey: "applied_on", sortDir: -1, charts: {}, map: null, radar: null};

/* ---------------------------------------------------------------- navigation */
function go(view, push = true) {
  window.currentView = view;
  $$(".views [data-go]").forEach(b => b.setAttribute("aria-selected", b.dataset.go === view));
  $$(".view").forEach(v => v.hidden = v.id !== "view-" + view);
  $("#btnFind").hidden = view !== "jobs";
  $("#btnExport").title = $("#btnExport").ariaLabel = (view === "apps" || view === "insights") ? "Download applications as Excel" : "Export jobs to CSV";
  if (push) try { history.replaceState(null, "", "#" + view); } catch {}
  closeDrawer();
  if (view === "apps") loadApps();
  if (view === "insights") loadInsights();
  if (view === "radar") loadRadar();
}
document.addEventListener("click", e => { const b = e.target.closest("[data-go]"); if (b) go(b.dataset.go); });
window.onSyncDone = () => { if (window.currentView === "apps") loadApps(); if (window.currentView === "insights") loadInsights(); };

function flapStrip(el, items) {
  el.innerHTML = items.map(([label, val, cls]) => `<div class="fs-item"><span class="fs-label">${esc(label)}</span>${flapHTML(String(val), 8, cls || "")}</div>`).join("");
  animateFlaps(el);
}

/* ---------------------------------------------------------------- applications */
async function loadApps() {
  const d = await api("/api/applications");
  V.apps = d.apps;
  V.history = d.history;
  renderApps();
}

const fmtShort = iso => iso ? new Date(iso.slice(0, 10) + "T12:00:00").toLocaleDateString(undefined, {month: "short", day: "numeric"}) : "";
const lastEvent = a => (a.events || []).slice().sort((x, y) => (y.date || "").localeCompare(x.date || ""))[0];

function renderApps() {
  const apps = V.apps;
  const c = k => apps.filter(a => a.status === k).length;
  flapStrip($("#appsFlaps"), [["Applied", apps.length, "amber"], ["Pending", c("pending")], ["Interviewing", c("interview")],
    ["Offers", c("offer"), "go"], ["Not selected", c("rejected"), "dim"]]);
  $("#appsSub").textContent = "Tracked automatically from employer emails and jobs you apply to in Dispatch";
  const fu = apps.filter(a => a.follow_up).length;
  const chips = [["", "All"], ["followup", "Needs follow-up"], ...SORDER.map(k => [k, SL[k]])];
  $("#appStatusChips").innerHTML = chips.map(([k, l]) => `<button class="chip" aria-pressed="${V.appFilter === k}" data-af="${k}">${l}${k ? ` <span class="cn">${k === "followup" ? fu : c(k)}</span>` : ""}</button>`).join("");
  const hb = $("#historyBar"), h = V.history || {};
  hb.hidden = !(h.available && !h.imported) || apps.length > 0 && !h.available;
  if (!hb.hidden) {
    hb.innerHTML = `<span>Want your past applications from <b>${esc(h.available)}</b> in the charts? Import them once; Dispatch won't use the file after that.</span>
      <button class="btn btn-sm btn-amber" id="btnHistBar">Import old history</button><button class="btn btn-sm btn-ghost" id="btnHistDismiss">No thanks</button>`;
    $("#btnHistBar").onclick = importHistory;
    $("#btnHistDismiss").onclick = () => { try { localStorage.setItem("dispatch.noHistory", "1"); } catch {} hb.hidden = true; };
    try { if (localStorage.getItem("dispatch.noHistory")) hb.hidden = true; } catch {}
  }
  const fsel = $("#appFocus"), ssel = $("#appState"), fv = fsel.value, sv = ssel.value;
  const focuses = [...new Set(apps.map(a => a.focus))].sort(), states = [...new Set(apps.map(a => (a.state || "").toUpperCase()).filter(Boolean))].sort();
  fsel.innerHTML = `<option value="">All focus areas</option>` + focuses.map(f => `<option${f === fv ? " selected" : ""}>${esc(f)}</option>`).join("");
  ssel.innerHTML = `<option value="">All states</option>` + states.map(s => `<option${s === sv ? " selected" : ""}>${esc(s)}</option>`).join("");
  const q = ($("#aq").value || "").toLowerCase();
  let rows = apps.filter(a => (!V.appFilter || (V.appFilter === "followup" ? a.follow_up : a.status === V.appFilter)) && (!fv || a.focus === fv) && (!sv || (a.state || "").toUpperCase() === sv)
    && (!q || [a.title, a.company, a.city, a.state].join(" ").toLowerCase().includes(q)));
  const k = V.sortKey, dir = V.sortDir;
  const val = a => k === "last" ? (lastEvent(a)?.date || "") : k === "days_to_reply" ? (a[k] ?? 9999) : (a[k] ?? "");
  rows.sort((x, y) => { const p = val(x), r = val(y); return (typeof p === "number" ? p - r : String(p).localeCompare(String(r))) * dir; });
  $$("#appsTable th").forEach(th => th.setAttribute("aria-sort", th.dataset.k === k ? (dir > 0 ? "ascending" : "descending") : "none"));
  $("#appsTable tbody").innerHTML = rows.length ? rows.map(a => {
    const le = lastEvent(a);
    return `<tr data-app="${esc(a.id)}" tabindex="0">
      <td><span class="st st-${a.status}"><i></i>${esc(a.status_label)}</span>${a.follow_up ? '<span class="fu">Follow up</span>' : ""}${a.history ? '<span class="hist" title="Imported from your old spreadsheet">history</span>' : ""}</td>
      <td class="t-role">${esc(a.title)}</td><td>${esc(a.company)}</td>
      <td>${esc(a.place || "")}</td><td class="muted">${esc(a.focus)}</td>
      <td class="num">${fmtShort(a.posted_on)}</td><td class="num">${fmtShort(a.applied_on)}</td><td class="num">${fmtShort(a.closed_on)}</td>
      <td class="num">${a.days_to_reply != null ? a.days_to_reply + "d" : ""}</td>
      <td class="muted last">${le ? esc(fmtShort(le.date) + " · " + (EV_LABEL[le.kind] || le.kind)) : (a.confirmed ? "Confirmation received" : "")}</td></tr>`;
  }).join("") : `<tr><td colspan="10"><div class="empty"><h3>No applications here</h3><p>${apps.length ? "Try a different filter." : "Sync your email and Dispatch adds every application an employer confirms. Jobs you mark Applied land here too."}</p></div></td></tr>`;
  const withEmail = apps.filter(a => (a.events || []).length).length;
  $("#appsFoot").textContent = `${rows.length} of ${apps.length} shown · ${withEmail} matched to employer emails`;
}
document.addEventListener("click", e => {
  const chip = e.target.closest("[data-af]"); if (chip) { V.appFilter = chip.dataset.af; return renderApps(); }
  const th = e.target.closest("#appsTable th"); if (th) { V.sortDir = V.sortKey === th.dataset.k ? -V.sortDir : -1; V.sortKey = th.dataset.k; return renderApps(); }
  const tr = e.target.closest("tr[data-app]"); if (tr) return openApp(tr.dataset.app);
  const seg = e.target.closest("[data-astatus]"); if (seg) return setAppStatus(seg.dataset.astatus);
  if (e.target.closest("[data-fu]") && currentApp) return followedUp();
  if (e.target.closest("[data-fucopy]") && currentApp) {
    const a = currentApp;
    const txt = `Subject: Following up on my ${a.title} application\n\nHi,\n\nI applied for the ${a.title} role at ${a.company} on ${fmtDate(a.applied_on)} and wanted to check in. ` +
      `I'm still very interested, and my background in SQL, Python and BI reporting lines up well with the role. Is there any update on next steps, or anything else I can send?\n\nThank you,\nJordan Gillis`;
    navigator.clipboard?.writeText(txt); return toast("Follow-up email copied. Paste it into a reply to the recruiter.");
  }
});
document.addEventListener("keydown", e => { if (e.key === "Enter" && e.target.matches("tr[data-app]")) openApp(e.target.dataset.app); });
$("#aq").addEventListener("input", renderApps);
$("#appFocus").addEventListener("change", renderApps);
$("#appState").addEventListener("change", renderApps);
$("#btnAppsXlsx").onclick = () => location.href = "/api/applications/export.xlsx";


let currentApp = null;
function openApp(id) {
  currentApp = V.apps.find(a => a.id === id);
  if (!currentApp) return;
  renderAppDrawer(currentApp);
  state.selected = null;
  $("#drawer").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false"); $("#scrim").hidden = false; $("#drawer").focus();
}
function renderAppDrawer(a) {
  const evs = (a.events || []).slice().sort((x, y) => (y.date || "").localeCompare(x.date || ""));
  const timeline = [...evs.map(e => ({date: e.date, title: EV_LABEL[e.kind] || e.kind,
      kind: e.kind, body: e.subject, snip: e.snippet, from: e.sender})),
    ...(a.applied_on ? [{date: a.applied_on, title: "Applied", kind: "applied", body: a.history ? "Imported from your old spreadsheet" : a.source === "dispatch" ? "Marked applied in Dispatch" : "Found in your email"}] : []),
    ...(a.status === "no_response" && a.closed_on ? [{date: a.closed_on, title: "No response", kind: "no_response", body: "Closed automatically after no reply"}] : []),
    ...(a.posted_on ? [{date: a.posted_on, title: "Posting opened", kind: "posted", body: ""}] : [])]
    .sort((x, y) => (y.date || "").localeCompare(x.date || ""));
  const segs = [["", "Automatic"], ...SORDER.map(k => [k, SL[k]])].map(([k, l]) => `<button class="seg" aria-pressed="${(a.manual_status || "") === k}" data-astatus="${k}">${l}</button>`).join("");
  $("#drawer").innerHTML = `
  <div class="d-top">
    <div class="row"><span class="st st-${a.status}"><i></i>${esc(a.status_label)}</span><button class="btn btn-icon" data-act="close" aria-label="Close details">${ICON.x}</button></div>
    <h2 class="d-title">${esc(a.title)}</h2><div class="d-co">${esc(a.company)}</div>
    <div class="d-actions">${a.link && a.link.startsWith("http") ? `<a class="btn btn-amber" href="${esc(a.link)}" target="_blank" rel="noopener">Open posting ${ICON.ext}</a>` : ""}
      ${a.status === "pending" || a.status === "no_response" ? `<button class="btn" data-fu="1">${a.follow_up ? "I followed up" : "Log a follow-up"}</button><button class="btn" data-fucopy="1">Copy follow-up email</button>` : ""}</div>
    ${a.follow_up ? `<p class="fu-note">It's been ${a.age_days} days with no reply. A short follow-up to the recruiter or hiring manager often gets things moving.</p>` : ""}
  </div>
  <div class="d-body">
    <div class="facts">${fact("Opened", fmtDate(a.posted_on))}${fact("Applied", fmtDate(a.applied_on))}${fact("Closed", fmtDate(a.closed_on))}
      ${fact("Heard back after", a.days_to_reply != null ? a.days_to_reply + " days" : "")}${fact("Location", a.place)}
      ${fact("Focus area", a.focus)}${fact("Applied via", a.platform)}${fact("Confirmation email", a.confirmed ? "Received" : "")}</div>
    <section class="d-sec"><h3>Status <small>Automatic follows the latest employer email, and closes as No response after your cutoff</small></h3><div class="status-seg">${segs}</div></section>
    <section class="d-sec"><h3>Timeline</h3><ol class="timeline">${timeline.map(t => `<li class="tl-${t.kind}"><span class="tl-date">${esc(fmtShort(t.date))}</span>
      <div><b>${esc(t.title)}</b>${t.body ? `<p>${esc(t.body)}</p>` : ""}${t.snip ? `<p class="snip">“${esc(t.snip)}”</p>` : ""}${t.from ? `<p class="from">${esc(t.from)}</p>` : ""}</div></li>`).join("")}</ol>
      ${evs.length ? "" : `<p class="hint">No employer emails matched yet. They show up here after a sync.</p>`}</section>
    ${a.notes_excel ? `<section class="d-sec"><h3>Spreadsheet comment</h3><p>${esc(a.notes_excel)}</p></section>` : ""}
    <section class="d-sec"><h3>Notes</h3><textarea class="notes" id="appNotes" placeholder="Recruiter, follow-up date…">${esc(a.notes || "")}</textarea></section>
  </div>`;
  let t;
  $("#appNotes").oninput = e => { clearTimeout(t); const v = e.target.value; a.notes = v; t = setTimeout(() => api(`/api/applications/${encodeURIComponent(a.id)}`, {method: "PATCH", body: {notes: v}}), 500); };
}
async function followedUp() {
  const na = await api(`/api/applications/${encodeURIComponent(currentApp.id)}`, {method: "PATCH", body: {followed_up: true}});
  Object.assign(currentApp, na); renderAppDrawer(currentApp); renderApps();
  toast("Follow-up logged. Dispatch will remind you again if there's still no reply.");
}
async function setAppStatus(s) {
  if (!currentApp) return;
  const na = await api(`/api/applications/${encodeURIComponent(currentApp.id)}`, {method: "PATCH", body: {status: s}});
  Object.assign(currentApp, na);
  renderAppDrawer(currentApp); renderApps();
  toast(s ? `Status set to ${SL[s]}` : "Status back to automatic");
}

/* ---------------------------------------------------------------- insights */
function chartDefaults() {
  if (!window.Chart) return false;
  Chart.defaults.color = MUTED;
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.font.size = 13;
  Chart.defaults.borderColor = GRID;
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.plugins.legend.labels.boxHeight = 12;
  Chart.defaults.plugins.legend.labels.useBorderRadius = true;
  Chart.defaults.plugins.legend.labels.borderRadius = 3;
  Chart.defaults.plugins.legend.labels.color = "#E9EDF4";
  Chart.defaults.plugins.tooltip.backgroundColor = "#E9EDF4";
  Chart.defaults.plugins.tooltip.titleColor = "#16213A";
  Chart.defaults.plugins.tooltip.bodyColor = "#16213A";
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.boxPadding = 4;
  Chart.defaults.animation = matchMedia("(prefers-reduced-motion: reduce)").matches ? false : {duration: 500};
  return true;
}
function mkChart(id, cfg) {
  V.charts[id]?.destroy();
  V.charts[id] = new Chart($("#" + id), cfg);
}
const barDs = (label, data, color, extra = {}) => ({label, data, backgroundColor: color, borderColor: CARD, borderWidth: 2, borderRadius: 4, borderSkipped: false, maxBarThickness: 34, ...extra});
function emptyCard(id, msg) {
  const box = $("#" + id).parentElement;
  box.querySelector(".chart-empty")?.remove();
  if (msg) box.insertAdjacentHTML("beforeend", `<div class="chart-empty">${esc(msg)}</div>`);
}

async function loadInsights() {
  const d = await api("/api/insights");
  V.ins = d;
  renderInsights(d);
  if (d.geo_pending) setTimeout(async () => { const d2 = await api("/api/insights"); V.ins = d2; drawMap(d2); }, 12000);
}

function renderInsights(d) {
  flapStrip($("#insFlaps"), [["Response rate", d.response_rate + "%", "amber"], ["Heard back", d.heard_back], ["Sent last 7 days", d.last7],
    ["Median reply", d.median_reply_days != null ? d.median_reply_days + " days" : "--", "dim"], ["Follow-ups due", d.follow_up, "dim"]]);
  $("#insSub").textContent = d.total ? `${d.total} applications from ${fmtShort(d.first_applied)} to ${fmtShort(d.last_applied)}` +
    (d.median_apply_lag != null ? ` · you usually apply ${d.median_apply_lag} day${d.median_apply_lag === 1 ? "" : "s"} after a posting opens` : "") : "Nothing to chart yet";
  // status share bar
  const tot = d.total || 1;
  $("#statusBar").innerHTML = `<div class="sbar" role="img" aria-label="${SORDER.map(k => `${SL[k]} ${d.by_status[k] || 0}`).join(", ")}">` +
    SORDER.filter(k => d.by_status[k]).map(k => `<i style="flex:${d.by_status[k]};background:${SC[k]}" title="${SL[k]}: ${d.by_status[k]}"></i>`).join("") + `</div>` +
    `<ul class="sbar-legend">${SORDER.map(k => `<li><span class="sw" style="background:${SC[k]}"></span><span>${SL[k]}</span><b>${d.by_status[k] || 0}</b><em>${Math.round(100 * (d.by_status[k] || 0) / tot)}%</em></li>`).join("")}</ul>`;
  if (!chartDefaults()) { toast("Charts need an internet connection to load the first time.", {bad: true}); return; }
  const present = SORDER.filter(k => d.by_status[k]);
  // weekly stacked
  const wl = d.weeks.map(w => fmtShort(w.week));
  mkChart("chWeeks", {type: "bar", data: {labels: wl, datasets: present.map(k => barDs(SL[k], d.weeks.map(w => w.applied[k] || 0), SC[k]))},
    options: {maintainAspectRatio: false, interaction: {mode: "index", intersect: false}, plugins: {legend: {position: "top", align: "start"},
      tooltip: {callbacks: {title: i => "Week of " + i[0].label, footer: items => "Total: " + items.reduce((s, i) => s + i.parsed.y, 0)}}},
      scales: {x: {stacked: true, grid: {display: false}}, y: {stacked: true, beginAtZero: true, ticks: {precision: 0}, title: {display: true, text: "Applications"}}}}});
  // cities
  const top = d.cities.filter(c => c.city !== "Not recorded").slice(0, 10);
  const cityLabel = c => c.state ? `${c.city}, ${c.state}` : c.city;
  mkChart("chCities", {type: "bar", data: {labels: top.map(cityLabel), datasets: present.map(k => barDs(SL[k], top.map(c => c.status[k] || 0), SC[k], {maxBarThickness: 22}))},
    options: {indexAxis: "y", maintainAspectRatio: false, interaction: {mode: "index", axis: "y", intersect: false}, plugins: {legend: {position: "top", align: "start"}},
      scales: {x: {stacked: true, beginAtZero: true, ticks: {precision: 0}}, y: {stacked: true, grid: {display: false}}}}});
  // focus
  const fx = Object.entries(d.focus).sort((a, b) => Object.values(b[1]).reduce((s, x) => s + x, 0) - Object.values(a[1]).reduce((s, x) => s + x, 0));
  mkChart("chFocus", {type: "bar", data: {labels: fx.map(f => f[0]), datasets: present.map(k => barDs(SL[k], fx.map(f => f[1][k] || 0), SC[k], {maxBarThickness: 22}))},
    options: {indexAxis: "y", maintainAspectRatio: false, interaction: {mode: "index", axis: "y", intersect: false}, plugins: {legend: {position: "top", align: "start"}},
      scales: {x: {stacked: true, beginAtZero: true, ticks: {precision: 0}}, y: {stacked: true, grid: {display: false}}}}});
  // opened vs closed
  const anyClosed = d.weeks.some(w => w.closed);
  mkChart("chOpenClosed", {type: "bar", data: {labels: wl, datasets: [
      barDs("Applied", d.weeks.map(w => Object.values(w.applied).reduce((s, x) => s + x, 0)), MUTED, {maxBarThickness: 16}),
      barDs("Closed (not selected or no response)", d.weeks.map(w => w.closed), SC.rejected, {maxBarThickness: 16})]},
    options: {maintainAspectRatio: false, interaction: {mode: "index", intersect: false}, plugins: {legend: {position: "top", align: "start"}, tooltip: {callbacks: {title: i => "Week of " + i[0].label}}},
      scales: {x: {grid: {display: false}, ticks: {maxRotation: 0, autoSkip: true, autoSkipPadding: 14}}, y: {beginAtZero: true, ticks: {precision: 0}}}}});
  emptyCard("chOpenClosed", anyClosed ? "" : "Closed dates fill in as employers reply, or when an application passes the no-response cutoff.");
  // reply time
  const anyReply = d.reply_hist.some(h => h.n);
  mkChart("chReply", {type: "bar", data: {labels: d.reply_hist.map(h => h.label), datasets: [barDs("Applications", d.reply_hist.map(h => h.n), AMBER)]},
    options: {maintainAspectRatio: false, plugins: {legend: {display: false}}, scales: {x: {grid: {display: false}, title: {display: true, text: "Days until first reply"}}, y: {beginAtZero: true, ticks: {precision: 0}}}}});
  emptyCard("chReply", anyReply ? "" : "Fills in after your first email sync matches employer replies to applications.");
  // employer type
  const ex = Object.entries(d.employer_types || {}).sort((a, b) => Object.values(b[1]).reduce((s, x) => s + x, 0) - Object.values(a[1]).reduce((s, x) => s + x, 0));
  mkChart("chEmployer", {type: "bar", data: {labels: ex.map(f => f[0]), datasets: present.map(k => barDs(SL[k], ex.map(f => f[1][k] || 0), SC[k], {maxBarThickness: 22}))},
    options: {indexAxis: "y", maintainAspectRatio: false, interaction: {mode: "index", axis: "y", intersect: false}, plugins: {legend: {position: "top", align: "start"}},
      scales: {x: {stacked: true, beginAtZero: true, ticks: {precision: 0}}, y: {stacked: true, grid: {display: false}}}}});
  // platforms
  const px = Object.entries(d.platforms).sort((a, b) => b[1] - a[1]).slice(0, 10);
  mkChart("chPlatforms", {type: "bar", data: {labels: px.map(p => p[0]), datasets: [barDs("Applications", px.map(p => p[1]), AMBER, {maxBarThickness: 20})]},
    options: {indexAxis: "y", maintainAspectRatio: false, plugins: {legend: {display: false}}, scales: {x: {beginAtZero: true, ticks: {precision: 0}}, y: {grid: {display: false}}}}});
  drawCalendar(d.daily);
  drawMap(d);
}

function drawCalendar(daily) {
  const el = $("#calendar");
  const dates = Object.keys(daily).sort();
  if (!dates.length) { el.innerHTML = '<div class="chart-empty static">No application dates yet.</div>'; return; }
  const start = new Date(dates[0] + "T12:00:00"); start.setDate(start.getDate() - start.getDay());
  const end = new Date(); const max = Math.max(...Object.values(daily));
  const ramp = ["#22304F", "#5C4B26", "#8A6A26", "#BE8F2E", "#F5B841"];
  const lvl = n => !n ? 0 : Math.min(4, Math.ceil(4 * n / max));
  let cols = "", months = "", d = new Date(start), lastM = -1, w = 0;
  while (d <= end) {
    let cells = "";
    if (d.getMonth() !== lastM) { months += `<span style="grid-column:${w + 1}">${d.toLocaleDateString(undefined, {month: "short"})}</span>`; lastM = d.getMonth(); }
    for (let i = 0; i < 7; i++) {
      const iso = d.toISOString().slice(0, 10), n = daily[iso] || 0;
      cells += d > end ? `<i class="out"></i>` : `<i style="background:${ramp[lvl(n)]}" title="${d.toLocaleDateString(undefined, {weekday: "short", month: "short", day: "numeric"})}: ${n} application${n === 1 ? "" : "s"}"></i>`;
      d.setDate(d.getDate() + 1);
    }
    cols += `<div class="cal-col">${cells}</div>`; w++;
  }
  const busiest = Object.entries(daily).sort((a, b) => b[1] - a[1])[0];
  el.innerHTML = `<div class="cal-wrap"><div class="cal-days"><span>Sun</span><span></span><span>Tue</span><span></span><span>Thu</span><span></span><span>Sat</span></div>
    <div><div class="cal-months" style="grid-template-columns:repeat(${w},14px)">${months}</div><div class="cal-grid">${cols}</div></div></div>
    <div class="cal-foot"><span>Busiest day: <b>${fmtDate(busiest[0])}</b> with ${busiest[1]}</span><span class="cal-legend">Fewer ${ramp.map(c => `<i style="background:${c}"></i>`).join("")} More</span></div>`;
}

function drawMap(d) {
  if (!window.L) { $("#map").innerHTML = '<div class="chart-empty static">The map needs an internet connection.</div>'; return; }
  if (!V.map) {
    V.map = L.map("map", {scrollWheelZoom: false, attributionControl: true}).setView([39, -98], 4);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {maxZoom: 12, subdomains: "abcd",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'}).addTo(V.map);
    V.layer = L.layerGroup().addTo(V.map);
  }
  V.layer.clearLayers();
  const pts = d.cities.filter(c => c.lat != null);
  const max = Math.max(1, ...pts.map(p => p.n));
  pts.forEach(c => {
    const r = 5 + 17 * Math.sqrt(c.n / max);
    const rows = SORDER.filter(k => c.status[k]).map(k => `<li><span class="sw" style="background:${SC[k]}"></span>${SL[k]} <b>${c.status[k]}</b></li>`).join("");
    L.circleMarker([c.lat, c.lng], {radius: r, color: "#16213A", weight: 2, fillColor: AMBER, fillOpacity: .78})
      .bindPopup(`<div class="pop"><b>${esc(c.city)}${c.state ? ", " + esc(c.state) : ""}</b><span>${c.n} application${c.n === 1 ? "" : "s"}${c.approx ? " · placed at state center" : ""}</span><ul>${rows}</ul></div>`)
      .bindTooltip(`${c.city}${c.state ? ", " + c.state : ""}: ${c.n}`, {direction: "top"})
      .addTo(V.layer);
  });
  if (pts.length && !V.mapFitted) { V.map.fitBounds(L.latLngBounds(pts.map(p => [p.lat, p.lng])).pad(0.15)); V.mapFitted = true; }
  setTimeout(() => V.map.invalidateSize(), 50);
  const off = d.cities.filter(c => c.lat == null).map(c => `${c.city}${c.state ? ", " + c.state : ""} (${c.n})`);
  let note = $("#mapNote");
  if (!note) { $("#map").insertAdjacentHTML("afterend", '<p class="hint" id="mapNote"></p>'); note = $("#mapNote"); }
  note.textContent = off.length ? `Not on the map: ${off.join(", ")}` + (d.geo_pending ? ". Looking up remaining cities…" : "") : "";
}

/* ---------------------------------------------------------------- radar */
const RF = {rQueries: "radar_queries", rLocs: "radar_locations", rMatch: "radar_min_match", rPay: "radar_min_pay", rAge: "radar_max_age_days",
  rEvery: "radar_every_hours", rExclude: "radar_exclude", rWatch: "watch_companies", rTo: "alert_email_to", rExclStates: "radar_exclude_states"};
const RB = {rAuto: "watch_auto", rOn: "radar_enabled", rEmail: "alert_email_on", rDesk: "alert_desktop_on"};
let radarPoll;
async function loadRadar() {
  const [r, s] = await Promise.all([api("/api/radar"), api("/api/settings")]);
  V.radar = r;
  const cfg = s.settings;
  if (!$("#radarForm").dataset.dirty) {
    Object.entries(RF).forEach(([id, k]) => $("#" + id).value = cfg[k] ?? "");
    if (!cfg.radar_queries) $("#rQueries").value = r.profile.roles.join("\n");
    if (!cfg.radar_locations) $("#rLocs").value = r.profile.areas.map(a => a.label).join("\n");
    $("#rRemote").checked = !!r.profile.remote;
    Object.entries(RB).forEach(([id, k]) => $("#" + id).checked = !!cfg[k]);
  }
  const FT = ["Credit union", "University / college", "School / district", "Government", "Healthcare", "Private company"];
  if (!$("#radarForm").dataset.dirty) {
    V.favor = new Set(r.favor_types || []); $("#rOnly").checked = !!(r.only_types || []).length;
    V.sources = Object.fromEntries((r.sources || []).map(x => [x.name, x.on]));
  }
  $("#rFavor").innerHTML = FT.map(t => `<button type="button" class="chip" aria-pressed="${V.favor.has(t)}" data-favor="${esc(t)}">${esc(t)}</button>`).join("");
  $("#rSources").innerHTML = (r.sources || []).map(x => `<label class="switch src"><input type="checkbox" data-src="${esc(x.name)}" ${V.sources[x.name] ? "checked" : ""}><span></span><b>${esc(x.name)}</b><em>${esc(x.note)}</em></label>`).join("");
  $("#rAlertSites").innerHTML = (r.alert_sites || []).map(x => `<div class="alert-site"><b>${esc(x.site)}</b><em>${esc(x.how)}</em><div class="links">${x.links.map(l => `<a class="btn btn-sm" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ${ICON.ext}</a>`).join("")}</div></div>`).join("");
  $("#rIndeed").innerHTML = (r.indeed || []).map(l => `<a class="btn btn-sm" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ${ICON.ext}</a>`).join("");
  $("#rLearned").textContent = r.profile.learned_from ? `Learned from your ${r.profile.learned_from} applications. Edit anything below; clear a box to go back to what Dispatch learned.` : "Dispatch learns these from the jobs you apply to.";
  $("#rSites").innerHTML = r.sites.length ? `<p class="hint">${r.sites.length} career sites watched: ${r.sites.slice(0, 14).map(x => esc(x.company || x.label.split(":")[1])).join(", ")}${r.sites.length > 14 ? "…" : ""}</p>` : "";
  try { localStorage.setItem("dispatch.radarSeen", new Date().toISOString()); } catch {}
  $("#radarBadge").hidden = true;
  renderRadarStatus(); renderRadarList();
  if (r.status.running) pollRadar();
}
function renderRadarStatus() {
  const r = V.radar; if (!r) return;
  const st = r.status;
  const R = r.report || {};
  const rep = Object.entries(R.Sources || {}).map(([k, v]) => `<span class="rep-item"><b>${esc(k)}</b> ${esc(v)}</span>`).join("") +
    (R["Filtered out"] && Object.keys(R["Filtered out"]).length ? `<span class="rep-item muted">Filtered out: ${Object.entries(R["Filtered out"]).map(([k, v]) => `${v} ${esc(k)}`).join(", ")}</span>` : "");
  $("#radarStatus").innerHTML = st.running ? `<div class="loading">${esc(st.log.slice(-1)[0] || "Searching…")}</div>`
    : `<p>${r.last ? `Last search ${esc(ago(r.last).toLowerCase())}${new Date(r.last).toDateString() === new Date().toDateString() ? " at " + new Date(r.last).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}) : ""} found <b>${r.found ?? 0}</b> roles that fit.` : "Radar hasn't run yet."}
      ${r.last_alert ? ` Last alert: “${esc(r.last_alert_headline || "")}” ${esc(ago(r.last_alert).toLowerCase())} (email ${esc(r.last_alert_result?.email || "off")}).` : ""}</p>
      ${st.error ? `<p class="bad">${esc(st.error)}</p>` : ""}<div class="rep">${rep}</div>`;
  const b = $("#btnRadarRun"); b.disabled = st.running; b.classList.toggle("spinning", st.running); $("span", b).textContent = st.running ? "Searching…" : "Run Radar now";
}
function renderRadarList() {
  if (!V.radar) return;
  const ids = new Set(V.radar.finds.map(f => f.id));
  let list = state.jobs.filter(j => ids.has(j.id) && j.status !== "hidden");
  const types = {};
  list.forEach(j => types[j.employer_type || "Private company"] = (types[j.employer_type || "Private company"] || 0) + 1);
  $("#radarTypes").innerHTML = Object.entries(types).sort((a, b) => b[1] - a[1]).map(([t, n]) => `<button class="chip" aria-pressed="${V.rtype === t}" data-rtype="${esc(t)}">${esc(t)} <span class="cn">${n}</span></button>`).join("");
  if (V.rtype) list = list.filter(j => (j.employer_type || "Private company") === V.rtype);
  const fit = Object.fromEntries(V.radar.finds.map(f => [f.id, f.fit || 0]));
  const s = $("#rSort").value;
  list.sort(s === "posted" ? (a, b) => (postedOf(b) || "").localeCompare(postedOf(a) || "") : s === "pay" ? (a, b) => (b.salary_max || b.salary_min || 0) - (a.salary_max || a.salary_min || 0) : (a, b) => (fit[b.id] || 0) - (fit[a.id] || 0));
  $("#radarCount").textContent = list.length || "";
  $("#radarList").innerHTML = list.length ? list.map(jobRow).join("")
    : `<div class="empty"><h3>No finds yet</h3><p>Every hour Radar searches LinkedIn, job boards and the career sites of companies you've applied to for ${esc(V.radar.profile.roles.slice(0, 4).join(", "))} roles in ${esc(V.radar.profile.areas.map(a => a.label).slice(0, 4).join(", "))}${V.radar.profile.remote ? " and remote" : ""}.</p><button class="btn btn-amber" id="btnRadarEmpty">Run Radar now</button></div>`;
  $("#btnRadarEmpty") && ($("#btnRadarEmpty").onclick = runRadar);
}
async function runRadar() {
  await api("/api/radar/run", {method: "POST"});
  V.radar.status.running = true; renderRadarStatus(); pollRadar();
}
function pollRadar() {
  clearInterval(radarPoll);
  radarPoll = setInterval(async () => {
    const r = await api("/api/radar").catch(() => null); if (!r) return;
    V.radar = r; renderRadarStatus();
    if (!r.status.running) {
      clearInterval(radarPoll);
      await load(); renderRadarList();
      toast(r.status.error ? r.status.error : r.status.new ? `Radar found ${r.status.new} new role${r.status.new > 1 ? "s" : ""}` : "Radar finished. Nothing new since last time.", {bad: !!r.status.error});
    }
  }, 1500);
}
$("#btnRadarRun").onclick = runRadar;
$("#rSort").onchange = renderRadarList;
$("#radarForm").addEventListener("input", () => $("#radarForm").dataset.dirty = "1");
document.addEventListener("click", e => {
  const f = e.target.closest("[data-favor]");
  if (f) { const t = f.dataset.favor; V.favor.has(t) ? V.favor.delete(t) : V.favor.add(t); f.setAttribute("aria-pressed", V.favor.has(t)); $("#radarForm").dataset.dirty = "1"; }
  const rt = e.target.closest("[data-rtype]");
  if (rt) { V.rtype = V.rtype === rt.dataset.rtype ? "" : rt.dataset.rtype; renderRadarList(); }
});
document.addEventListener("change", e => { if (e.target.dataset.src) { V.sources[e.target.dataset.src] = e.target.checked; $("#radarForm").dataset.dirty = "1"; } });
$("#radarForm").addEventListener("submit", async e => {
  e.preventDefault();
  const body = Object.fromEntries(Object.entries(RF).map(([id, k]) => [k, ["radar_min_match", "radar_min_pay", "radar_max_age_days", "radar_every_hours"].includes(k) ? +$("#" + id).value : $("#" + id).value.trim()]));
  Object.entries(RB).forEach(([id, k]) => body[k] = $("#" + id).checked);
  body.radar_remote = $("#rRemote").checked;
  body.radar_favor_types = [...V.favor];
  body.radar_only_types = $("#rOnly").checked ? [...V.favor] : [];
  body.radar_sources = V.sources;
  if (body.radar_queries === V.radar.defaults.queries.join("\n")) body.radar_queries = "";
  if (body.radar_locations === V.radar.defaults.locations.filter(l => l !== "Remote").join("\n")) body.radar_locations = "";
  await api("/api/settings", {method: "POST", body});
  delete $("#radarForm").dataset.dirty;
  toast("Radar settings saved");
  loadRadar();
});
$("#rReset").onclick = () => { $("#rQueries").value = V.radar.defaults.queries.join("\n"); $("#rLocs").value = V.radar.defaults.locations.filter(l => l !== "Remote").join("\n"); $("#radarForm").dataset.dirty = "1"; };
$("#btnAlertTest").onclick = async () => {
  const b = $("#btnAlertTest"); b.disabled = true; b.textContent = "Sending…";
  try {
    const r = await api("/api/alerts/test", {method: "POST"});
    const em = r.email || "off";
    toast(em === "sent" ? "Test alert emailed. Check your inbox." : em === "no account" ? "Add an email account in Settings first." : `Email ${em}`, {bad: em !== "sent", ms: 8000});
  } finally { b.disabled = false; b.textContent = "Send me a test alert"; }
};

/* hooks into the jobs view */
const _render = render;
render = function () { _render(); if (window.currentView === "radar") renderRadarList(); };
window.onJobsLoaded = d => {
  let seen = ""; try { seen = localStorage.getItem("dispatch.radarSeen") || ""; } catch {}
  const n = d.jobs.filter(j => j.radar && j.status === "discovered" && (j.radar_found || "") > seen).length;
  const b = $("#radarBadge"); b.hidden = !n || window.currentView === "radar"; b.textContent = n;
};
addEventListener("hashchange", () => { const h = location.hash.slice(1); if (h !== window.currentView && ["jobs", "apps", "insights", "radar"].includes(h)) go(h, false); });
go(["jobs", "apps", "insights", "radar"].includes(location.hash.slice(1)) ? location.hash.slice(1) : "jobs", false);
