const API = "/api";

let shipments = [];
let statuses = [];
let selectedId = null;

const $ = (sel) => document.querySelector(sel);

async function api(path, opts = {}) {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  let data = {};
  try {
    data = await res.json();
  } catch (parseErr) {
    if (res.ok) console.warn(`Failed to parse JSON response for ${path}:`, parseErr);
  }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

function showToast(message, isError = false) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.className = isError ? "toast error" : "toast";
  toast.classList.remove("hidden");
  setTimeout(() => toast.classList.add("hidden"), 3000);
}

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString();
}

function statusClass(status) {
  return `status-badge status-${status}`;
}

async function loadStatuses() {
  statuses = await api("/statuses");
  const filterSelect = $("#status-filter");
  const eventSelect = $("#event-status");
  statuses.forEach((s) => {
    const opt1 = document.createElement("option");
    opt1.value = s.value;
    opt1.textContent = s.label;
    filterSelect.appendChild(opt1);

    const opt2 = document.createElement("option");
    opt2.value = s.value;
    opt2.textContent = s.label;
    eventSelect.appendChild(opt2);
  });
}

async function loadShipments() {
  const params = new URLSearchParams();
  const search = $("#search-input").value.trim();
  const status = $("#status-filter").value;
  if (search) params.set("search", search);
  if (status) params.set("status", status);

  shipments = await api(`/shipments?${params.toString()}`);
  renderShipments();
}

function renderShipments() {
  const list = $("#shipment-list");
  if (!shipments.length) {
    list.innerHTML = `<p class="empty empty-padded">No shipments found</p>`;
    return;
  }
  list.innerHTML = shipments
    .map(
      (s) => `
    <div class="shipment-card ${s.id === selectedId ? "selected" : ""}" data-id="${s.id}">
      <div class="awb">${s.awb_number}</div>
      <div class="route">${s.origin_airport} → ${s.destination_airport} · ${s.status_label}</div>
    </div>
  `
    )
    .join("");

  list.querySelectorAll(".shipment-card").forEach((el) => {
    el.addEventListener("click", () => selectShipment(Number(el.dataset.id)));
  });
}

function selectShipment(id) {
  selectedId = id;
  renderShipments();
  const s = shipments.find((x) => x.id === id);
  if (!s) return;

  $("#detail-empty").classList.add("hidden");
  $("#detail-content").classList.remove("hidden");
  $("#detail-awb").textContent = s.awb_number;
  const statusEl = $("#detail-status");
  statusEl.textContent = s.status_label;
  statusEl.className = statusClass(s.status);

  $("#detail-meta").innerHTML = `
    <div class="meta-item"><label>Carrier</label>${s.carrier_name}</div>
    <div class="meta-item"><label>Route</label>${s.origin_airport} → ${s.destination_airport}</div>
    <div class="meta-item"><label>Shipper</label>${s.shipper}</div>
    <div class="meta-item"><label>Consignee</label>${s.consignee}</div>
    <div class="meta-item"><label>Cargo</label>${s.pieces} pcs / ${s.weight_kg} kg</div>
    <div class="meta-item"><label>Commodity</label>${s.commodity || "—"}</div>
    <div class="meta-item"><label>Flight</label>${s.flight_number || "—"}</div>
    <div class="meta-item"><label>Reference</label>${s.reference || "—"}</div>
  `;

  const timeline = $("#timeline");
  if (!s.events.length) {
    timeline.innerHTML = `<p class="empty">No tracking events yet</p>`;
    return;
  }
  timeline.innerHTML = s.events
    .map(
      (e) => `
    <div class="timeline-item">
      <div class="timeline-dot"></div>
      <div class="timeline-body">
        <div class="timeline-status">${e.status_label}</div>
        <div class="timeline-meta">${formatDate(e.event_time)} · ${e.location}${e.flight_number ? ` · ${e.flight_number}` : ""}</div>
        <div class="timeline-desc">${e.description}</div>
      </div>
    </div>
  `
    )
    .join("");
}

async function refreshSelected() {
  await loadShipments();
  if (selectedId) selectShipment(selectedId);
}

function openModal() {
  $("#modal-overlay").classList.remove("hidden");
}

function closeModal() {
  $("#modal-overlay").classList.add("hidden");
  $("#shipment-form").reset();
}

async function handleCreateShipment(evt) {
  evt.preventDefault();
  const form = evt.target;
  const data = Object.fromEntries(new FormData(form).entries());
  data.pieces = Number(data.pieces || 1);
  data.weight_kg = Number(data.weight_kg || 0);

  try {
    const shipment = await api("/shipments", { method: "POST", body: JSON.stringify(data) });
    showToast(`Shipment ${shipment.awb_number} created`);
    closeModal();
    await loadShipments();
    selectShipment(shipment.id);
  } catch (err) {
    showToast(err.message, true);
  }
}

async function handleAddEvent(evt) {
  evt.preventDefault();
  if (!selectedId) return;

  const payload = {
    status: $("#event-status").value,
    location: $("#event-location").value.trim(),
    description: $("#event-description").value.trim(),
    flight_number: $("#event-flight").value.trim() || null,
  };

  try {
    await api(`/shipments/${selectedId}/events`, { method: "POST", body: JSON.stringify(payload) });
    showToast("Tracking event added");
    $("#event-form").reset();
    await refreshSelected();
  } catch (err) {
    showToast(err.message, true);
  }
}

function init() {
  $("#new-shipment-btn").addEventListener("click", openModal);
  $("#modal-cancel").addEventListener("click", closeModal);
  $("#shipment-form").addEventListener("submit", handleCreateShipment);
  $("#event-form").addEventListener("submit", handleAddEvent);
  $("#search-input").addEventListener("input", () => loadShipments());
  $("#status-filter").addEventListener("change", () => loadShipments());

  loadStatuses().then(loadShipments).catch((err) => showToast(err.message, true));
}

document.addEventListener("DOMContentLoaded", init);
