const viewEl = document.getElementById("view");
const navEl = document.getElementById("nav");
const periodEl = document.getElementById("period");
const titleEl = document.getElementById("view-title");
const subEl = document.getElementById("view-sub");
const sponsorsEl = document.getElementById("sponsors");
const sideStatusEl = document.getElementById("side-status");
const drawerEl = document.getElementById("drawer");

const PERIODS = [
  ["24h", "24 hours"],
  ["7d", "7 days"],
  ["30d", "30 days"],
  ["90d", "90 days"],
];
const NAV = [
  ["dashboard", "Overview"],
  ["incidents", "Incidents"],
  ["investigations", "Investigations"],
  ["team", "Team"],
];
const CLASS_FILTERS = [
  ["unsafe", "Unsafe"],
  ["all", "All"],
  ["walkway_violation", "Walkway"],
  ["forklift_overload", "Forklift"],
  ["opened_panel_cover", "Panel"],
  ["unauthorized_intervention", "Vest"],
  ["parcel_handling", "Parcel"],
];
const STATUSES = [
  ["unassigned", "Needs assignment"],
  ["pending", "Pending"],
  ["investigating", "Under investigation"],
  ["closed", "Closed"],
];
const SEVERITIES = ["severe", "high", "medium", "low"];
const CLASS_SEVERITY = {
  forklift_overload: "severe",
  opened_panel_cover: "severe",
  unauthorized_intervention: "high",
  walkway_violation: "high",
  parcel_handling: "medium",
  safe_walkway: "low",
  authorized_intervention: "low",
  closed_panel_cover: "low",
  safe_carrying: "low",
};

let events = [];
let people = [];
let assignments = {};
let meta = { source: "", parcel_ready: false, sponsors: {} };
let view = "dashboard";
let period = "7d";
let classFilter = "unsafe";
let statusFilter = "any";
let severityFilter = "any";
let labelReview = null;
let selectedId = null;
let assignmentStore = "file";

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function toast(msg) {
  const el = document.getElementById("toast");
  el.hidden = false;
  el.textContent = msg;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 2400);
}

function prepare(e) {
  const m = String(e.source || e.original_video || "").match(/(20\d{6})_(\d{6})/);
  if (!e.flagged_at && m) {
    const d = m[1];
    const t = m[2];
    e.flagged_at = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}T${t.slice(0, 2)}:${t.slice(2, 4)}:${t.slice(4, 6)}Z`;
  }
  if (CLASS_SEVERITY[e.class_id]) e.severity = CLASS_SEVERITY[e.class_id];
  return e;
}

function inPeriod(e) {
  const t = Date.parse(e.flagged_at || "");
  if (Number.isNaN(t)) return true;
  const ms = period === "24h" ? 86400000 : { "7d": 7, "30d": 30, "90d": 90 }[period] * 86400000;
  return t >= Date.now() - ms;
}

function recOf(e) {
  return assignments[e.id] || { status: "unassigned", assignee_id: null };
}

function personName(id) {
  const p = people.find((x) => x.id === id);
  return p ? p.name : "Unassigned";
}

function caseNo(id) {
  let h = 0;
  for (const c of String(id)) h = (Math.imul(h, 31) + c.charCodeAt(0)) >>> 0;
  return `INC-${(h % 9000) + 1000}`;
}

function fmtWhen(iso) {
  const d = new Date(iso || "");
  if (Number.isNaN(d.getTime())) return "Time unknown";
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function periodLabel() {
  return PERIODS.find((p) => p[0] === period)[1];
}

function flagged() {
  return events.filter((e) => e.behavior_type === "unsafe" && inPeriod(e));
}

function statusLabel(status) {
  return (STATUSES.find((s) => s[0] === status) || ["", status])[1];
}

function isWalkway(e) {
  return e.class_id === "walkway_violation" || e.class_id === "safe_walkway" || e.label_from_filename === "walkway_violation";
}

function matchesIncident(e) {
  if (!inPeriod(e)) return false;
  if (labelReview && e.label_from_filename !== labelReview) return false;
  if (classFilter === "walkway_violation" && !isWalkway(e)) return false;
  else if (classFilter === "unsafe" && e.behavior_type !== "unsafe") return false;
  else if (classFilter !== "unsafe" && classFilter !== "all" && classFilter !== "walkway_violation" && e.class_id !== classFilter) return false;
  if (statusFilter !== "any" && recOf(e).status !== statusFilter) return false;
  if (severityFilter !== "any" && e.severity !== severityFilter) return false;
  return true;
}

function batchNote() {
  const times = events.map((e) => Date.parse(e.flagged_at || "")).filter((t) => !Number.isNaN(t));
  if (!times.length) return "";
  const min = new Date(Math.min(...times));
  const max = new Date(Math.max(...times));
  const when = min.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  if (min.toDateString() === max.toDateString()) {
    return `Indexed ${when}. The 24-hour, week, and month filters include this same batch.`;
  }
  return `Indexed ${when} – ${max.toLocaleDateString(undefined, { month: "short", day: "numeric" })}.`;
}

function renderSponsors() {
  const flags = meta.sponsors || {};
  sponsorsEl.innerHTML = [["VAST", flags.vast], ["Cosmos", flags.cosmos], ["W&B", flags.wandb]]
    .map(([n, on]) => `<span class="pill ${on ? "on" : ""}">${n}</span>`)
    .join("");
}

function renderChrome() {
  const open = flagged().filter((e) => recOf(e).status === "unassigned").length;
  navEl.innerHTML = NAV.map(([id, label]) => {
    const badge = id === "investigations" && open ? `<span class="badge">${open}</span>` : "";
    return `<button type="button" class="nav-btn ${view === id ? "active" : ""}" data-nav="${id}">${label}${badge}</button>`;
  }).join("");
  periodEl.innerHTML = PERIODS.map(
    ([id, label]) => `<button type="button" data-period="${id}" class="${period === id ? "active" : ""}">${label}</button>`
  ).join("");
  const titles = {
    dashboard: ["Overview", `Safety incidents flagged in the last ${periodLabel()}`],
    incidents: ["Incidents", "Clip, caption, and owner for each flagged event"],
    investigations: ["Investigations", "Who is working which case"],
    team: ["Team", "Open caseload by investigator"],
  };
  titleEl.textContent = titles[view][0];
  subEl.textContent = titles[view][1];
  const src = meta.source === "vss" ? "live index" : meta.source || "loading";
  const parcel = meta.parcel_ready ? "parcel clip indexed" : "parcel clip still indexing";
  sideStatusEl.textContent = `${flagged().length} flagged · ${periodLabel()} · ${src} · ${parcel}`;
  renderSponsors();
}

function kpi(label, num, hint, status) {
  return `<button type="button" class="card kpi" data-jump="${esc(status)}">
    <div class="label">${esc(label)}</div>
    <div class="num">${num}</div>
    <div class="hint">${esc(hint)}</div>
  </button>`;
}

function labelLine() {
  const labeled = events.filter((e) => e.label_from_filename && inPeriod(e));
  const agreed = labeled.filter((e) => e.label_match === true).length;
  const conflicts = events.filter((e) => e.label_from_filename === "walkway_violation" && e.class_id !== "walkway_violation" && inPeriod(e));
  const agree = labeled.length ? `Ingest labels agree on ${agreed} of ${labeled.length} labeled clips.` : "";
  const review = conflicts.length
    ? `<button type="button" class="btn" data-review="walkway_violation">${conflicts.length} walkway clips: dataset says violation, Cosmos says on the path</button>`
    : "";
  if (!agree && !review) return "";
  return `<p class="muted" style="margin:0.45rem 0 0;display:flex;gap:0.6rem;align-items:center;flex-wrap:wrap">${esc(agree)} ${review}</p>`;
}

function renderDashboard() {
  const rows = flagged();
  const count = (status) => rows.filter((e) => recOf(e).status === status).length;
  const bySev = Object.fromEntries(SEVERITIES.map((s) => [s, rows.filter((e) => e.severity === s).length]));
  const max = Math.max(1, ...Object.values(bySev));
  const workload = people.map((p) => {
    const mine = rows.filter((e) => recOf(e).assignee_id === p.id && recOf(e).status !== "closed");
    return { p, mine };
  });
  const recent = [...rows].sort((a, b) => Date.parse(b.flagged_at || 0) - Date.parse(a.flagged_at || 0)).slice(0, 8);
  viewEl.innerHTML = `
    <div class="kpis">
      ${kpi("Flagged", rows.length, `Unsafe incidents · last ${periodLabel()}`, "flagged")}
      ${kpi("Needs assignment", count("unassigned"), "No investigator yet", "unassigned")}
      ${kpi("Under investigation", count("investigating"), "Owner is reviewing", "investigating")}
      ${kpi("Pending", count("pending"), "Assigned, not started", "pending")}
    </div>
    <p class="muted" style="margin:0.7rem 0 0">Closed this period: ${count("closed")}. Flagged = needs assignment + pending + under investigation + closed. ${esc(batchNote())}</p>
    ${labelLine()}
    <div class="grid-2">
      <section class="card">
        <h2 class="section-title">By severity</h2>
        ${SEVERITIES.map((s) => `
          <div class="bucket">
            <button type="button" class="sev ${s}" data-severity="${s}">${s}</button>
            <div class="bar ${s}"><span style="width:${Math.round((bySev[s] / max) * 100)}%"></span></div>
            <strong>${bySev[s]}</strong>
          </div>`).join("")}
      </section>
      <section class="card">
        <h2 class="section-title">Open caseload</h2>
        ${workload.map(({ p, mine }) => `
          <div class="person">
            <div><strong>${esc(p.name)}</strong><div class="muted">${esc(p.role)} · ${esc(p.shift)}</div></div>
            <div>${mine.length}</div>
          </div>`).join("") || `<p class="empty">No investigators loaded.</p>`}
      </section>
    </div>
    <section class="card" style="margin-top:0.75rem">
      <h2 class="section-title">Recent incidents</h2>
      ${recent.length ? `<table class="table"><thead><tr><th>Case</th><th>Incident</th><th>When</th><th>Owner</th><th>Status</th></tr></thead><tbody>
        ${recent.map((e) => {
          const rec = recOf(e);
          return `<tr class="row-btn" data-open="${esc(e.id)}" style="cursor:pointer">
            <td>${caseNo(e.id)}</td>
            <td><strong>${esc(e.class_label)}</strong><div class="sev ${esc(e.severity)}">${esc(e.severity)}</div></td>
            <td>${esc(fmtWhen(e.flagged_at))}</td>
            <td>${esc(personName(rec.assignee_id))}</td>
            <td><span class="status ${esc(rec.status)}">${esc(statusLabel(rec.status))}</span></td>
          </tr>`;
        }).join("")}
      </tbody></table>` : `<p class="empty">No unsafe incidents in this period.</p>`}
    </section>`;
}

function renderIncidents() {
  const rows = events.filter(matchesIncident);
  viewEl.innerHTML = `
    <div class="filters" id="class-filters">
      ${CLASS_FILTERS.map(([id, label]) => `<button type="button" class="chip ${classFilter === id ? "active" : ""}" data-class="${id}">${label}</button>`).join("")}
    </div>
    <div class="filters" id="status-filters">
      <button type="button" class="chip ${statusFilter === "any" ? "active" : ""}" data-status="any">Any status</button>
      ${STATUSES.map(([id, label]) => `<button type="button" class="chip ${statusFilter === id ? "active" : ""}" data-status="${id}">${label}</button>`).join("")}
      ${severityFilter !== "any" ? `<button type="button" class="chip active" data-severity-clear="1">Severity: ${esc(severityFilter)} ×</button>` : ""}
      ${labelReview ? `<button type="button" class="chip active" data-review-clear="1">Dataset walkway label ×</button>` : ""}
    </div>
    <section class="card">
      ${rows.length ? rows.map((e) => {
        const rec = recOf(e);
        return `<button type="button" class="row-btn" data-open="${esc(e.id)}" style="border-bottom:1px solid var(--line)">
          <div style="display:flex;justify-content:space-between;gap:0.6rem;padding:0.7rem 0.2rem">
            <div>
              <div class="sev ${esc(e.severity)}">${esc(e.severity)} · ${caseNo(e.id)}</div>
              <strong>${esc(e.class_label)}</strong>
              <div class="meta">${esc(e.location)} · ${esc(e.camera_id)} · ${esc(fmtWhen(e.flagged_at))}</div>
            </div>
            <div style="text-align:right">
              <span class="status ${esc(rec.status)}">${esc(statusLabel(rec.status))}</span>
              <div class="meta">${esc(personName(rec.assignee_id))}</div>
            </div>
          </div>
        </button>`;
      }).join("") : `<p class="empty">No incidents in this filter.</p>`}
    </section>`;
}

function ticket(e) {
  const rec = recOf(e);
  const selected = e.id === selectedId ? "selected" : "";
  return `<button type="button" class="ticket ${selected}" data-open="${esc(e.id)}">
    <div class="sev ${esc(e.severity)}">${esc(e.severity)} · ${caseNo(e.id)}</div>
    <h3>${esc(e.class_label)}</h3>
    <div class="meta">${esc(fmtWhen(e.flagged_at))} · ${esc(personName(rec.assignee_id))}</div>
  </button>`;
}

function renderInvestigations() {
  const rows = flagged();
  viewEl.innerHTML = `<div class="board">${STATUSES.map(([id, label]) => {
    const items = rows.filter((e) => recOf(e).status === id);
    return `<section>
      <h2 class="col-h">${esc(label)} <span class="muted">${items.length}</span></h2>
      ${items.map(ticket).join("") || `<p class="empty">None</p>`}
    </section>`;
  }).join("")}</div>`;
}

function renderTeam() {
  const rows = flagged();
  viewEl.innerHTML = `<div class="team-grid">${people.map((p) => {
    const mine = rows.filter((e) => recOf(e).assignee_id === p.id && recOf(e).status !== "closed");
    return `<section class="card">
      <strong>${esc(p.name)}</strong>
      <div class="meta">${esc(p.role)} · ${esc(p.shift)} · ${mine.length} open</div>
      ${mine.map((e) => `<div class="mini"><button type="button" data-open="${esc(e.id)}">
        <strong>${esc(e.class_label)}</strong>
        <div class="meta">${caseNo(e.id)} · ${esc(statusLabel(recOf(e).status))} · ${esc(e.severity)}</div>
      </button></div>`).join("") || `<p class="empty">No open investigations in this period.</p>`}
    </section>`;
  }).join("") || `<p class="empty">Team list did not load.</p>`}</div>`;
}

function caseMetaHtml(e) {
  const rec = recOf(e);
  const match = e.label_match == null ? "" : `<span class="${e.label_match ? "match" : "nomatch"}">${e.label_match ? "Agrees with ingest label" : "Differs from ingest label"}</span>`;
  const options = [`<option value="">Unassigned</option>`]
    .concat(people.map((p) => `<option value="${esc(p.id)}" ${rec.assignee_id === p.id ? "selected" : ""}>${esc(p.name)}</option>`))
    .join("");
  const statusOpts = STATUSES.map(([id, label]) => `<option value="${id}" ${rec.status === id ? "selected" : ""}>${esc(label)}</option>`).join("");
  return `
    <p class="sev ${esc(e.severity)}">${esc(e.severity)} · ${esc(e.behavior_type)}</p>
    <h2 style="margin:0.2rem 0">${esc(e.class_label)}</h2>
    <p class="meta">${caseNo(e.id)} · ${esc(e.location)} · ${esc(e.camera_id)} · indexed ${esc(fmtWhen(e.flagged_at))} · conf ${esc(e.confidence ?? "—")} · ${match}</p>
    <p class="reason"><strong>Why</strong> — ${esc(e.reason || "No reason recorded")}</p>
    <p class="action"><strong>Action</strong> — ${esc(e.action)}</p>
    <p class="caption"><strong>Cosmos</strong> — ${esc(e.caption || "No caption")}</p>
    <form class="form" id="assign-form">
      <label>Investigator<select name="assignee_id">${options}</select></label>
      <label>Status<select name="status">${statusOpts}</select></label>
      <button class="btn-primary" type="submit">Save assignment</button>
    </form>`;
}

function openCase(id) {
  const e = events.find((x) => x.id === id);
  if (!e) return;
  selectedId = id;
  const same = drawerEl.getAttribute("data-case-id") === id && drawerEl.querySelector(".case-meta");
  drawerEl.hidden = false;
  document.body.classList.add("case-open");
  if (!same) {
    const src = e.source ? `clip?source=${encodeURIComponent(e.source)}` : "";
    const video = src
      ? `<div class="stage"><video controls playsinline src="${esc(src)}"></video><canvas></canvas></div><p class="meta yolo-note">YOLO boxes follow the clip: person, truck, suitcase.</p>`
      : `<p class="empty novideo">Clip URL is not on this event yet.</p>`;
    drawerEl.setAttribute("data-case-id", id);
    drawerEl.innerHTML = `
      <div class="drawer-top"><strong>${caseNo(e.id)}</strong><button type="button" class="btn" data-close-case>Close</button></div>
      ${video}
      <div class="case-meta">${caseMetaHtml(e)}</div>`;
    const vid = drawerEl.querySelector("video");
    if (vid && e.source) attachDetections(vid, e.source);
  } else {
    drawerEl.querySelector(".case-meta").innerHTML = caseMetaHtml(e);
  }
  document.querySelectorAll(".ticket, .row-btn").forEach((el) => {
    el.classList.toggle("selected", el.getAttribute("data-open") === id);
  });
}

function drawBoxes(video) {
  const canvas = video.parentElement && video.parentElement.querySelector("canvas");
  const frames = video._frames || [];
  if (!canvas || !frames.length) return;
  const width = video._frameW || video.videoWidth || 1;
  const height = video._frameH || video.videoHeight || 1;
  const box = video.getBoundingClientRect();
  canvas.width = Math.max(1, Math.round(box.width));
  canvas.height = Math.max(1, Math.round(box.height));
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  let frame = frames[0];
  for (const f of frames) if (f.t <= video.currentTime + 0.08) frame = f;
  const sx = canvas.width / width;
  const sy = canvas.height / height;
  for (const b of frame.boxes || []) {
    ctx.strokeStyle = b.label === "person" ? "#0f6e8c" : "#c2410c";
    ctx.lineWidth = 2;
    ctx.strokeRect(b.x * sx, b.y * sy, b.w * sx, b.h * sy);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.font = "12px sans-serif";
    ctx.fillText(`${b.label} ${b.conf}`, b.x * sx, Math.max(12, b.y * sy - 3));
  }
}

function attachDetections(video, source) {
  video.addEventListener("timeupdate", () => drawBoxes(video));
  video.addEventListener("loadeddata", () => drawBoxes(video));
  fetch(`detections?source=${encodeURIComponent(source)}`)
    .then((r) => r.json())
    .then((data) => {
      video._frames = data.frames || [];
      video._frameW = data.width;
      video._frameH = data.height;
      const note = video.parentElement && video.parentElement.parentElement.querySelector(".yolo-note");
      if (note) note.textContent = video._frames.length ? "YOLO boxes follow the clip: person, truck, suitcase." : "No YOLO boxes for this clip.";
      drawBoxes(video);
    })
    .catch(() => {});
}

function closeCase() {
  selectedId = null;
  drawerEl.hidden = true;
  drawerEl.removeAttribute("data-case-id");
  drawerEl.innerHTML = "";
  document.body.classList.remove("case-open");
}

function render() {
  renderChrome();
  if (view === "dashboard") renderDashboard();
  else if (view === "incidents") renderIncidents();
  else if (view === "investigations") renderInvestigations();
  else renderTeam();
  if (selectedId) openCase(selectedId);
}

function jump(status) {
  view = "incidents";
  classFilter = "unsafe";
  severityFilter = "any";
  labelReview = null;
  statusFilter = status === "flagged" ? "any" : status;
  render();
}

async function saveAssignment(form) {
  const e = events.find((x) => x.id === selectedId);
  if (!e) return;
  const assignee = form.assignee_id.value || null;
  let status = form.status.value;
  if (!assignee) status = "unassigned";
  else if (status === "unassigned") status = "pending";
  const res = await fetch("assignments", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_id: e.id, assignee_id: assignee, status }),
  });
  if (!res.ok) {
    toast("Could not save assignment");
    return;
  }
  const data = await res.json();
  assignments[e.id] = data.assignment;
  if (data.store) assignmentStore = data.store;
  const where = assignmentStore === "vastdb" ? "Saved in VastDB" : "Saved on this server";
  toast(assignee ? `${where} · ${personName(assignee)}` : "Assignment cleared");
  render();
}

async function load(refresh) {
  viewEl.innerHTML = `<p class="empty">Loading incidents…</p>`;
  const q = refresh ? "?refresh=1" : "";
  const [evRes, teamRes, asRes] = await Promise.all([
    fetch(`events${q}`),
    fetch("team"),
    fetch("assignments"),
  ]);
  if (!evRes.ok) throw new Error("events");
  const ev = await evRes.json();
  events = (ev.events || []).map(prepare);
  meta = { source: ev.source, parcel_ready: ev.parcel_ready, sponsors: ev.sponsors || {} };
  if (teamRes.ok) people = (await teamRes.json()).people || [];
  if (asRes.ok) {
    const asg = await asRes.json();
    assignments = asg.assignments || {};
    assignmentStore = asg.store || "file";
  }
  render();
}

document.body.addEventListener("click", (ev) => {
  const nav = ev.target.closest("[data-nav]");
  if (nav) { view = nav.dataset.nav; render(); return; }
  const per = ev.target.closest("[data-period]");
  if (per) { period = per.dataset.period; render(); return; }
  const jumpBtn = ev.target.closest("[data-jump]");
  if (jumpBtn) { jump(jumpBtn.dataset.jump); return; }
  const sev = ev.target.closest("[data-severity]");
  if (sev) {
    view = "incidents";
    classFilter = "unsafe";
    statusFilter = "any";
    labelReview = null;
    severityFilter = sev.dataset.severity;
    render();
    return;
  }
  const review = ev.target.closest("[data-review]");
  if (review) {
    view = "incidents";
    classFilter = "all";
    statusFilter = "any";
    severityFilter = "any";
    labelReview = review.dataset.review;
    render();
    return;
  }
  if (ev.target.closest("[data-severity-clear]")) { severityFilter = "any"; render(); return; }
  if (ev.target.closest("[data-review-clear]")) { labelReview = null; render(); return; }
  const cls = ev.target.closest("[data-class]");
  if (cls) { classFilter = cls.dataset.class; labelReview = null; render(); return; }
  const st = ev.target.closest("[data-status]");
  if (st) { statusFilter = st.dataset.status; render(); return; }
  const open = ev.target.closest("[data-open]");
  if (open) { openCase(open.getAttribute("data-open")); return; }
  if (ev.target.closest("[data-close-case]")) { closeCase(); }
});

document.body.addEventListener("submit", (ev) => {
  if (ev.target.id !== "assign-form") return;
  ev.preventDefault();
  saveAssignment(ev.target);
});

document.getElementById("refresh").onclick = () => {
  load(true).catch(() => { viewEl.innerHTML = `<p class="empty">Could not refresh incidents.</p>`; });
};

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") closeCase();
});

load(false).catch(() => {
  viewEl.innerHTML = `<p class="empty">Could not load /events. Restart the app from the app folder and refresh.</p>`;
});
