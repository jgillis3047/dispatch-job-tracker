/* Dispatch front end */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const api = async (path, opts = {}) => {
  const r = await fetch(path, {headers: {"Content-Type": "application/json"}, ...opts,
    body: opts.body && typeof opts.body !== "string" ? JSON.stringify(opts.body) : opts.body});
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Request failed (${r.status})`);
  return data;
};
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

const STATUSES = [
  {key: "new", label: "New"}, {key: "saved", label: "Saved"}, {key: "applied", label: "Applied"},
  {key: "interviewing", label: "Interviewing"}, {key: "offer", label: "Offer"}, {key: "passed", label: "Not moving forward"},
];
const EXTRA_TABS = [{key: "all", label: "All active"}, {key: "discovered", label: "Radar & web finds"}, {key: "hidden", label: "Hidden"}];
const STYLES = ["Remote", "Hybrid", "On-site"];

const state = {
  jobs: [], resume: {skills: []}, sync: {}, view: "new", q: "", styles: new Set(), sources: new Set(),
  minPay: 0, noCL: false, noRef: false, hasPay: false, sort: "posted", selected: null, webMeta: null, boardSig: "",
};
try { Object.assign(state, JSON.parse(localStorage.getItem("dispatch.view") || "{}"), {styles: new Set(), sources: new Set()}); } catch {}
const persist = () => { try { localStorage.setItem("dispatch.view", JSON.stringify({view: state.view, sort: state.sort})); } catch {} };

/* ---------------------------------------------------------------- helpers */
const ICON = {
  star: '<svg viewBox="0 0 24 24"><path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8L3.5 9.7l5.9-.9z"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
  eyeOff: '<svg viewBox="0 0 24 24"><path d="M3 3l18 18M10.6 6.1A9.8 9.8 0 0 1 12 6c5 0 8.5 4.2 9.5 6-.4.8-1.3 2-2.5 3.2M6.6 7.6C4.6 8.9 3.2 10.8 2.5 12c1 1.8 4.5 6 9.5 6 1.5 0 2.9-.4 4.1-1"/><path d="M9.9 10a3 3 0 0 0 4.1 4.1"/></svg>',
  ext: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  radar: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m20 20-4.2-4.2"/></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M4 12a8 8 0 0 1 14-5.3M20 12a8 8 0 0 1-14 5.3M18 3v4h-4M6 21v-4h4"/></svg>',
  copy: '<svg viewBox="0 0 24 24"><rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/></svg>',
};

function ago(iso) {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? iso + "T12:00:00" : iso);
  const days = Math.floor((Date.now() - d) / 864e5);
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  if (days < 60) return `${Math.floor(days / 7)} wk${days >= 14 ? "s" : ""} ago`;
  return d.toLocaleDateString(undefined, {month: "short", day: "numeric"});
}
const fmtDate = iso => iso ? new Date(iso.length === 10 ? iso + "T12:00:00" : iso).toLocaleDateString(undefined, {month: "short", day: "numeric", year: "numeric"}) : "";
const postedOf = j => j.posted_date || (j.email_date || "").slice(0, 10) || (j.first_seen || "").slice(0, 10);
const reqHas = (j, k, strict = true) => (j.requirements || []).some(r => r.key === k && (!strict || !r.optional));
const matchColor = m => m == null ? "var(--line)" : m >= 70 ? "var(--go)" : m >= 45 ? "var(--flap)" : "var(--stop)";

function toast(msg, opts = {}) {
  const t = document.createElement("div");
  t.className = "toast" + (opts.bad ? " bad" : "");
  t.innerHTML = `<span>${esc(msg)}</span>` + (opts.action ? `<button>${esc(opts.action)}</button>` : "");
  if (opts.action) t.querySelector("button").onclick = () => { opts.onAction(); t.remove(); };
  $("#toasts").append(t);
  setTimeout(() => t.remove(), opts.ms || 4200);
}

/* ---------------------------------------------------------------- data */
async function load() {
  const d = await api("/api/jobs");
  state.jobs = d.jobs; state.resume = d.resume; state.sync = d.sync; state.emailsRead = d.emails_read; state.accounts = d.accounts; state.radar = d.radar;
  render();
  window.onJobsLoaded && window.onJobsLoaded(d);
  state.needsConnect = d.needs_connect;
  if (!d.accounts.length && !state.connectShown) { state.connectShown = true; openConnect(); }
}

function inView(j) {
  const v = state.view;
  if (v === "discovered") return j.status === "discovered";
  if (v === "hidden") return j.status === "hidden";
  if (v === "all") return !["hidden", "discovered", "passed"].includes(j.status);
  return j.status === v;
}

function filtered() {
  const q = state.q.trim().toLowerCase();
  let list = state.jobs.filter(inView).filter(j => {
    if (q && ![j.title, j.company, j.location, ...(j.skills || [])].join(" ").toLowerCase().includes(q)) return false;
    if (state.styles.size && !state.styles.has(j.work_style)) return false;
    if (state.sources.size && !state.sources.has(j.source_label)) return false;
    if (state.minPay && !((j.salary_max || j.salary_min || 0) >= state.minPay * 1000)) return false;
    if (state.noCL && reqHas(j, "cover_letter")) return false;
    if (state.noRef && reqHas(j, "references")) return false;
    if (state.hasPay && !j.salary_min) return false;
    return true;
  });
  const by = {
    posted: (a, b) => (postedOf(b) || "").localeCompare(postedOf(a) || ""),
    match: (a, b) => (b.match ?? -1) - (a.match ?? -1),
    pay: (a, b) => (b.salary_max || b.salary_min || 0) - (a.salary_max || a.salary_min || 0),
    company: (a, b) => (a.company || "").localeCompare(b.company || ""),
  }[state.sort];
  return list.sort(by);
}

async function setStatus(id, status, quiet) {
  const j = state.jobs.find(x => x.id === id);
  if (!j) return;
  const prev = j.status;
  j.status = status;
  render();
  await api(`/api/jobs/${encodeURIComponent(id)}`, {method: "PATCH", body: {status}});
  if (!quiet) {
    const label = status === "applied" ? "Marked applied and added to Applications" : status === "hidden" ? "Hidden" : status === "new" ? "Moved back to New" : `Marked ${STATUSES.find(s => s.key === status)?.label || status}`;
    toast(label, {action: "Undo", onAction: () => setStatus(id, prev, true)});
  }
}

/* ---------------------------------------------------------------- render */
function render() {
  renderSync(); renderBoard(); renderStats(); renderRail(); renderList();
  if (state.selected) renderDrawer(state.jobs.find(j => j.id === state.selected));
}

function renderSync() {
  const s = state.sync || {}, pill = $("#syncPill"), btn = $("#btnSync");
  pill.className = "sync-pill " + (s.running ? "busy" : s.error ? "err" : s.last_ok ? "ok" : "");
  $("#syncText").textContent = s.running ? (s.log?.slice(-1)[0] || "Syncing…")
    : s.error ? (/^CONNECT:/.test(s.error) ? "Gmail not connected yet" : s.error)
    : s.last_ok ? `Synced ${(state.accounts || []).length > 1 ? state.accounts.length + " inboxes " : ""}${ago(s.last_ok).toLowerCase() === "today" ? "today at " + new Date(s.last_ok).toLocaleTimeString([], {hour: "numeric", minute: "2-digit"}) : ago(s.last_ok)} · ${state.emailsRead || 0} emails read`
    : state.jobs.some(j => j.demo) ? "Showing sample alerts" : "Gmail not connected yet";
  btn.classList.toggle("spinning", !!s.running);
  btn.disabled = !!s.running;
  $("span", btn).textContent = s.running ? "Syncing…" : "Sync email";
}

function flapHTML(text, max, cls = "") {
  const t = String(text || "").toUpperCase().slice(0, max);
  return `<span class="flap ${cls}" data-text="${esc(t)}">` +
    [...t].map(c => `<span class="ch${c === " " ? " sp" : ""}">${c === " " ? "&nbsp;" : esc(c)}</span>`).join("") + "</span>";
}
function animateFlaps(root) {
  if (REDUCED) return;
  const POOL = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789$";
  $$(".flap", root).forEach((f, row) => {
    $$(".ch:not(.sp)", f).forEach((ch, i) => {
      const final = ch.textContent;
      let n = 3 + Math.floor(Math.random() * 4);
      const tick = () => {
        if (n-- <= 0) { ch.textContent = final; return; }
        ch.textContent = POOL[Math.floor(Math.random() * POOL.length)];
        ch.classList.remove("flip"); void ch.offsetWidth; ch.classList.add("flip");
        setTimeout(tick, 55);
      };
      setTimeout(tick, row * 18 + i * 22);
    });
  });
}

function renderBoard() {
  const rows = state.jobs.filter(j => !["hidden", "discovered"].includes(j.status))
    .sort((a, b) => (postedOf(b) || "").localeCompare(postedOf(a) || "")).slice(0, 6);
  const sig = rows.map(r => r.id + r.match).join("|");
  if (sig === state.boardSig) return;
  state.boardSig = sig;
  const el = $("#boardRows");
  if (!rows.length) {
    el.innerHTML = `<div class="board-empty">No postings yet. Connect the inbox that gets your job alerts, then sync.<br>
      <button class="btn btn-amber" data-act="connect">Connect Gmail</button><button class="btn" data-act="demo">Load sample alerts</button></div>`;
    return;
  }
  el.innerHTML = rows.map(j => {
    const p = postedOf(j), d = p ? new Date(p + "T12:00:00") : null;
    const when = d ? d.toLocaleDateString("en-US", {month: "short", day: "2-digit"}) : "--";
    return `<div class="brow" role="row" tabindex="0" data-id="${esc(j.id)}">
      <span role="cell">${flapHTML(when, 6, "dim")}</span>
      <span role="cell">${flapHTML(j.title, 30)}</span>
      <span role="cell">${flapHTML(j.company || "—", 20, "dim")}</span>
      <span role="cell" class="c-loc">${flapHTML((j.work_style === "Remote" ? "Remote" : (j.location || "").split(/[,(]/)[0]) || "—", 14, "dim")}</span>
      <span role="cell" class="c-pay">${flapHTML(j.salary_label || "—", 10, "amber")}</span>
      <span role="cell" class="c-match">${flapHTML(j.match != null ? j.match + "%" : "--", 4, j.match >= 70 ? "go" : "amber")}</span></div>`;
  }).join("");
  animateFlaps(el);
}

function renderStats() {
  const active = state.jobs.filter(j => !["hidden", "discovered"].includes(j.status));
  const week = active.filter(j => postedOf(j) && (Date.now() - new Date(postedOf(j) + "T12:00:00")) < 7 * 864e5).length;
  const pays = active.map(j => j.salary_max && j.salary_min ? (j.salary_min + j.salary_max) / 2 : j.salary_min).filter(Boolean);
  const med = pays.length ? pays.sort((a, b) => a - b)[Math.floor(pays.length / 2)] : null;
  const applied = active.filter(j => ["applied", "interviewing", "offer"].includes(j.status)).length;
  const missing = {};
  active.forEach(j => (j.skills_missing || []).forEach(s => missing[s] = (missing[s] || 0) + 1));
  const gaps = Object.entries(missing).sort((a, b) => b[1] - a[1]).slice(0, 4);
  $("#stats").innerHTML = `
    <div class="stat"><b>${active.length}</b><span>Postings tracked</span></div>
    <div class="stat"><b>${week}</b><span>Posted in the last 7 days</span></div>
    <div class="stat"><b>${med ? "$" + Math.round(med / 1000) + "K" : "—"}</b><span>Median listed pay${pays.length ? ` (${pays.length} with pay)` : ""}</span></div>
    <div class="stat"><b>${applied}</b><span>Applied or further</span></div>
    <div class="stat"><span>Skills employers ask for that aren't on your resume</span>
      <div class="skills-mini">${gaps.length ? gaps.map(([s, n]) => `<span class="tag">${esc(s)} · ${n}</span>`).join("") : '<span class="tag">None yet</span>'}</div></div>`;
}

function renderRail() {
  const count = k => state.jobs.filter(j => k === "all" ? !["hidden", "discovered", "passed"].includes(j.status) : j.status === k).length;
  const tabs = [...STATUSES.map(s => ({...s})), ...EXTRA_TABS];
  $("#statusTabs").innerHTML = tabs.map((t, i) => `<button class="tab${i === STATUSES.length ? " sep" : ""}" role="tab" aria-selected="${state.view === t.key}" data-view="${t.key}">
    <span>${t.label}</span><span class="n">${count(t.key)}</span></button>`).join("");
  $("#styleChips").innerHTML = STYLES.map(s => `<button class="chip" aria-pressed="${state.styles.has(s)}" data-style="${s}">${s}</button>`).join("");
  const sources = [...new Set(state.jobs.map(j => j.source_label).filter(Boolean))].sort();
  $("#sourceChips").innerHTML = sources.length ? sources.map(s => `<button class="chip" aria-pressed="${state.sources.has(s)}" data-source="${esc(s)}">${esc(s)}</button>`).join("") : '<span class="hint" style="margin:0">Appears after your first sync</span>';
  const r = state.resume || {};
  $("#resumeCard").innerHTML = r.name ? `Matching against <strong>${esc(r.name)}</strong> · ${r.skills.length} skills found` :
    `No resume found. Put your resume PDF in the Employment folder to get match scores.`;
}

function jobRow(j) {
  const m = j.match;
  const reqs = (j.requirements || []).filter(r => ["cover_letter", "references", "portfolio", "transcripts", "writing_sample", "assessment", "clearance"].includes(r.key));
  const isNew = j.status === "new";
  return `<article class="job${state.selected === j.id ? " sel" : ""}" data-id="${esc(j.id)}" tabindex="0" aria-label="${esc(j.title)} at ${esc(j.company || "")}">
    <div class="ring${m == null ? " na" : ""}" style="--p:${m || 0};--c:${matchColor(m)}" title="${m == null ? "No skills listed to compare" : m + "% of listed skills are on your resume"}"><b>${m == null ? "—" : m}</b></div>
    <div>
      <h3 class="j-title">${esc(j.title)}${isNew ? '<span class="newdot" title="New"></span>' : ""}</h3>
      <div class="j-meta"><span class="co">${esc(j.company || "Company not listed")}</span><span>${esc(j.location || "")}</span>
        ${j.salary_label ? `<span class="pay">${esc(j.salary_label)}</span>` : ""}<span>${esc(ago(postedOf(j)))}</span></div>
      <div class="j-tags">
        ${j.work_style ? `<span class="tag style">${esc(j.work_style)}</span>` : ""}
        ${reqs.map(r => `<span class="tag ${r.optional ? "opt" : "need"}">${esc(r.label)}${r.optional ? " · optional" : ""}</span>`).join("")}
        ${j.employer_type && j.employer_type !== "Private company" ? `<span class="tag etype">${esc(j.employer_type)}</span>` : ""}
        <span class="tag src">via ${esc(j.source_label)}${j.area && j.area !== "Unknown" ? " · " + esc(j.area) : ""}</span>
        ${j.status === "hidden" && j.hidden_reason ? `<span class="tag">${esc(j.hidden_reason)}</span>` : ""}
      </div>
    </div>
    <div class="j-actions">
      <button class="ibtn${j.status === "saved" ? " on" : ""}" data-act="save" title="${j.status === "saved" ? "Saved" : "Save"}" aria-label="Save">${ICON.star}</button>
      <button class="ibtn${["applied", "interviewing", "offer"].includes(j.status) ? " on" : ""}" data-act="applied" title="Mark applied" aria-label="Mark applied">${ICON.check}</button>
      <button class="ibtn" data-act="hide" title="${j.status === "hidden" ? "Unhide" : "Hide"}" aria-label="Hide">${ICON.eyeOff}</button>
      <a class="btn btn-amber btn-sm" href="${esc(j.apply_url || j.url)}" target="_blank" rel="noopener" data-act="apply">Apply ${ICON.ext}</a>
    </div></article>`;
}

function renderList() {
  const list = filtered();
  const tab = [...STATUSES, ...EXTRA_TABS].find(t => t.key === state.view);
  $("#listTitle").textContent = tab ? tab.label : "Jobs";
  $("#listCount").textContent = list.length ? `${list.length}` : "";
  $("#sort").value = state.sort;
  const wb = $("#webBar");
  if (state.view === "discovered" && state.webMeta) {
    const m = state.webMeta;
    wb.hidden = false;
    wb.innerHTML = `<span class="lbl">Also search “${esc(m.query)}” on</span>` + m.links.map(l => `<a class="btn btn-sm" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ${ICON.ext}</a>`).join("") +
      `<span class="rep">${Object.entries(m.report).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(" · ")}</span>`;
  } else wb.hidden = true;
  if (!list.length) {
    const hasAny = state.jobs.length > 0;
    $("#list").innerHTML = `<div class="empty">${
      state.view === "discovered" ? `<h3>Nothing found on the web yet</h3><p>Search job boards for a role, or open any posting and choose “Similar roles”.</p><button class="btn btn-amber" data-act="find">Find roles</button>`
      : !hasAny ? `<h3>Your alerts will land here</h3><p>Add the inboxes that get your LinkedIn, Indeed, ZipRecruiter or Glassdoor alerts.</p><button class="btn btn-amber" data-act="connect">Connect Gmail</button><button class="btn" data-act="demo">Load sample alerts</button>`
      : `<h3>No jobs in this view</h3><p>Try another pipeline stage or loosen the filters.</p><button class="btn" data-act="clear">Clear filters</button>`}</div>`;
    return;
  }
  $("#list").innerHTML = list.map(jobRow).join("");
}

/* ---------------------------------------------------------------- drawer */
function openDrawer(id) {
  state.selected = id;
  const j = state.jobs.find(x => x.id === id);
  renderDrawer(j);
  $("#drawer").classList.add("open"); $("#drawer").setAttribute("aria-hidden", "false");
  $("#scrim").hidden = false;
  $("#drawer").focus();
  $$(".job").forEach(el => el.classList.toggle("sel", el.dataset.id === id));
}
function closeDrawer() {
  state.selected = null;
  $("#drawer").classList.remove("open"); $("#drawer").setAttribute("aria-hidden", "true");
  $("#scrim").hidden = true;
  $$(".job.sel").forEach(el => el.classList.remove("sel"));
}

function fact(label, val) { return `<div class="fact"><span>${label}</span><b class="${val ? "" : "none"}">${val ? esc(val) : "Not listed"}</b></div>`; }

function renderDrawer(j) {
  if (!j) return closeDrawer();
  const done = JSON.parse((() => { try { return localStorage.getItem("dispatch.reqs." + j.id) || "{}"; } catch { return "{}"; } })());
  const reqs = j.requirements || [];
  const hasDesc = (j.description || "").length > 40;
  const statusBtns = [...STATUSES, {key: "hidden", label: "Hidden"}].map(s => `<button class="seg" aria-pressed="${j.status === s.key}" data-status="${s.key}">${s.label}</button>`).join("");
  const blocked = j.enrich_status && !["ok", "demo"].includes(j.enrich_status);
  $("#drawer").innerHTML = `
  <div class="d-top">
    <div class="row"><span class="d-src">From ${esc(j.source_label)}${j.email_subject ? ` · “${esc(j.email_subject)}”` : ""}</span>
      <button class="btn btn-icon" data-act="close" aria-label="Close details">${ICON.x}</button></div>
    <h2 class="d-title">${esc(j.title)}</h2>
    <div class="d-co">${esc(j.company || "Company not listed")}</div>
    <div class="d-actions">
      <a class="btn btn-amber" href="${esc(j.apply_url || j.url)}" target="_blank" rel="noopener">Apply${j.apply_type ? " on " + esc(j.apply_type) : ""} ${ICON.ext}</a>
      ${j.url && j.url !== j.apply_url ? `<a class="btn" href="${esc(j.url)}" target="_blank" rel="noopener">View posting ${ICON.ext}</a>` : ""}
      <button class="btn" data-act="similar">${ICON.radar} Similar roles</button>
      <button class="btn btn-icon" data-act="copy" title="Copy apply link" aria-label="Copy apply link">${ICON.copy}</button>
      ${j.origin !== "web" && !j.demo ? `<button class="btn btn-icon" data-act="refresh" title="Re-read posting" aria-label="Re-read posting">${ICON.refresh}</button>` : ""}
    </div>
  </div>
  <div class="d-body">
    <div class="facts">
      ${fact("Pay", j.salary_text || j.salary_label)}${fact("Posted", postedOf(j) ? `${fmtDate(postedOf(j))} (${ago(postedOf(j)).toLowerCase()})` : "")}
      ${fact("Location", [j.location, j.work_style && !(j.location || "").includes(j.work_style) ? j.work_style : ""].filter(Boolean).join(" · "))}
      ${fact("Type", [j.employment_type, j.seniority].filter(Boolean).join(" · "))}
      ${j.closes_date ? fact("Closes", fmtDate(j.closes_date)) : ""}${j.applicants ? fact("Applicants", j.applicants) : ""}
    </div>
    ${blocked ? `<div class="warn-note">${esc(j.source_label)} didn't let Dispatch open this posting (${esc(j.enrich_status)}), so details come from the alert email only. Open the posting to check requirements.</div>` : ""}

    <section class="d-sec"><h3>Status</h3><div class="status-seg">${statusBtns}</div></section>

    <section class="d-sec">
      <h3>Skills <small>${j.match != null ? `${j.match}% on your resume` : "none listed"}</small></h3>
      ${j.match != null ? `<div class="meter"><i style="width:${j.match}%;background:${matchColor(j.match)}"></i></div>` : ""}
      <div>${(j.skills_have || []).map(s => `<span class="skill have">${ICON.check}${esc(s)}</span>`).join("")}${(j.skills_missing || []).map(s => `<span class="skill miss">${esc(s)}</span>`).join("")}</div>
    </section>

    <section class="d-sec">
      <h3>What to submit <small>${reqs.length ? "check off as you go" : ""}</small></h3>
      <ul class="reqs">
        <li class="req${done.resume ? " ok" : ""}"><input type="checkbox" data-req="resume" ${done.resume ? "checked" : ""} aria-label="Resume done"><div><b>Resume</b></div></li>
        ${reqs.map(r => `<li class="req${done[r.key] ? " ok" : ""}"><input type="checkbox" data-req="${r.key}" ${done[r.key] ? "checked" : ""} aria-label="${esc(r.label)} done">
          <div><b>${esc(r.label)}</b>${r.optional ? '<span class="o">Optional</span>' : ""}${r.snippet ? `<p>${esc(r.snippet)}</p>` : ""}</div></li>`).join("")}
      </ul>
      ${!hasDesc ? `<p class="hint">No description was available, so other requirements may be missing.</p>` : ""}
    </section>

    <section class="d-sec" id="simSec" hidden></section>

    ${hasDesc ? `<section class="d-sec"><h3>Description</h3><p class="desc" id="desc">${esc(j.description)}</p>
      <button class="btn btn-sm" data-act="more" style="margin-top:8px">Show full description</button></section>` : ""}

    <section class="d-sec"><h3>Notes</h3><textarea class="notes" id="notes" placeholder="Recruiter name, referral, follow-up date…">${esc(j.notes || "")}</textarea></section>
  </div>`;
}

async function similarFor(j) {
  const sec = $("#simSec");
  sec.hidden = false;
  sec.innerHTML = `<h3>Similar roles</h3><div class="loading">Searching job boards…</div>`;
  try {
    const d = await api(`/api/jobs/${encodeURIComponent(j.id)}/similar`, {method: "POST", body: {}});
    state.webMeta = d;
    const top = d.jobs.slice(0, 8);
    sec.innerHTML = `<h3>Similar roles <small>for “${esc(d.query)}”${d.location ? " near " + esc(d.location) : ""}</small></h3>
      ${top.length ? `<div class="sim-list">${top.map(s => `<div class="sim"><div><div class="t">${esc(s.title)}</div>
        <div class="m">${esc(s.company || "")} · ${esc(s.location || "")}${s.salary_label ? " · " + esc(s.salary_label) : ""}${s.match != null ? ` · ${s.match}% match` : ""} · ${esc(s.board)}</div></div>
        <a class="btn btn-sm" href="${esc(s.apply_url)}" target="_blank" rel="noopener">Open ${ICON.ext}</a></div>`).join("")}</div>
        ${d.jobs.length > 8 ? `<button class="btn btn-sm" data-act="seeweb" style="margin-top:8px">See all ${d.jobs.length} in “Found on the web”</button>` : ""}`
      : `<p class="hint">${Object.values(d.report).every(v => v !== "0 found" && !/found/.test(v)) ? "Couldn't reach the open job boards. Check your internet connection, or" : "The open job boards had nothing close."} Try the big boards directly:</p>`}
      <div class="links" style="margin-top:10px">${d.links.map(l => `<a class="btn btn-sm" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ${ICON.ext}</a>`).join("")}</div>`;
    const fresh = await api("/api/jobs"); state.jobs = fresh.jobs; renderRail(); renderStats();
  } catch (e) { sec.innerHTML = `<h3>Similar roles</h3><p class="hint">Search failed: ${esc(e.message)}</p>`; }
}

/* ---------------------------------------------------------------- events */
document.addEventListener("click", async e => {
  const t = e.target.closest("[data-act],[data-view],[data-style],[data-source],[data-status],.job,.brow[data-id]");
  if (!t) return;
  if (t.dataset.view) { state.view = t.dataset.view; persist(); return renderRail(), renderList(); }
  if (t.dataset.style) { const s = t.dataset.style; state.styles.has(s) ? state.styles.delete(s) : state.styles.add(s); return renderRail(), renderList(); }
  if (t.dataset.source) { const s = t.dataset.source; state.sources.has(s) ? state.sources.delete(s) : state.sources.add(s); return renderRail(), renderList(); }
  if (t.dataset.status && state.selected) { const s = t.dataset.status; return setStatus(state.selected, s); }
  const act = t.dataset.act;
  const row = t.closest(".job");
  if (act === "apply") {
    if (row) { const j = state.jobs.find(x => x.id === row.dataset.id); if (j && ["new", "discovered"].includes(j.status)) setTimeout(() => toast("Did you apply?", {action: "Mark applied", ms: 8000, onAction: () => setStatus(j.id, "applied")}), 600); }
    return;
  }
  if (act && row) {
    e.preventDefault(); e.stopPropagation();
    const j = state.jobs.find(x => x.id === row.dataset.id);
    if (act === "save") return setStatus(j.id, j.status === "saved" ? "new" : "saved");
    if (act === "applied") return setStatus(j.id, "applied");
    if (act === "hide") return setStatus(j.id, j.status === "hidden" ? "new" : "hidden");
  }
  if (act === "close") return closeDrawer();
  if (act === "settings") return openSettings();
  if (act === "connect") return openConnect();
  if (act === "find") return openFind();
  if (act === "demo") return loadDemo();
  if (act === "clear") { state.q = ""; $("#q").value = ""; state.styles.clear(); state.sources.clear(); state.minPay = 0; $("#minPay").value = 0; $("#payOut").textContent = "Any";
    state.noCL = state.noRef = state.hasPay = false; ["#fNoCL", "#fNoRef", "#fHasPay"].forEach(s => $(s).checked = false); return renderRail(), renderList(); }
  const j = state.jobs.find(x => x.id === state.selected);
  if (act === "similar" && j) return similarFor(j);
  if (act === "seeweb") { state.view = "discovered"; closeDrawer(); return renderRail(), renderList(); }
  if (act === "more") { $("#desc").classList.add("full"); t.remove(); return; }
  if (act === "copy" && j) { navigator.clipboard?.writeText(j.apply_url || j.url); return toast("Apply link copied"); }
  if (act === "refresh" && j) {
    t.classList.add("spinning"); t.disabled = true;
    try { const nj = await api(`/api/jobs/${encodeURIComponent(j.id)}/refresh`, {method: "POST"}); Object.assign(j, nj); render(); toast(nj.enrich_status === "ok" ? "Posting re-read" : `Couldn't open posting (${nj.enrich_status})`, {bad: nj.enrich_status !== "ok"}); }
    catch (err) { toast(err.message, {bad: true}); }
    return;
  }
  const open = t.closest(".job,.brow[data-id]");
  if (open && !e.target.closest("a,button")) openDrawer(open.dataset.id);
});

document.addEventListener("keydown", e => {
  if (e.key === "Escape" && state.selected && !$("dialog[open]")) closeDrawer();
  if (e.key === "Enter" && e.target.matches(".job,.brow[data-id]")) openDrawer(e.target.dataset.id);
  if (e.key === "/" && !e.target.matches("input,textarea")) { e.preventDefault(); $("#q").focus(); }
});
$("#scrim").onclick = closeDrawer;
document.addEventListener("change", e => {
  if (e.target.dataset.req && state.selected) {
    const key = "dispatch.reqs." + state.selected;
    let d = {}; try { d = JSON.parse(localStorage.getItem(key) || "{}"); } catch {}
    d[e.target.dataset.req] = e.target.checked;
    try { localStorage.setItem(key, JSON.stringify(d)); } catch {}
    e.target.closest(".req").classList.toggle("ok", e.target.checked);
  }
});
let notesTimer;
document.addEventListener("input", e => {
  if (e.target.id === "notes" && state.selected) {
    const id = state.selected, val = e.target.value;
    const j = state.jobs.find(x => x.id === id); if (j) j.notes = val;
    clearTimeout(notesTimer);
    notesTimer = setTimeout(() => api(`/api/jobs/${encodeURIComponent(id)}`, {method: "PATCH", body: {notes: val}}), 500);
  }
});
$("#q").addEventListener("input", e => { state.q = e.target.value; renderList(); });
$("#sort").addEventListener("change", e => { state.sort = e.target.value; persist(); renderList(); });
$("#minPay").addEventListener("input", e => { state.minPay = +e.target.value; $("#payOut").textContent = state.minPay ? `$${state.minPay}K+` : "Any"; renderList(); });
$("#fNoCL").onchange = e => { state.noCL = e.target.checked; renderList(); };
$("#fNoRef").onchange = e => { state.noRef = e.target.checked; renderList(); };
$("#fHasPay").onchange = e => { state.hasPay = e.target.checked; renderList(); };
$("#btnExport").onclick = () => location.href = (window.currentView === "apps" || window.currentView === "insights") ? "/api/applications/export.xlsx" : "/api/export.csv";
$("#btnSettings").onclick = () => openSettings();
$("#btnFind").onclick = () => openFind();

/* ---------------------------------------------------------------- sync */
let pollTimer;
$("#btnSync").onclick = async () => {
  try {
    const d = await api("/api/sync", {method: "POST", body: {}});
    state.sync = d.sync; renderSync();
    if (!d.sync.running && d.sync.error) { if (/^CONNECT:/.test(d.sync.error)) return openConnect(); toast(d.sync.error, {bad: true, ms: 7000}); if (/password|sign-in/i.test(d.sync.error)) openConnect(); return; }
    poll();
  } catch (e) { toast(e.message, {bad: true}); }
};
function poll() {
  clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    const s = await api("/api/sync").catch(() => null);
    if (!s) return;
    state.sync = s; renderSync();
    if (!s.running) {
      clearInterval(pollTimer);
      await load();
      if (s.error) { if (/^CONNECT:/.test(s.error)) openConnect(); else { toast(s.error, {bad: true, ms: 7000}); if (/password|sign-in/i.test(s.error)) openConnect(); } }
      else toast([s.new ? `${s.new} new posting${s.new > 1 ? "s" : ""} arrived` : "No new postings", s.updates ? `${s.updates} application update${s.updates > 1 ? "s" : ""}` : ""].filter(Boolean).join(" · "));
      window.onSyncDone && window.onSyncDone(s);
      if (s.new && state.view !== "new") { state.view = "new"; renderRail(); renderList(); }
    }
  }, 1200);
}

/* ---------------------------------------------------------------- find */
function openFind() {
  const titles = [...new Set(state.jobs.filter(j => j.origin !== "web").map(j => j.title.replace(/\s*[\(\[,–-].*$/, "").trim()))].slice(0, 6);
  $("#quickRoles").innerHTML = titles.map(t => `<button type="button" class="chip" data-q="${esc(t)}">${esc(t)}</button>`).join("");
  $$("#quickRoles .chip").forEach(c => c.onclick = () => { $("#findQ").value = c.dataset.q; });
  if (!$("#findL").value) api("/api/settings").then(d => { if (!$("#findL").value) $("#findL").value = d.settings.default_location || ""; });
  $("#findDlg").showModal();
  $("#findQ").focus();
}
$("#findForm").addEventListener("submit", async e => {
  if (e.submitter?.value !== "go") return;
  e.preventDefault();
  const btn = $("#findGo"); btn.disabled = true; btn.textContent = "Searching…";
  try {
    const d = await api("/api/discover", {method: "POST", body: {query: $("#findQ").value, location: $("#findL").value}});
    state.webMeta = d;
    $("#findDlg").close();
    await load();
    state.view = "discovered"; state.sort = "match"; renderRail(); renderList();
    toast(`${d.jobs.length} roles found on the web`);
  } catch (err) { toast(err.message, {bad: true}); }
  finally { btn.disabled = false; btn.textContent = "Search boards"; }
});

/* ---------------------------------------------------------------- connect gmail */
function openConnect() {
  const email = (state.needsConnect && state.needsConnect[0]) || $("#cEmail").value || "jordangillis74@gmail.com";
  $("#cEmail").value = email; $("#cEmailShow").textContent = $("#cEmailShow2").textContent = email;
  $("#cMsg").textContent = ""; $("#cMsg").className = "connect-msg";
  if (!$("#connectDlg").open) $("#connectDlg").showModal();
  setTimeout(() => $("#cOpen").focus(), 50);
}
$("#cEmail").addEventListener("input", e => { $("#cEmailShow").textContent = $("#cEmailShow2").textContent = e.target.value; });
$("#cOpen").addEventListener("click", () => setTimeout(() => $("#cCode").focus(), 400));
$("#cCode").addEventListener("input", e => { if (e.target.value.replace(/\s/g, "").length === 16) $("#cGo").focus(); });
$("#connectForm").addEventListener("submit", async e => {
  if (e.submitter?.value !== "go") return;
  e.preventDefault();
  const m = $("#cMsg"), b = $("#cGo");
  m.className = "connect-msg"; m.textContent = "Checking with Google…"; b.disabled = true;
  try {
    const r = await api("/api/connect", {method: "POST", body: {email: $("#cEmail").value.trim(), app_password: $("#cCode").value}});
    m.textContent = r.message; m.className = "connect-msg " + (r.ok ? "ok" : "bad");
    if (r.ok) { setTimeout(() => $("#connectDlg").close(), 1200); state.sync.running = true; renderSync(); poll(); }
  } catch (err) {
    m.className = "connect-msg bad";
    m.textContent = /404/.test(err.message)
      ? "Dispatch needs to restart to finish an update. Close this window, then open Dispatch again from the desktop icon."
      : `Something went wrong: ${err.message}. Try again in a moment.`;
  } finally { b.disabled = false; }
});

/* ---------------------------------------------------------------- settings */
const FIELDS = {sDays: "days", sStatusDays: "status_days", sAuto: "auto_sync_minutes", sSenders: "extra_senders", sFollow: "followup_days", sGhost: "ghost_days",
  sLoc: "default_location", sResume: "resume_path", sAdzId: "adzuna_app_id", sAdzKey: "adzuna_app_key", sUsaKey: "usajobs_key", sUsaEmail: "usajobs_email", sJooble: "jooble_key"};
const NUMERIC = ["days", "status_days", "auto_sync_minutes", "followup_days", "ghost_days"];
function acctRow(a = {}) {
  const row = document.createElement("div");
  row.className = "acct";
  row.innerHTML = `<label class="field"><span>Email address</span><input class="aEmail" type="email" value="${esc(a.email || "")}" placeholder="you@gmail.com" autocomplete="off"></label>
    <label class="field"><span>App password</span><input class="aPass" type="password" value="${esc(a.app_password || "")}" placeholder="16 characters" autocomplete="new-password"></label>
    <div class="acct-actions"><button type="button" class="btn btn-sm aTest">Test</button><button type="button" class="btn btn-sm btn-ghost aDel" aria-label="Remove account">Remove</button></div>
    <span class="aMsg" role="status"></span><input class="aHost" type="hidden" value="${esc(a.imap_host || "")}">`;
  $(".aDel", row).onclick = () => row.remove();
  $(".aTest", row).onclick = async () => {
    const m = $(".aMsg", row); m.className = "aMsg"; m.textContent = "Connecting…";
    const d = await api("/api/settings/test", {method: "POST", body: {email: $(".aEmail", row).value.trim(), app_password: $(".aPass", row).value, imap_host: $(".aHost", row).value}});
    m.textContent = d.message; m.className = "aMsg " + (d.ok ? "ok" : "bad");
  };
  $("#accounts").append(row);
}
$("#btnAddAcct").onclick = () => acctRow();
async function openSettings() {
  const d = await api("/api/settings");
  Object.entries(FIELDS).forEach(([id, k]) => $("#" + id).value = d.settings[k] ?? "");
  $("#accounts").innerHTML = "";
  (d.settings.accounts.length ? d.settings.accounts : [{}]).forEach(acctRow);
  $("#sStartup").checked = !!d.settings.start_with_windows;
  $("#startupRow").hidden = !d.windows;
  $("#sResumeInfo").innerHTML = d.resume.name ? `Using <strong>${esc(d.resume.name)}</strong>: ${d.resume.skills.map(esc).join(", ")}` : "No resume PDF found yet.";
  $("#sWeekly").checked = !!d.settings.weekly_report_on;
  $("#sAutoApplied").checked = d.settings.auto_mark_applied !== false;
  renderHistorySetting(d.history);
  $("#setDlg").showModal();
}
const settingsBody = () => ({
  ...Object.fromEntries(Object.entries(FIELDS).map(([id, k]) => [k, NUMERIC.includes(k) ? +$("#" + id).value : $("#" + id).value.trim()])),
  accounts: $$("#accounts .acct").map(r => ({email: $(".aEmail", r).value.trim(), app_password: $(".aPass", r).value, imap_host: $(".aHost", r).value})).filter(a => a.email),
  start_with_windows: $("#sStartup").checked,
  weekly_report_on: $("#sWeekly").checked,
  auto_mark_applied: $("#sAutoApplied").checked,
});
function renderHistorySetting(h) {
  const el = $("#sHistory");
  if (h.imported) {
    el.innerHTML = `${h.imported} past applications from <strong>${esc(h.file || "your spreadsheet")}</strong> are in Dispatch as history. Dispatch doesn't read the file anymore.
      <div class="test-row" style="margin-top:8px"><button type="button" class="btn btn-sm btn-ghost" id="btnHistRemove">Remove imported history</button></div>`;
    $("#btnHistRemove").onclick = async () => {
      const r = await api("/api/history", {method: "DELETE"});
      toast(`Removed ${r.removed} imported rows` + (r.kept ? `, kept ${r.kept} that employers emailed about` : ""));
      renderHistorySetting((await api("/api/history")));
    };
  } else if (h.available) {
    el.innerHTML = `Found <strong>${esc(h.available)}</strong> in your Employment folder. You can bring it in once so your charts include past applications. Dispatch won't read it again after that.
      <div class="test-row" style="margin-top:8px"><button type="button" class="btn btn-sm" id="btnHistImport">Import old history (one time)</button></div>`;
    $("#btnHistImport").onclick = importHistory;
  } else el.textContent = "Not using a spreadsheet. Applications come from your email and from jobs you mark applied.";
}
async function importHistory() {
  try {
    const r = await api("/api/history", {method: "POST"});
    toast(r.file ? `Imported ${r.imported} past applications from ${r.file}` : "No spreadsheet found in the Employment folder");
    if ($("#setDlg").open) renderHistorySetting(await api("/api/history"));
    window.onSyncDone && window.onSyncDone();
  } catch (err) { toast(err.message, {bad: true, ms: 7000}); }
}
$("#btnReportNow").onclick = async () => {
  const m = $("#reportMsg"); m.textContent = "Sending…";
  const r = await api("/api/report/test", {method: "POST"});
  m.textContent = r.result === "sent" ? "Sent. Check your inbox." : r.result === "no account" ? "Add an email account first." : `Not sent: ${r.result}`;
};
$("#setForm").addEventListener("submit", async e => {
  if (e.submitter?.value !== "save") return;
  e.preventDefault();
  await api("/api/settings", {method: "POST", body: settingsBody()});
  $("#setDlg").close();
  toast("Settings saved");
  await load();
});
$("#btnQuit").onclick = async () => { await api("/api/quit", {method: "POST"}).catch(() => {}); document.body.innerHTML = '<div class="empty" style="margin-top:20vh"><h3>Dispatch has stopped</h3><p>Open it again from the Dispatch icon on your desktop.</p></div>'; };
async function loadDemo() {
  await api("/api/demo", {method: "POST"});
  state.boardSig = ""; state.view = "new";
  $("#setDlg").open && $("#setDlg").close();
  await load();
  toast("Sample alerts loaded. Connect email in Settings to see your real ones.");
}
$("#btnDemo").onclick = loadDemo;
$("#btnDemoClear").onclick = async () => { await api("/api/demo", {method: "DELETE"}); state.boardSig = ""; await load(); toast("Samples removed"); };

/* ---------------------------------------------------------------- boot */
let uiVersion = null;
setInterval(() => api("/api/ping").then(p => { if (uiVersion && p.ui !== uiVersion) location.reload(); uiVersion = p.ui; }).catch(() => {}), 20000);
api("/api/ping").then(p => uiVersion = p.ui).catch(() => {});
load().then(() => { if (state.sync.running) poll(); }).catch(e => toast("Can't reach Dispatch. Is the app window still open?", {bad: true, ms: 10000}));
setInterval(() => { if (!state.sync.running && !document.hidden) api("/api/jobs").then(d => {
  const changed = d.jobs.length !== state.jobs.length || d.sync.last_ok !== state.sync.last_ok || d.sync.running !== state.sync.running;
  if (changed) { state.jobs = d.jobs; state.sync = d.sync; state.emailsRead = d.emails_read; render(); if (d.sync.running) poll(); }
}).catch(() => {}); }, 30000);
