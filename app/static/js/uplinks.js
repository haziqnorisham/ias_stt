"use strict";

const API = "/api/uplinks";
const TRACKERS_API = "/api/stt";
const STORAGE_KEY = "api_key";

const state = {
  data: [],
  limit: 25,
  offset: 0,
  deviceEui: "",
  source: "",
};

let detailModal;

function getApiKey() {
  return sessionStorage.getItem(STORAGE_KEY);
}

function logout() {
  sessionStorage.removeItem(STORAGE_KEY);
  window.location.replace("/login");
}

function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtTs(value) {
  if (!value) return "—";
  const date = new Date(value);
  return isNaN(date)
    ? value
    : date.toLocaleString(undefined, {
        timeZone: window.APP_TIMEZONE || "Asia/Kuala_Lumpur",
      });
}

function toast(message, type = "success") {
  const id = "t" + Date.now();
  const bg = type === "error" ? "text-bg-danger" : "text-bg-success";
  document.getElementById("toastContainer").insertAdjacentHTML(
    "beforeend",
    `<div id="${id}" class="toast align-items-center ${bg} border-0" role="alert">
      <div class="d-flex">
        <div class="toast-body">${escapeHtml(message)}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
      </div>
    </div>`
  );
  const element = document.getElementById(id);
  const instance = new bootstrap.Toast(element, { delay: 4000 });
  instance.show();
  element.addEventListener("hidden.bs.toast", () => element.remove());
}

async function api(path, options = {}) {
  const headers = Object.assign(
    { "Content-Type": "application/json" },
    options.headers || {}
  );
  const key = getApiKey();
  if (key) headers.Authorization = "Bearer " + key;

  const response = await fetch(path, Object.assign({}, options, { headers }));
  if (response.status === 401) {
    logout();
    return { ok: false, status: 401, body: null };
  }

  let body = null;
  try {
    body = await response.json();
  } catch (error) {
    body = null;
  }
  return { ok: response.ok, status: response.status, body };
}

async function fetchAllTrackers() {
  const trackers = [];
  const limit = 100;
  let offset = 0;
  while (true) {
    const { ok, body } = await api(
      `${TRACKERS_API}?limit=${limit}&offset=${offset}`
    );
    if (!ok || !Array.isArray(body) || body.length === 0) break;
    trackers.push(...body);
    if (body.length < limit) break;
    offset += limit;
  }
  return trackers;
}

async function loadTrackerFilter() {
  const trackers = await fetchAllTrackers();
  const select = document.getElementById("trackerFilter");
  const current = select.value;
  const byEui = new Map(trackers.map((tracker) => [tracker.device_eui, tracker]));

  if (current && !byEui.has(current)) {
    byEui.set(current, { device_eui: current, display_name: "" });
  }

  const sorted = Array.from(byEui.values()).sort((a, b) =>
    String(a.display_name || a.device_eui).localeCompare(
      String(b.display_name || b.device_eui)
    )
  );
  let html = '<option value="">All trackers</option>';
  for (const tracker of sorted) {
    const label = tracker.display_name
      ? `${tracker.display_name} (${tracker.device_eui})`
      : tracker.device_eui;
    html += `<option value="${escapeHtml(tracker.device_eui)}">${escapeHtml(label)}</option>`;
  }
  select.innerHTML = html;
  select.value = current;
}

async function loadUplinks() {
  const params = new URLSearchParams({
    limit: state.limit,
    offset: state.offset,
  });
  if (state.deviceEui) params.set("device_eui", state.deviceEui);
  if (state.source) params.set("source", state.source);

  const { ok, body } = await api(`${API}?${params.toString()}`);
  if (!ok) {
    toast((body && body.error) || "Failed to load uplinks", "error");
    return;
  }
  state.data = Array.isArray(body) ? body : [];
  render();
}

function render() {
  const tbody = document.getElementById("uplinksBody");
  if (state.data.length === 0) {
    tbody.innerHTML =
      '<tr><td colspan="8" class="text-center text-muted py-4">No uplinks found.</td></tr>';
  } else {
    tbody.innerHTML = state.data.map(rowHtml).join("");
  }

  document.getElementById("recordCount").textContent =
    `${state.data.length} on this page`;
  document.getElementById("pageInfo").textContent =
    `Showing ${state.data.length} loaded (offset ${state.offset})`;
  document.getElementById("prevBtn").disabled = state.offset === 0;
  document.getElementById("nextBtn").disabled = state.data.length < state.limit;
}

function rowHtml(uplink) {
  const coordinates =
    uplink.latitude !== null && uplink.longitude !== null
      ? `${uplink.latitude}, ${uplink.longitude}`
      : "—";
  const battery =
    uplink.battery === null || uplink.battery === undefined
      ? "—"
      : `${uplink.battery}%`;
  const sourceClass = uplink.source === "http" ? "text-bg-primary" : "text-bg-info";

  return `<tr>
    <td class="timestamp">${escapeHtml(fmtTs(uplink.received_at))}</td>
    <td>${escapeHtml(uplink.display_name) || "—"}</td>
    <td class="font-monospace small">${escapeHtml(uplink.device_eui)}</td>
    <td>${escapeHtml(coordinates)}</td>
    <td>${escapeHtml(uplink.tilt_status) || "—"}</td>
    <td>${escapeHtml(battery)}</td>
    <td><span class="badge ${sourceClass}">${escapeHtml(uplink.source)}</span></td>
    <td class="text-end">
      <button class="btn btn-sm btn-outline-primary" type="button"
              onclick="showUplink(${uplink.id})" title="View payload">
        <i class="bi bi-eye"></i>
      </button>
    </td>
  </tr>`;
}

window.showUplink = async function (uplinkId) {
  document.getElementById("uplinkDetailTitle").textContent =
    `Uplink #${uplinkId}`;
  document.getElementById("rawPayload").textContent = "Loading…";
  detailModal.show();

  const { ok, body } = await api(`${API}/${uplinkId}`);
  if (!ok) {
    document.getElementById("rawPayload").textContent =
      (body && body.error) || "Could not load uplink details.";
    return;
  }

  document.getElementById("detailReceived").textContent = fmtTs(body.received_at);
  document.getElementById("detailDevice").textContent =
    body.display_name
      ? `${body.display_name} (${body.device_eui})`
      : body.device_eui || "—";
  document.getElementById("detailSource").textContent = body.source || "—";
  document.getElementById("detailTopic").textContent = body.topic || "—";
  document.getElementById("detailCoordinates").textContent =
    body.latitude !== null && body.longitude !== null
      ? `${body.latitude}, ${body.longitude}`
      : "—";
  document.getElementById("detailPosition").textContent = body.tilt_status || "—";
  document.getElementById("detailBattery").textContent =
    body.battery === null || body.battery === undefined
      ? "—"
      : `${body.battery}%`;

  let raw = body.raw_payload || "";
  try {
    raw = JSON.stringify(JSON.parse(raw), null, 2);
  } catch (error) {
    // Keep the stored text visible if it is not parseable for any reason.
  }
  document.getElementById("rawPayload").textContent = raw || "—";
};

document.addEventListener("DOMContentLoaded", () => {
  if (!getApiKey()) {
    window.location.replace("/login");
    return;
  }

  detailModal = new bootstrap.Modal(document.getElementById("uplinkDetailModal"));

  document.getElementById("logoutBtn").addEventListener("click", logout);
  document.getElementById("refreshBtn").addEventListener("click", () => {
    loadTrackerFilter();
    loadUplinks();
  });
  document.getElementById("trackerFilter").addEventListener("change", (event) => {
    state.deviceEui = event.target.value;
    state.offset = 0;
    loadUplinks();
  });
  document.getElementById("sourceFilter").addEventListener("change", (event) => {
    state.source = event.target.value;
    state.offset = 0;
    loadUplinks();
  });
  document.getElementById("pageSize").addEventListener("change", (event) => {
    state.limit = parseInt(event.target.value, 10);
    state.offset = 0;
    loadUplinks();
  });
  document.getElementById("prevBtn").addEventListener("click", () => {
    state.offset = Math.max(0, state.offset - state.limit);
    loadUplinks();
  });
  document.getElementById("nextBtn").addEventListener("click", () => {
    state.offset += state.limit;
    loadUplinks();
  });

  loadTrackerFilter();
  loadUplinks();
});
