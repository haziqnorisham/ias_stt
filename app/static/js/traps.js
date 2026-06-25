"use strict";

const API = "/api/traps";
const STORAGE_KEY = "api_key";

function getApiKey() {
  return sessionStorage.getItem(STORAGE_KEY);
}

function logout() {
  sessionStorage.removeItem(STORAGE_KEY);
  window.location.replace("/login");
}

const state = {
  data: [],          // current page from server
  limit: 25,
  offset: 0,
  status: "",        // server-side filter
  search: "",        // client-side filter
  sortKey: "id",
  sortDir: "asc",
};

let trapModal, deleteModal, deleteTargetId;

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------
function toast(message, type = "success") {
  const id = "t" + Date.now();
  const bg = type === "error" ? "text-bg-danger" : "text-bg-success";
  const html = `
    <div id="${id}" class="toast align-items-center ${bg} border-0" role="alert">
      <div class="d-flex">
        <div class="toast-body">${escapeHtml(message)}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto"
                data-bs-dismiss="toast"></button>
      </div>
    </div>`;
  document.getElementById("toastContainer").insertAdjacentHTML("beforeend", html);
  const el = document.getElementById(id);
  const t = new bootstrap.Toast(el, { delay: 4000 });
  t.show();
  el.addEventListener("hidden.bs.toast", () => el.remove());
}

function escapeHtml(v) {
  if (v === null || v === undefined) return "";
  return String(v)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtTs(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString();
}

async function api(path, options = {}) {
  const headers = Object.assign(
    { "Content-Type": "application/json" },
    options.headers || {}
  );
  const key = getApiKey();
  if (key) headers["Authorization"] = "Bearer " + key;

  const opts = Object.assign({}, options, { headers });
  const res = await fetch(path, opts);

  if (res.status === 401) {
    // Key missing/invalid/expired -> back to login.
    logout();
    return { ok: false, status: 401, body: null };
  }

  let body = null;
  try {
    body = await res.json();
  } catch (e) {
    body = null;
  }
  return { ok: res.ok, status: res.status, body };
}

// ----------------------------------------------------------------------------
// Data loading + rendering
// ----------------------------------------------------------------------------
async function loadTraps() {
  const params = new URLSearchParams({ limit: state.limit, offset: state.offset });
  if (state.status) params.set("status", state.status);
  const { ok, body } = await api(`${API}?${params.toString()}`);
  if (!ok) {
    toast((body && body.error) || "Failed to load traps", "error");
    return;
  }
  state.data = Array.isArray(body) ? body : [];
  render();
}

function visibleRows() {
  let rows = state.data.slice();
  const term = state.search.trim().toLowerCase();
  if (term) {
    rows = rows.filter(
      (r) =>
        (r.trap_id || "").toLowerCase().includes(term) ||
        (r.location || "").toLowerCase().includes(term)
    );
  }
  const { sortKey, sortDir } = state;
  rows.sort((a, b) => {
    let x = a[sortKey], y = b[sortKey];
    if (x === null || x === undefined) x = "";
    if (y === null || y === undefined) y = "";
    if (typeof x === "number" && typeof y === "number") {
      return sortDir === "asc" ? x - y : y - x;
    }
    x = String(x).toLowerCase();
    y = String(y).toLowerCase();
    if (x < y) return sortDir === "asc" ? -1 : 1;
    if (x > y) return sortDir === "asc" ? 1 : -1;
    return 0;
  });
  return rows;
}

function render() {
  const rows = visibleRows();
  const tbody = document.getElementById("trapsBody");
  if (rows.length === 0) {
    tbody.innerHTML =
      '<tr><td colspan="11" class="text-center text-muted py-4">No traps found.</td></tr>';
  } else {
    tbody.innerHTML = rows.map(rowHtml).join("");
  }

  document.querySelectorAll("th.sortable").forEach((th) => {
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
  const badge =
    r.status === "active"
      ? '<span class="badge text-bg-success">active</span>'
      : `<span class="badge text-bg-secondary">${escapeHtml(r.status)}</span>`;
  return `
    <tr>
      <td>${r.id}</td>
      <td>${badge}</td>
      <td>${escapeHtml(r.trap_id)}</td>
      <td>${escapeHtml(r.tracker_id)}</td>
      <td>${escapeHtml(r.location) || "—"}</td>
      <td>${escapeHtml(r.door_status) || "—"}</td>
      <td>${r.temperature ?? "—"}</td>
      <td>${escapeHtml(r.updated_by)}</td>
      <td class="timestamp">${fmtTs(r.created_at)}</td>
      <td class="timestamp">${fmtTs(r.updated_at)}</td>
      <td class="text-end actions-cell">
        <button class="btn btn-sm btn-outline-primary" onclick="editTrap(${r.id})" title="Edit">
          <i class="bi bi-pencil"></i>
        </button>
        <button class="btn btn-sm btn-outline-danger" onclick="askDelete(${r.id})" title="Delete">
          <i class="bi bi-trash"></i>
        </button>
      </td>
    </tr>`;
}

// ----------------------------------------------------------------------------
// Add / Edit
// ----------------------------------------------------------------------------
function openAdd() {
  document.getElementById("trapForm").reset();
  document.getElementById("trapPk").value = "";
  document.getElementById("trapModalTitle").textContent = "Add Trap";
  document.getElementById("updatedByReq").style.display = "none";
  document.getElementById("f_updated_by").required = false;
  document.getElementById("f_status").value = "active";
  trapModal.show();
}

window.editTrap = function (id) {
  const r = state.data.find((t) => t.id === id);
  if (!r) return;
  document.getElementById("trapForm").reset();
  document.getElementById("trapPk").value = r.id;
  document.getElementById("trapModalTitle").textContent = `Edit Trap #${r.id}`;
  document.getElementById("f_status").value = r.status || "active";
  document.getElementById("f_trap_id").value = r.trap_id || "";
  document.getElementById("f_tracker_id").value = r.tracker_id || "";
  document.getElementById("f_location").value = r.location || "";
  document.getElementById("f_door_status").value = r.door_status || "";
  document.getElementById("f_temperature").value = r.temperature ?? "";
  document.getElementById("f_notes").value = r.notes || "";
  document.getElementById("f_updated_by").value = "";
  document.getElementById("updatedByReq").style.display = "";
  document.getElementById("f_updated_by").required = true;
  trapModal.show();
};

async function submitForm(e) {
  e.preventDefault();
  const pk = document.getElementById("trapPk").value;
  const isEdit = pk !== "";

  const payload = {
    status: document.getElementById("f_status").value.trim(),
    trap_id: document.getElementById("f_trap_id").value.trim(),
    tracker_id: document.getElementById("f_tracker_id").value.trim(),
  };

  const optionals = {
    location: document.getElementById("f_location").value.trim(),
    door_status: document.getElementById("f_door_status").value,
    notes: document.getElementById("f_notes").value.trim(),
  };
  for (const [k, v] of Object.entries(optionals)) {
    payload[k] = v === "" ? null : v;
  }
  const tempRaw = document.getElementById("f_temperature").value.trim();
  payload.temperature = tempRaw === "" ? null : Number(tempRaw);

  const updatedBy = document.getElementById("f_updated_by").value.trim();
  if (updatedBy) payload.updated_by = updatedBy;

  // Client-side validation
  if (!payload.status || !payload.trap_id || !payload.tracker_id) {
    toast("Status, Trap ID and Tracker ID are required.", "error");
    return;
  }
  if (isEdit && !updatedBy) {
    toast("'Updated By' is required when editing.", "error");
    return;
  }

  const path = isEdit ? `${API}/${pk}` : API;
  const method = isEdit ? "PUT" : "POST";
  const { ok, body } = await api(path, { method, body: JSON.stringify(payload) });
  if (!ok) {
    toast((body && body.error) || "Operation failed.", "error");
    return;
  }
  trapModal.hide();
  toast(isEdit ? "Trap updated." : "Trap created.");
  await loadTraps();
}

// ----------------------------------------------------------------------------
// Delete
// ----------------------------------------------------------------------------
window.askDelete = function (id) {
  const r = state.data.find((t) => t.id === id);
  deleteTargetId = id;
  document.getElementById("deleteLabel").textContent = r ? `${r.trap_id} (#${id})` : `#${id}`;
  deleteModal.show();
};

async function confirmDelete() {
  if (deleteTargetId == null) return;
  const { ok, body } = await api(`${API}/${deleteTargetId}`, { method: "DELETE" });
  deleteModal.hide();
  if (!ok) {
    toast((body && body.error) || "Delete failed.", "error");
    return;
  }
  toast((body && body.message) || "Trap deleted.");
  deleteTargetId = null;
  await loadTraps();
}

// ----------------------------------------------------------------------------
// Wiring
// ----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  // Auth guard: require a key in this browser session.
  if (!getApiKey()) {
    window.location.replace("/login");
    return;
  }

  trapModal = new bootstrap.Modal(document.getElementById("trapModal"));
  deleteModal = new bootstrap.Modal(document.getElementById("deleteModal"));

  document.getElementById("addBtn").addEventListener("click", openAdd);
  document.getElementById("refreshBtn").addEventListener("click", loadTraps);
  document.getElementById("trapForm").addEventListener("submit", submitForm);
  document.getElementById("confirmDeleteBtn").addEventListener("click", confirmDelete);
  document.getElementById("logoutBtn").addEventListener("click", logout);

  document.getElementById("searchInput").addEventListener("input", (e) => {
    state.search = e.target.value;
    render();
  });

  document.getElementById("statusFilter").addEventListener("change", (e) => {
    state.status = e.target.value;
    state.offset = 0;
    loadTraps();
  });

  document.getElementById("pageSize").addEventListener("change", (e) => {
    state.limit = parseInt(e.target.value, 10);
    state.offset = 0;
    loadTraps();
  });

  document.getElementById("prevBtn").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    loadTraps();
  });

  document.getElementById("nextBtn").addEventListener("click", () => {
    state.offset += state.limit;
    loadTraps();
  });

  document.querySelectorAll("th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.dataset.sort;
      if (state.sortKey === key) {
        state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
      } else {
        state.sortKey = key;
        state.sortDir = "asc";
      }
      render();
    });
  });

  loadTraps();
});
