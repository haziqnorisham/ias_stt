"use strict";

const STORAGE_KEY = "api_key";
const API_TRAPS = "/api/traps";
const API_DEPLOYMENTS = "/api/deployments";

let state = {
  traps: [],
  statusFilter: "",
};

// --- auth helpers ---
function getApiKey() { return sessionStorage.getItem(STORAGE_KEY); }
function logout() { sessionStorage.removeItem(STORAGE_KEY); window.location.replace("/login"); }

// --- helpers ---
function toast(message, type = "success") {
  const id = "t" + Date.now();
  const bg = type === "error" ? "text-bg-danger" : "text-bg-success";
  document.getElementById("toastContainer").insertAdjacentHTML("beforeend",
    `<div id="${id}" class="toast align-items-center ${bg} border-0" role="alert">
      <div class="d-flex">
        <div class="toast-body">${escapeHtml(message)}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
      </div></div>`);
  const t = new bootstrap.Toast(document.getElementById(id), { delay: 3000 });
  t.show();
}

function escapeHtml(v) {
  if (v === null || v === undefined) return "";
  return String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function fmtTs(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString();
}

async function api(path, options = {}) {
  const headers = Object.assign({}, options.headers || {});
  if (!options.skipJson) headers["Content-Type"] = "application/json";
  const key = getApiKey();
  if (key) headers["Authorization"] = "Bearer " + key;
  const res = await fetch(path, Object.assign({}, options, { headers }));
  if (res.status === 401) { logout(); return { ok: false, status: 401, body: null }; }
  let body = null;
  try { body = await res.json(); } catch (e) { body = null; }
  return { ok: res.ok, status: res.status, body };
}

// --- load ---
async function loadAll() {
  const { ok, body: traps } = await api(API_TRAPS + "?limit=200");
  if (!ok) { toast("Failed to load traps", "error"); return; }
  const allTraps = Array.isArray(traps) ? traps : [];

  // Filter by status
  const filtered = state.statusFilter
    ? allTraps.filter(t => t.status === state.statusFilter)
    : allTraps;

  // Load deployments for each trap
  const results = await Promise.all(
    filtered.map(async (trap) => {
      const { ok: dOk, body: deps } = await api(`/api/traps/${trap.id}/deployments`);
      return {
        trap,
        deployments: dOk && Array.isArray(deps) ? deps : [],
      };
    })
  );

  state.traps = results;
  render();
}

function render() {
  const container = document.getElementById("trapsAccordion");
  if (state.traps.length === 0) {
    container.innerHTML = '<div class="text-muted text-center py-5">No traps with deployments.</div>';
    document.getElementById("recordCount").textContent = "";
    return;
  }

  const totalTraps = state.traps.length;
  const totalDeps = state.traps.reduce((s, t) => s + t.deployments.length, 0);
  document.getElementById("recordCount").textContent = `${totalTraps} traps / ${totalDeps} deploys`;

  container.innerHTML = state.traps.map(trapSection).join("");
}

// --- trap section ---
function trapSection({ trap, deployments }) {
  const trapIcon = trap.status === "active" ? "bi-play-circle text-success" : "bi-stop-circle text-secondary";
  const bg = trap.status === "active" ? "bg-success" : "bg-secondary";
  const id = "trap-" + trap.id;
  return `
    <div class="card deploy-card mb-3">
      <div class="card-header py-2 trap-header d-flex align-items-center justify-content-between"
           data-bs-toggle="collapse" data-bs-target="#${id}">
        <div>
          <i class="bi ${trapIcon} me-1"></i>
          <strong>${escapeHtml(trap.trap_id)}</strong>
          <span class="badge ${bg} ms-2">${escapeHtml(trap.status)}</span>
          <span class="text-muted small ms-2">${deployments.length} deployment${deployments.length !== 1 ? "s" : ""}</span>
        </div>
        <i class="bi bi-chevron-down"></i>
      </div>
      <div id="${id}" class="collapse${state.traps.length === 1 ? " show" : ""}">
        <div class="card-body p-2">
          ${deployments.length === 0
            ? '<p class="text-muted small text-center mb-2">No deployments yet.</p>'
            : deployments.map(d => deploymentCard(d, trap)).join("<hr class='my-2' />")}
          <hr class="my-2" />
          <div class="d-flex align-items-center justify-content-between px-2 gap-2">
            <button class="btn btn-sm btn-outline-success btn-action flex-shrink-0"
                    onclick="getGpsLocation(${trap.id})" title="Get GPS">
              <i class="bi bi-geo-alt-fill"></i>
            </button>
            <span class="small text-muted flex-grow-1 text-center">Trap: ${escapeHtml(trap.trap_id)}</span>
            <button class="btn btn-sm btn-outline-secondary btn-action flex-shrink-0"
                    onclick="openStatusModal(${trap.id})">
              <i class="bi bi-arrow-repeat me-1"></i> ${trap.status === "active" ? "Deactivate" : "Activate"}
            </button>
          </div>
        </div>
      </div>
    </div>`;
}

// --- deployment card ---
function deploymentCard(d, trap) {
  const badge = d.status === "active"
    ? '<span class="badge text-bg-success">active</span>'
    : '<span class="badge text-bg-secondary">closed</span>';
  return `
    <div class="px-2">
      <div class="d-flex justify-content-between align-items-center mb-1">
        <span><strong>#${d.id}</strong> ${badge}</span>
        <small class="text-muted">${fmtTs(d.start_date)}</small>
      </div>
      ${d.end_date ? `<small class="text-muted d-block">Ended: ${fmtTs(d.end_date)}</small>` : ""}
      <div class="d-flex align-items-center gap-2 mt-2">
        <span class="small flex-grow-1">
          Capture: <strong>${escapeHtml(d.animal_capture) || "—"}</strong>
          ${d.notes ? `<br><small class="text-muted">${escapeHtml(d.notes)}</small>` : ""}
        </span>
        <button class="btn btn-sm btn-outline-info btn-action" onclick="openEdit(${d.id})">
          <i class="bi bi-pencil"></i>
        </button>
        <button class="btn btn-sm btn-outline-success btn-action" onclick="openPhotoUpload(${d.id})">
          <i class="bi bi-camera"></i>
        </button>
      </div>
      ${d.photo_url
        ? `<img src="${d.photo_url}" class="img-thumbnail mt-2" style="max-height:120px; cursor:pointer" alt="photo"
               onclick="event.stopPropagation(); openImageViewer('${d.photo_url}')" />`
        : ""}
    </div>`;
}

// --- edit deployment ---
let editModal;
window.openEdit = function (depId) {
  const entry = state.traps
    .flatMap(t => t.deployments)
    .find(d => d.id === depId);
  if (!entry) return;
  document.getElementById("editDepId").value = depId;
  document.getElementById("editAnimalCapture").value = entry.animal_capture || "";
  document.getElementById("editNotes").value = entry.notes || "";
  editModal.show();
};

async function submitEdit(e) {
  e.preventDefault();
  const depId = document.getElementById("editDepId").value;
  const payload = {
    animal_capture: document.getElementById("editAnimalCapture").value.trim(),
    notes: document.getElementById("editNotes").value.trim(),
  };
  const { ok, body } = await api(`${API_DEPLOYMENTS}/${depId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!ok) { toast((body && body.error) || "Failed to update", "error"); return; }
  editModal.hide();
  toast("Deployment updated.");
  await loadAll();
}

// --- photo upload ---
window.openPhotoUpload = function (depId) {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/*";
  input.capture = "environment";
  input.onchange = async function () {
    const file = input.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    const { ok, body } = await api(`${API_DEPLOYMENTS}/${depId}/photo`, {
      method: "POST", body: form, skipJson: true,
    });
    if (!ok) { toast((body && body.error) || "Upload failed.", "error"); return; }
    toast("Photo uploaded.");
    await loadAll();
  };
  input.click();
};

// --- trap status toggle ---
let statusModal, statusTrapId;
window.openStatusModal = function (trapId) {
  statusTrapId = trapId;
  const entry = state.traps.find(t => t.trap.id === trapId);
  if (!entry) return;
  document.getElementById("statusTrapLabel").textContent = entry.trap.trap_id;
  statusModal.show();
};

async function changeTrapStatus(newStatus) {
  statusModal.hide();
  const payload = { status: newStatus, updated_by: "mobile" };
  const { ok, body } = await api(`${API_TRAPS}/${statusTrapId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!ok) { toast((body && body.error) || "Status change failed.", "error"); return; }
  toast(newStatus === "active" ? "Trap activated — deployment created." : "Trap deactivated — deployment closed.");
  await loadAll();
}

// --- image viewer ---
let imageViewer;
window.openImageViewer = function (url) {
  document.getElementById("fullImage").src = url;
  if (!imageViewer) imageViewer = new bootstrap.Modal(document.getElementById("imageViewer"));
  imageViewer.show();
};

// --- GPS / location ---
let locationModal;
let gpsTrapId;

window.getGpsLocation = function (trapId) {
  if (!navigator.geolocation) {
    openLocationModal(trapId);
    return;
  }
  toast("Getting GPS location…");
  navigator.geolocation.getCurrentPosition(
    async (pos) => {
      const location = `${pos.coords.latitude.toFixed(5)},${pos.coords.longitude.toFixed(5)}`;
      await saveLocation(trapId, location);
    },
    (err) => {
      // Geolocation blocked — fall back to manual entry.
      // Common causes: non-HTTPS origin, permission denied, timeout.
      openLocationModal(trapId);
    },
    { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 }
  );
};

function openLocationModal(trapId) {
  gpsTrapId = trapId;
  document.getElementById("locLat").value = "";
  document.getElementById("locLng").value = "";
  if (!locationModal) {
    locationModal = new bootstrap.Modal(document.getElementById("locationModal"));
  }
  locationModal.show();
}

async function saveLocation(trapId, location) {
  const payload = { location, updated_by: "mobile-gps" };
  const { ok, body } = await api(`${API_TRAPS}/${trapId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
  if (!ok) {
    toast((body && body.error) || "Failed to update location", "error");
    return;
  }
  toast(`Location updated: ${location}`);
  await loadAll();
}

async function submitManualLocation() {
  const lat = document.getElementById("locLat").value.trim();
  const lng = document.getElementById("locLng").value.trim();
  if (!lat || !lng) {
    toast("Please enter both latitude and longitude.", "error");
    return;
  }
  if (isNaN(lat) || isNaN(lng)) {
    toast("Coordinates must be numbers.", "error");
    return;
  }
  locationModal.hide();
  await saveLocation(gpsTrapId, `${lat},${lng}`);
}

// --- wiring ---
document.addEventListener("DOMContentLoaded", () => {
  if (!getApiKey()) { window.location.replace("/login"); return; }

  editModal = new bootstrap.Modal(document.getElementById("editModal"));
  statusModal = new bootstrap.Modal(document.getElementById("statusModal"));

  document.getElementById("editForm").addEventListener("submit", submitEdit);
  document.getElementById("activateBtn").addEventListener("click", () => changeTrapStatus("active"));
  document.getElementById("deactivateBtn").addEventListener("click", () => changeTrapStatus("inactive"));

  document.getElementById("locSaveBtn").addEventListener("click", submitManualLocation);
  document.getElementById("locGpsBtn").addEventListener("click", () => {
    locationModal.hide();
    setTimeout(() => getGpsLocation(gpsTrapId), 300);
  });

  document.getElementById("refreshBtn").addEventListener("click", loadAll);
  document.getElementById("logoutBtn").addEventListener("click", logout);

  document.getElementById("statusFilter").addEventListener("change", (e) => {
    state.statusFilter = e.target.value;
    loadAll();
  });

  loadAll();
});
