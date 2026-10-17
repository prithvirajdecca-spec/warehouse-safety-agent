const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");
const chipsEl = document.getElementById("chips");
const bannerEl = document.getElementById("banner");
const sponsorsEl = document.getElementById("sponsors");

let events = [];
let filter = "unsafe";
let selectedId = null;

const FILTERS = [
  ["unsafe", "Unsafe"],
  ["all", "All"],
  ["walkway_violation", "Walkway"],
  ["forklift_overload", "Forklift"],
  ["opened_panel_cover", "Panel"],
  ["unauthorized_intervention", "Vest"],
  ["parcel_handling", "Parcel"],
];

function matches(e) {
  if (filter === "all") return true;
  if (filter === "unsafe") return e.behavior_type === "unsafe";
  return e.class_id === filter;
}

function renderSponsors(s) {
  const flags = s || {};
  sponsorsEl.innerHTML = [
    ["VAST", flags.vast],
    ["Cosmos", flags.cosmos],
    ["W&B", flags.wandb],
  ]
    .map(([n, on]) => `<span class="pill ${on ? "on" : ""}">${n}</span>`)
    .join("");
}

function renderChips() {
  chipsEl.innerHTML = FILTERS.map(
    ([id, label]) =>
      `<button class="chip ${filter === id ? "active" : ""}" data-id="${id}">${label}</button>`
  ).join("");
  chipsEl.querySelectorAll(".chip").forEach((b) => {
    b.onclick = () => {
      filter = b.dataset.id;
      render();
    };
  });
}

function showDetail(e) {
  selectedId = e.id;
  document.querySelectorAll(".row").forEach((r) => r.classList.toggle("selected", r.dataset.id === e.id));
  const src = e.source ? `/clip?source=${encodeURIComponent(e.source)}` : "";
  const match =
    e.label_match == null
      ? ""
      : `<span class="${e.label_match ? "match" : "nomatch"}">${
          e.label_match ? "Agrees with ingest label" : "Differs from ingest label"
        }</span>`;
  const video = src
    ? `<video controls playsinline src="${src}"></video>`
    : `<p class="empty">Clip URL not in this event yet (sample mode or still indexing).</p>`;
  detailEl.innerHTML = `
    ${video}
    <p class="sev ${e.severity}">${e.severity} · ${e.behavior_type}</p>
    <h2>${e.class_label}</h2>
    <p class="meta">${e.location} · ${e.camera_id} · conf ${e.confidence ?? "—"} · ${match}</p>
    <p class="action"><strong>Action</strong> — ${e.action}</p>
    <p class="caption"><strong>Cosmos</strong> — ${e.caption || "No caption"}</p>
  `;
}

function render() {
  renderChips();
  const rows = events.filter(matches);
  listEl.innerHTML = rows.length
    ? rows
        .map(
          (e) => `
    <article class="row" data-id="${e.id}">
      <div class="sev ${e.severity}">${e.severity}</div>
      <h2>${e.class_label}</h2>
      <div class="meta">${e.location} · ${e.camera_id}</div>
    </article>`
        )
        .join("")
    : `<p class="empty" style="padding:1rem">No events in this filter.</p>`;
  listEl.querySelectorAll(".row").forEach((row) => {
    row.onclick = () => showDetail(events.find((e) => e.id === row.dataset.id));
  });
  const pick = rows.find((e) => e.id === selectedId) || rows[0];
  if (pick) showDetail(pick);
}

fetch("/events")
  .then((r) => r.json())
  .then((data) => {
    events = data.events || [];
    renderSponsors(data.sponsors);
    const src = data.source || "unknown";
    const parcel = data.parcel_ready ? "parcel clip indexed" : "parcel clip still indexing";
    bannerEl.textContent = `${events.length} events · source ${src} · ${parcel}`;
    render();
  })
  .catch(() => {
    listEl.innerHTML = "<p class='empty'>Could not load /events</p>";
  });
