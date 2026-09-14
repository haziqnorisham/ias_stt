const dropdown = document.getElementById("trackerList");
const STT_URL = "/api/stt";
const TRAP_URL = "/api/traps";

function getApiKey() {
    return sessionStorage.getItem("api_key");
}

async function populateDropdown() {
    try {
        const apiKey = getApiKey();
        const headers = {
            "Authorization": apiKey ? "Bearer " + apiKey : "",
            "Content-Type": "application/json"
        };

        // Fetch both Trackers (STT) and Traps concurrently
        const [sttRes, trapRes] = await Promise.all([
            fetch(STT_URL, { headers }),
            fetch(TRAP_URL, { headers })
        ]);

        if (sttRes.status === 401 || trapRes.status === 401) {
            window.location.replace("/login");
            return;
        }

        if (!sttRes.ok || !trapRes.ok) {
            throw new Error(`Fetch failed! STT: ${sttRes.status}, Traps: ${trapRes.status}`);
        }

        const trackerData = await sttRes.json();
        const trapData = await trapRes.json();

        // Extract all tracker_ids currently assigned to traps
        const assignedTrackerIds = new Set(
            trapData
                .map(trap => trap.tracker_id)
                .filter(id => id && id.trim() !== "")
        );

        // Filter STTs to keep only unassigned ones
        const availableTrackers = trackerData.filter(
            stt => !assignedTrackerIds.has(stt.device_eui)
        );

        dropdown.innerHTML = '<option value="">--No Tracker--</option>';

        if (availableTrackers.length === 0) {
            const option = document.createElement("option");
            option.value = "";
            option.textContent = "No unassigned trackers available";
            option.disabled = true;
            dropdown.appendChild(option);
            return;
        }

        availableTrackers.forEach(item => {
            const option = document.createElement("option");
            option.value = item.device_eui;
            option.textContent = item.display_name
                ? `${item.display_name} (${item.device_eui})`
                : item.device_eui;
            dropdown.appendChild(option);
        });

    } catch (error) {
        console.error("Could not fetch data from Flask:", error);
    }
}


function assignTracker() {
    const current_trap_id = document.getElementById('trapId').getAttribute('current_trap_id');
    const selected_tracker_id = document.getElementById('trackerList').value;
    const url = '/api/traps/' + current_trap_id;

    // The data you want to update
    const updatedData = {
        trap_id: current_trap_id,
        tracker_id: selected_tracker_id
    };

    // Making the API request
    fetch(url, {
        method: 'PUT', // Use 'PUT' if replacing the entire object
        headers: {
            'Content-Type': 'application/json', // Tells the server you are sending JSON
            'Authorization': 'Bearer ' + getApiKey() // Optional: If your API requires authentication
        },
        body: JSON.stringify(updatedData) // Converts JS object to JSON string
    })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! Status: ${response.status}`);
            }
            return response.json(); // Parses the JSON response from the server
        })
        .then(data => {
            console.log('Success: Data updated:', data);
            alert("Tracker assigned successfully");

            setTimeout(() => {
                console.log("go to traps page");
                window.location.href = `/traps`;
            }, 1000);
        })
        .catch(error => {
            console.error('Error updating data:', error);
        });

}

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
        <button type="assignBtn" class="btn-close btn-close-white me-2 m-auto"
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
    return d.toLocaleString(undefined, {
        timeZone: window.APP_TIMEZONE || "Asia/Kuala_Lumpur",
    });
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


// ---------------------------------------------------------
// Populate the dropdown with the list of trackers
// ---------------------------------------------------------
populateDropdown();

// ---------------------------------------------------------
// Select the button element
// ---------------------------------------------------------
const button = document.getElementById('assignBtn');
// Add the click event listener
button.addEventListener('click', assignTracker);









