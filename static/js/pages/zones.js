// =====================================================
// Zone Analytics — interactive editor + metrics
// =====================================================

const FRAME_W = 1280, FRAME_H = 720;

let cameraId = null;
let tool = "polygon";
let draft = [];            // points in FRAME coords
let rectStart = null;
let zones = [];            // existing zones
let frozen = false;        // freeze the snapshot background for drawing
let popChart, dwellChart, hourlyChart;

const canvas = document.getElementById("zone-canvas");
const bg = document.getElementById("zone-bg");
const ctx = canvas.getContext("2d");

// ---------- coordinate mapping ----------
function sizeCanvas() {
    const w = canvas.clientWidth || bg.clientWidth || 640;
    const h = Math.round(w * FRAME_H / FRAME_W);
    canvas.width = w; canvas.height = h;
    canvas.style.height = h + "px";
}
function toFrame(cx, cy) {
    return [Math.round(cx * FRAME_W / canvas.width),
            Math.round(cy * FRAME_H / canvas.height)];
}
function toCanvas(fx, fy) {
    return [fx * canvas.width / FRAME_W, fy * canvas.height / FRAME_H];
}

// ---------- tools ----------
function setTool(t) {
    tool = t;
    draft = []; rectStart = null;
    document.getElementById("tool-polygon").classList.toggle("btn", t === "polygon");
    document.getElementById("tool-rect").classList.toggle("btn", t === "rect");
    redraw();
}
function clearDraft() { draft = []; rectStart = null; redraw(); }
function finishShape() { redraw(); }

// ---------- canvas events ----------
canvas.addEventListener("click", (e) => {
    const r = canvas.getBoundingClientRect();
    const cx = e.clientX - r.left, cy = e.clientY - r.top;
    if (tool === "polygon") {
        draft.push(toFrame(cx, cy));
        redraw();
    }
});
canvas.addEventListener("mousedown", (e) => {
    if (tool !== "rect") return;
    const r = canvas.getBoundingClientRect();
    rectStart = [e.clientX - r.left, e.clientY - r.top];
});
canvas.addEventListener("mouseup", (e) => {
    if (tool !== "rect" || !rectStart) return;
    const r = canvas.getBoundingClientRect();
    const x2 = e.clientX - r.left, y2 = e.clientY - r.top;
    const [x1, y1] = rectStart;
    const p1 = toFrame(Math.min(x1, x2), Math.min(y1, y2));
    const p2 = toFrame(Math.max(x1, x2), Math.min(y1, y2));
    const p3 = toFrame(Math.max(x1, x2), Math.max(y1, y2));
    const p4 = toFrame(Math.min(x1, x2), Math.max(y1, y2));
    draft = [p1, p2, p3, p4];
    rectStart = null;
    redraw();
});

// ---------- drawing ----------
function redraw() {
    sizeCanvas();
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // existing zones
    zones.forEach(z => {
        drawPoly(z.points, z.color || "#38bdf8", z.name);
    });

    // draft (high-contrast yellow so it stands out over zones/video)
    if (draft.length) {
        ctx.fillStyle = "rgba(255,212,0,0.30)";
        ctx.strokeStyle = "#ffd400";
        ctx.lineWidth = 3;
        ctx.beginPath();
        draft.forEach((p, i) => {
            const [cx, cy] = toCanvas(p[0], p[1]);
            i === 0 ? ctx.moveTo(cx, cy) : ctx.lineTo(cx, cy);
        });
        if (draft.length > 2) ctx.closePath();
        ctx.fill(); ctx.stroke();
        draft.forEach(p => {
            const [cx, cy] = toCanvas(p[0], p[1]);
            // dark outline + bright fill for visibility on any background
            ctx.fillStyle = "#ffd400";
            ctx.strokeStyle = "#000";
            ctx.lineWidth = 2;
            ctx.beginPath(); ctx.arc(cx, cy, 6, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
        });
    }
}
function drawPoly(points, color, label) {
    if (!points || points.length < 2) return;
    ctx.beginPath();
    points.forEach((p, i) => {
        const [cx, cy] = toCanvas(p[0], p[1]);
        i === 0 ? ctx.moveTo(cx, cy) : ctx.lineTo(cx, cy);
    });
    ctx.closePath();
    ctx.fillStyle = hexA(color, 0.18);
    ctx.strokeStyle = color; ctx.lineWidth = 2;
    ctx.fill(); ctx.stroke();
    if (label) {
        const [lx, ly] = toCanvas(points[0][0], points[0][1]);
        ctx.fillStyle = color; ctx.font = "13px sans-serif";
        ctx.fillText(label, lx + 6, ly + 16);
    }
}
function hexA(hex, a) {
    const h = (hex || "#38bdf8").replace("#", "");
    const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${a})`;
}

// ---------- data ----------
async function loadCameras() {
    const cams = await API.get("/api/sources");
    const sel = document.getElementById("zone-camera");
    sel.innerHTML = cams.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
    sel.addEventListener("change", () => selectCamera(parseInt(sel.value, 10)));
    if (cams.length) selectCamera(cams[0].id);
}

async function selectCamera(id) {
    cameraId = id;
    frozen = false;              // new camera -> resume live preview
    updateFreezeBtn();
    // ensure frames exist for the snapshot background
    API.post(`/api/sources/${id}/start`).catch(() => {});
    refreshBg();
    await loadZones();
    loadMetrics();
    loadJourney();
}

function refreshBg() {
    if (frozen) return;               // keep the frame still while drawing
    if (cameraId) bg.src = `/api/sources/${cameraId}/snapshot?t=${Date.now()}`;
}

function updateFreezeBtn() {
    const btn = document.getElementById("freeze-btn");
    if (!btn) return;
    if (frozen) {
        btn.textContent = "▶ Live";
        btn.classList.remove("btn-outline"); btn.classList.add("btn");
    } else {
        btn.textContent = "⏸ Freeze Frame";
        btn.classList.remove("btn"); btn.classList.add("btn-outline");
    }
}

function toggleFreeze() {
    frozen = !frozen;
    updateFreezeBtn();
    if (!frozen) refreshBg();         // grab a fresh frame when going live again
    const hint = document.getElementById("zone-hint");
    if (hint) hint.textContent = frozen
        ? "Frame frozen — draw your zone, then Save."
        : "Pick a tool, click to draw, then Save.";
}
window.toggleFreeze = toggleFreeze;

async function loadZones() {
    zones = await API.get(`/api/cameras/${cameraId}/zones`);
    // zone list table
    const body = document.querySelector("#zone-list tbody");
    body.innerHTML = zones.length ? zones.map(z => `
        <tr>
            <td><span style="color:${z.color}">●</span> ${z.name}</td>
            <td>${z.kind}</td>
            <td>${z.live_count || 0}</td>
            <td><button class="btn-outline" onclick="deleteZone(${z.id})">✕</button></td>
        </tr>`).join("") : '<tr><td colspan="4" class="muted">No zones — draw one.</td></tr>';
    redraw();
}

async function saveZone() {
    if (draft.length < 3) { alert("Draw at least 3 points (polygon) or a rectangle."); return; }
    const name = document.getElementById("zone-name").value.trim();
    if (!name) { alert("Zone name required"); return; }
    const payload = {
        name,
        shape: tool === "rect" ? "rect" : "polygon",
        points: draft,
        kind: document.getElementById("zone-kind").value,
        color: document.getElementById("zone-color").value,
    };
    await API.post(`/api/cameras/${cameraId}/zones`, payload);
    document.getElementById("zone-name").value = "";
    clearDraft();
    loadZones();
}

async function deleteZone(zoneId) {
    if (!confirm("Delete this zone?")) return;
    await API.del(`/api/zones/${zoneId}`);
    loadZones();
}

// ---------- metrics + charts ----------
function initCharts() {
    const opts = {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: "#94a3b8" } }, y: { ticks: { color: "#94a3b8" }, beginAtZero: true } },
    };
    popChart = new Chart(document.getElementById("popChart"),
        { type: "bar", data: { labels: [], datasets: [{ data: [], backgroundColor: "#38bdf8", borderRadius: 4 }] }, options: opts });
    dwellChart = new Chart(document.getElementById("dwellChart"),
        { type: "bar", data: { labels: [], datasets: [{ data: [], backgroundColor: "#00ff99", borderRadius: 4 }] }, options: opts });
    hourlyChart = new Chart(document.getElementById("hourlyChart"),
        { type: "line", data: { labels: [], datasets: [{ data: [], borderColor: "#f59e0b", backgroundColor: "rgba(245,158,11,.15)", fill: true, tension: 0.3 }] }, options: opts });
}

async function loadMetrics() {
    const d = await API.get(`/api/cameras/${cameraId}/zones/metrics`);
    const body = document.querySelector("#zone-metrics tbody");
    body.innerHTML = d.zones.length ? d.zones.map(z => `
        <tr><td>${z.name}</td><td>${z.total_visits}</td><td>${z.unique_visitors}</td>
        <td>${z.avg_dwell}</td><td>${z.max_dwell}</td><td>${z.revisits}</td></tr>`).join("")
        : '<tr><td colspan="6" class="muted">No visits recorded yet — run the camera.</td></tr>';

    const names = d.zones.map(z => z.name);
    popChart.data.labels = names;
    popChart.data.datasets[0].data = d.zones.map(z => z.total_visits);
    popChart.update();
    dwellChart.data.labels = names;
    dwellChart.data.datasets[0].data = d.zones.map(z => z.avg_dwell);
    dwellChart.update();
    hourlyChart.data.labels = d.hourly.labels;
    hourlyChart.data.datasets[0].data = d.hourly.visits;
    hourlyChart.update();
}

async function loadJourney() {
    const d = await API.get(`/api/cameras/${cameraId}/zones/journey`);
    document.getElementById("common-paths").innerHTML = d.common_paths.length
        ? d.common_paths.map(p => `<div class="journey-node" style="margin:4px 0;display:block;">${p.path} <b>(${p.count})</b></div>`).join("")
        : '<p class="muted">No multi-zone journeys yet.</p>';
    document.getElementById("least-visited").innerHTML = d.least_visited.length
        ? d.least_visited.map(z => `<span class="badge medium" style="margin:3px;">${z.zone}: ${z.count}</span>`).join("")
        : '<p class="muted">—</p>';
    const maxF = Math.max(1, ...d.funnel.map(f => f.count));
    document.getElementById("funnel").innerHTML = d.funnel.map(f => `
        <div class="zone-bar">
            <div class="label"><span>${f.stage}</span><span>${f.count}</span></div>
            <div class="track"><div class="fill" style="width:${(f.count / maxF) * 100}%"></div></div>
        </div>`).join("");
}

// ---------- boot ----------
window.addEventListener("load", () => {
    initCharts();
    loadCameras();
    setTool("polygon");
    setInterval(refreshBg, 900);
    setInterval(() => { if (cameraId) { loadZones(); loadMetrics(); loadJourney(); } }, 5000);
});
