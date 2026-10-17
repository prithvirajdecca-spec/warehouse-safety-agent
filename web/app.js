const listEl = document.getElementById("list");
const detailEl = document.getElementById("detail");
const chipsEl = document.getElementById("chips");
let events = [];
let filter = "unsafe";

const FILTERS = [
  ["unsafe", "Unsafe"],
  ["all", "All"],
  ["walkway_violation", "Walkway"],
  ["forklift_overload", "Forklift"],
  ["opened_panel_cover", "Panel"],
  ["parcel_handling", "Parcel"],
];

function matches(e) {
  if (filter === "all") return true;
  if (filter === "unsafe") return e.behavior_type === "unsafe";
  return e.class_id === filter;
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
  document.querySelectorAll(".row").forEach((r) => r.classList.toggle("selected", r.dataset.id === e.id));
  const match =
    e.label_match == null ? "" : e.label_match ? "Label match: yes" : "Label match: no";
  detailEl.innerHTML = `
    <p class="sev">${e.severity.toUpperCase()} · ${e.behavior_type}</p>
    <h2>${e.class_label}</h2>
    <p class="meta">${e.location} · ${e.camera_id} · ${match}</p>
    <p class="action"><strong>Action:</strong> ${e.action}</p>
    <p class="caption">${e.caption}</p>
    <p class="meta">VAST search · Cosmos caption · W&amp;B class (wire live next)</p>
  `;
}

function render() {
  renderChips();
  const rows = events.filter(matches);
  listEl.innerHTML = rows
    .map(
      (e) => `
    <article class="row" data-id="${e.id}">
      <div class="sev">${e.severity}</div>
      <h2>${e.class_label}</h2>
      <div class="meta">${e.location} · ${e.camera_id}</div>
    </article>`
    )
    .join("");
  listEl.querySelectorAll(".row").forEach((row) => {
    row.onclick = () => showDetail(events.find((e) => e.id === row.dataset.id));
  });
  if (rows[0]) showDetail(rows[0]);
}

fetch("/events")
  .then((r) => r.json())
  .then((data) => {
    events = data.events || [];
    render();
  })
  .catch(() => {
    listEl.innerHTML = "<p class='empty'>Could not load /events</p>";
  });
