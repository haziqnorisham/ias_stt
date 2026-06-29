"use strict";

const API = "/api/stt";
const STORAGE_KEY = "api_key";

function getApiKey() { return sessionStorage.getItem(STORAGE_KEY); }
function logout() { sessionStorage.removeItem(STORAGE_KEY); window.location.replace("/login"); }

const state = {
  data: [],
  limit: 25,
  offset: 0,
  search: "",
  sortKey: "id",
  sortDir: "asc",
};

let trackerModal, deleteModal, deleteTargetId;

function toast(message, type = "success") {
  const id = "t" + Date.now();
  const bg = type === "error" ? "text-bg-danger" : "text-bg-success";
  document.getElementById("toastContainer").insertAdjacentHTML("beforeend", `
    <div id="${id}" class="toast align-items-center ${bg} border-0" role="alert">
      <div class="d-flex">
        <div class="toast-body">${escapeHtml(message)}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
      </div></div>`);
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
  const headers = Object.assign({ "Content-Type": "application/json" }, options.headers || {});
  const key = getApiKey();
  if (key) headers["Authorization"] = "Bearer " + key;
  const res = await fetch(path, Object.assign({}, options, { headers }));
  if (res.status === 401) { logout(); return { ok: false, status: 401, body: null }; }
  let body = null;
  try { body = await res.json(); } catch (e) { body = null; }
  return { ok: res.ok, status: res.status, body };
}

async function loadTrackers() {
  const params = new URLSearchParams({ limit: state.limit, offset: state.offset });
  const { ok, body } = await api(`${API}?${params.toString()}`);
  if (!ok) { toast((body && body.error) || "Failed to load trackers", "error"); return; }
  state.data = Array.isArray(body) ? body : [];
  render();
}

function visibleRows() {
  let rows = state.data.slice();
  const term = state.search.trim().toLowerCase();
  if (term) {
    rows = rows.filter(r =>
      (r.display_name || "").toLowerCase().includes(term) ||
      (r.device_eui || "").toLowerCase().includes(term));
  }
  const { sortKey, sortDir } = state;
  rows.sort((a, b) => {
    let x = a[sortKey], y = b[sortKey];
    if (x === null || x === undefined) x = "";
    if (y === null || y === undefined) y = "";
    if (typeof x === "number" && typeof y === "number") return sortDir === "asc" ? x - y : y - x;
    x = String(x).toLowerCase(); y = String(y).toLowerCase();
    if (x < y) return sortDir === "asc" ? -1 : 1;
    if (x > y) return sortDir === "asc" ? 1 : -1;
    return 0;
  });
  return rows;
}

function render() {
  const rows = visibleRows();
  const tbody = document.getElementById("trackersBody");
  if (rows.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" class="text-center text-muted py-4">No trackers found.</td></tr>';
  } else {
    tbody.innerHTML = rows.map(rowHtml).join("");
  }
  document.querySelectorAll("th.sortable").forEach(th => {
    th.classList.remove("sort-asc", "sort-desc");
    if (th.dataset.sort === state.sortKey) {
      th.classList.add(state.sortDir === "asc" ? "sort-asc" : "sort-desc");
    }
  });
  document.getElementById("recordCount").textContent = `${state.data.length} on this page`;
  document.getElementById("pageInfo").textContent =
    `Showing ${rows.length} of ${state.data.length} loaded (offset ${state.offset})`;
  document.getElementById("prevBtn").disabled = state.offset === 0;
  document.getElementById("nextBtn").disabled = state.data.length < state.limit;
}

function rowHtml(r) {
  return `
    <tr>
      <td>${r.id}</td>
      <td>${escapeHtml(r.display_name) || "—"}</td>
      <td>${escapeHtml(r.device_eui)}</td>
      <td>${r.latitude ?? "—"}</td>
      <td>${r.longitude ?? "—"}</td>
      <td>${escapeHtml(r.tilt_status) || "—"}</td>
      <td>${r.battery != null ? r.battery + "%" : "—"}</td>
      <td class="timestamp">${fmtTs(r.created_date)}</td>
      <td class="timestamp">${fmtTs(r.updated_date)}</td>
      <td class="text-end actions-cell">
        <button class="btn btn-sm btn-outline-warning" onclick="testTiltAlert(${r.id})" title="Test Alert">
          <i class="bi bi-bell"></i>
        </button>
        <button class="btn btn-sm btn-outline-primary" onclick="editTracker(${r.id})" title="Edit"><i class="bi bi-pencil"></i></button>
        <button class="btn btn-sm btn-outline-danger" onclick="askDelete(${r.id})" title="Delete"><i class="bi bi-trash"></i></button>
      </td>
    </tr>`;
}

function openAdd() {
  document.getElementById("trackerForm").reset();
  document.getElementById("trackerPk").value = "";
  document.getElementById("trackerModalTitle").textContent = "Add Tracker";
  trackerModal.show();
}

window.editTracker = function (id) {
  const r = state.data.find(t => t.id === id);
  if (!r) return;
  document.getElementById("trackerForm").reset();
  document.getElementById("trackerPk").value = r.id;
  document.getElementById("trackerModalTitle").textContent = `Edit Tracker #${r.id}`;
  document.getElementById("f_display_name").value = r.display_name || "";
  document.getElementById("f_device_eui").value = r.device_eui || "";
  document.getElementById("f_latitude").value = r.latitude ?? "";
  document.getElementById("f_longitude").value = r.longitude ?? "";
  document.getElementById("f_battery").value = r.battery ?? "";
  document.getElementById("f_tilt_status").value = r.tilt_status || "";
  trackerModal.show();
};

async function submitForm(e) {
  e.preventDefault();
  const pk = document.getElementById("trackerPk").value;
  const isEdit = pk !== "";

  const payload = {
    display_name: document.getElementById("f_display_name").value.trim(),
    device_eui: document.getElementById("f_device_eui").value.trim(),
  };

  const latRaw = document.getElementById("f_latitude").value.trim();
  payload.latitude = latRaw === "" ? null : parseFloat(latRaw);
  const lngRaw = document.getElementById("f_longitude").value.trim();
  payload.longitude = lngRaw === "" ? null : parseFloat(lngRaw);
  const battRaw = document.getElementById("f_battery").value;
  payload.battery = battRaw === "" ? null : parseInt(battRaw, 10);
  payload.tilt_status = document.getElementById("f_tilt_status").value || null;

  if (!payload.display_name || !payload.device_eui) {
    toast("Display Name and Device EUI are required.", "error"); return;
  }

  const path = isEdit ? `${API}/${pk}` : API;
  const method = isEdit ? "PUT" : "POST";
  const { ok, body } = await api(path, { method, body: JSON.stringify(payload) });
  if (!ok) { toast((body && body.error) || "Operation failed.", "error"); return; }
  trackerModal.hide();
  toast(isEdit ? "Tracker updated." : "Tracker created.");
  await loadTrackers();
}

window.askDelete = function (id) {
  const r = state.data.find(t => t.id === id);
  deleteTargetId = id;
  document.getElementById("deleteLabel").textContent = r ? `${r.display_name || r.device_eui} (#${id})` : `#${id}`;
  deleteModal.show();
};

async function confirmDelete() {
  if (deleteTargetId == null) return;
  const { ok, body } = await api(`${API}/${deleteTargetId}`, { method: "DELETE" });
  deleteModal.hide();
  if (!ok) { toast((body && body.error) || "Delete failed.", "error"); return; }
  toast((body && body.message) || "Tracker deleted.");
  deleteTargetId = null;
  await loadTrackers();
}

window.testTiltAlert = async function (id) {
  const { ok, body } = await api(`${API}/${id}/test_tilt_alert`, { method: "POST" });
  if (ok) {
    toast((body && body.message) || "Alert triggered.");
  } else {
    toast((body && body.error) || "Test failed.", "error");
  }
};

document.addEventListener("DOMContentLoaded", () => {
  if (!getApiKey()) { window.location.replace("/login"); return; }

  trackerModal = new bootstrap.Modal(document.getElementById("trackerModal"));
  deleteModal = new bootstrap.Modal(document.getElementById("deleteModal"));

  document.getElementById("addBtn").addEventListener("click", openAdd);
  document.getElementById("refreshBtn").addEventListener("click", loadTrackers);
  document.getElementById("trackerForm").addEventListener("submit", submitForm);
  document.getElementById("confirmDeleteBtn").addEventListener("click", confirmDelete);
  document.getElementById("logoutBtn").addEventListener("click", logout);

  document.getElementById("searchInput").addEventListener("input", e => { state.search = e.target.value; render(); });
  document.getElementById("pageSize").addEventListener("change", e => { state.limit = parseInt(e.target.value, 10); state.offset = 0; loadTrackers(); });
  document.getElementById("prevBtn").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); loadTrackers(); });
  document.getElementById("nextBtn").addEventListener("click", () => { state.offset += state.limit; loadTrackers(); });

  document.querySelectorAll("th.sortable").forEach(th => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sortKey === key) { state.sortDir = state.sortDir === "asc" ? "desc" : "asc"; }
      else { state.sortKey = key; state.sortDir = "asc"; }
      render();
    });
  });

  loadTrackers();
});
