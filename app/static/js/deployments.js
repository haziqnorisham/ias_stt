"use strict";

const DEPLOYMENTS_API = "/api/deployments";
const STORAGE_KEY = "api_key";

let state = {
  data: [],
  status: "",
  trapId: "",
};

function getApiKey() {
  return sessionStorage.getItem(STORAGE_KEY);
}

function logout() {
  sessionStorage.removeItem(STORAGE_KEY);
  window.location.replace("/login");
}

function toast(message, type = "success") {
  const id = "t" + Date.now();
  const bg = type === "error" ? "text-bg-danger" : "text-bg-success";
  document.getElementById("toastContainer").insertAdjacentHTML("beforeend", `
    <div id="${id}" class="toast align-items-center ${bg} border-0" role="alert">
      <div class="d-flex">
        <div class="toast-body">${escapeHtml(message)}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
      </div>
    </div>`);
  const el = document.getElementById(id);
  const t = new bootstrap.Toast(el, { delay: 4000 });
  t.show();
  el.addEventListener("hidden.bs.toast", () => el.remove());
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

// ---------------------------------------------------------------------------
// Load + render
// ---------------------------------------------------------------------------
async function loadDeployments() {
  const params = new URLSearchParams();
  if (state.status) params.set("status", state.status);
  if (state.trapId) params.set("trap_id", state.trapId);
  const { ok, body } = await api(`${DEPLOYMENTS_API}?${params.toString()}`);
  if (!ok) { toast((body && body.error) || "Failed to load deployments", "error"); return; }
  state.data = Array.isArray(body) ? body : [];
  render();
}

function render() {
  const tbody = document.getElementById("deploymentsBody");
  if (state.data.length === 0) {
    tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">No deployments found.</td></tr>';
    return;
  }
  tbody.innerHTML = state.data.map(rowHtml).join("");
  document.getElementById("recordCount").textContent = `${state.data.length} deployments`;
}

function rowHtml(d) {
  return `
    <tr>
      <td>${d.id}</td>
      <td><a href="/traps">${escapeHtml(String(d.trap_id))}</a></td>
      <td>${d.status === "active"
        ? '<span class="badge text-bg-success">active</span>'
        : '<span class="badge text-bg-secondary">closed</span>'}
      </td>
      <td class="timestamp">${fmtTs(d.start_date)}</td>
      <td class="timestamp">${fmtTs(d.end_date)}</td>
      <td>${escapeHtml(d.animal_capture) || "—"}</td>
      <td>${d.photo_url
        ? `<img src="${d.photo_url}" alt="photo" style="height:40px" class="img-thumbnail" />`
        : "—"}
      </td>
      <td class="text-end actions-cell">
        <button class="btn btn-sm btn-outline-primary" onclick="showLocations(${d.id})" title="Locations">
          <i class="bi bi-geo-alt"></i>
        </button>
        <button class="btn btn-sm btn-outline-success" onclick="openPhotoUpload(${d.id})" title="Upload Photo">
          <i class="bi bi-camera"></i>
        </button>
      </td>
    </tr>`;
}

// ---------------------------------------------------------------------------
// Location history
// ---------------------------------------------------------------------------
window.showLocations = async function (depId) {
  const panel = document.getElementById("locationPanel");
  const content = document.getElementById("locPanelContent");
  document.getElementById("locDepLabel").textContent = `Deployment #${depId}`;
  content.innerHTML = '<div class="text-muted text-center py-3">Loading…</div>';
  panel.classList.remove("d-none");

  const { ok, body } = await api(`/api/deployments/${depId}/locations`);
  if (!ok) { content.innerHTML = '<div class="text-danger py-2">Failed to load.</div>'; return; }
  const locs = Array.isArray(body) ? body : [];
  if (locs.length === 0) {
    content.innerHTML = '<div class="text-muted text-center py-3">No location history.</div>';
    return;
  }
  content.innerHTML = `
    <table class="table table-sm table-borderless small">
      <thead><tr><th>Location</th><th>Recorded</th><th>Notes</th></tr></thead>
      <tbody>${locs.map(l => `<tr>
        <td>${escapeHtml(l.location)}</td>
        <td class="timestamp">${fmtTs(l.recorded_at)}</td>
        <td>${escapeHtml(l.notes) || "—"}</td>
      </tr>`).join("")}</tbody></table>`;
};

// ---------------------------------------------------------------------------
// Photo upload
// ---------------------------------------------------------------------------
window.openPhotoUpload = function (depId) {
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "image/jpeg,image/png,image/gif";
  input.onchange = async function () {
    const file = input.files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    const { ok, body } = await api(`/api/deployments/${depId}/photo`, {
      method: "POST",
      body: form,
      skipJson: true,
    });
    if (!ok) {
      toast((body && body.error) || "Upload failed.", "error");
    } else {
      toast("Photo uploaded.");
    }
    await loadDeployments();
  };
  input.click();
};

// ---------------------------------------------------------------------------
// Wiring
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  if (!getApiKey()) { window.location.replace("/login"); return; }

  document.getElementById("refreshBtn").addEventListener("click", loadDeployments);
  document.getElementById("logoutBtn").addEventListener("click", logout);
  document.getElementById("closeLocPanel").addEventListener("click", () => {
    document.getElementById("locationPanel").classList.add("d-none");
  });

  document.getElementById("statusFilter").addEventListener("change", (e) => {
    state.status = e.target.value;
    loadDeployments();
  });

  document.getElementById("trapFilter").addEventListener("change", (e) => {
    state.trapId = e.target.value;
    loadDeployments();
  });

  // Populate trap filter
  (async () => {
    const { ok, body } = await api("/api/traps");
    if (ok && Array.isArray(body)) {
      const sel = document.getElementById("trapFilter");
      for (const t of body) {
        sel.insertAdjacentHTML("beforeend",
          `<option value="${t.id}">${escapeHtml(t.trap_id)}</option>`);
      }
    }
  })();

  loadDeployments();
});
