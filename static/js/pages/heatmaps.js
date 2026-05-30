// =====================================================
// Heatmap Analytics — live + historical density
// =====================================================

const FW = 1280, FH = 720;
let hmCamera = null;
let hmMode = "live";
let zoneDensityChart, hmHourlyChart;

// ---- live decaying-heatmap accumulation grid ----
const GW = 192, GH = 108;          // accumulation grid (16:9)
const DECAY = 0.93;                // per-tick decay (older activity fades over ~secs)
const HEAT_MAX = 3.5;              // intensity that maps to "hottest" (red)
const STAMP = 1.3;                 // intensity added per person per tick
let heatBuf = null;                // Float32Array(GW*GH)

const hmCanvas = document.getElementById("hm-canvas");
const hmBg = document.getElementById("hm-bg");
const hmCtx = hmCanvas.getContext("2d");

// ---- heat colour ramp (blue→green→yellow→red) ----
function heatColor(t) {
    t = Math.max(0, Math.min(1, t));
    const stops = [[37, 99, 235], [34, 197, 94], [234, 179, 8], [239, 68, 68]];
    const seg = t * (stops.length - 1), i = Math.floor(seg), f = seg - i;
    const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)];
    return [Math.round(a[0] + (b[0] - a[0]) * f),
            Math.round(a[1] + (b[1] - a[1]) * f),
            Math.round(a[2] + (b[2] - a[2]) * f)];
}

function renderHeatmap(points) {
    const w = hmCanvas.clientWidth || 640;
    const h = Math.round(w * FH / FW);
    hmCanvas.width = w; hmCanvas.height = h; hmCanvas.style.height = h + "px";
    hmCtx.clearRect(0, 0, w, h);
    if (!points || !points.length) return;

    // 1) accumulate with smaller soft blobs (tighter hotspots)
    const off = document.createElement("canvas");
    off.width = w; off.height = h;
    const octx = off.getContext("2d");
    octx.globalCompositeOperation = "lighter";
    const radius = Math.max(6, w * 0.014);   // 50% smaller hotspots
    for (const p of points) {
        const x = p.x * w / FW, y = p.y * h / FH;
        const g = octx.createRadialGradient(x, y, 0, x, y, radius);
        g.addColorStop(0, "rgba(255,255,255,0.10)");
        g.addColorStop(1, "rgba(255,255,255,0)");
        octx.fillStyle = g;
        octx.beginPath(); octx.arc(x, y, radius, 0, Math.PI * 2); octx.fill();
    }

    // 2) light blur -> smooth but keeps hotspots tight
    hmCtx.filter = `blur(${Math.max(3, w * 0.008)}px)`;
    hmCtx.drawImage(off, 0, 0);
    hmCtx.filter = "none";

    // 3) FULL-COVERAGE colour map driven by DENSITY:
    //    low density stays blue/light, only genuinely busy spots go red.
    const img = hmCtx.getImageData(0, 0, w, h);
    const d = img.data;
    let max = 1;
    for (let i = 0; i < d.length; i += 4) if (d[i] > max) max = d[i];
    for (let i = 0; i < d.length; i += 4) {
        // gamma > 1 suppresses low/mid density -> they remain cool (blue/green);
        // red only appears where density is genuinely high.
        const t = Math.pow(d[i] / max, 1.6);
        const [r, g, b] = heatColor(t);
        d[i] = r; d[i + 1] = g; d[i + 2] = b;
        // light/translucent for low density, stronger for hotspots
        d[i + 3] = Math.round((0.25 + 0.55 * t) * 255);
    }
    hmCtx.putImageData(img, 0, 0);
}

// =====================================================
// LIVE decaying heatmap (TangoEye-style)
// Each tick: decay the whole grid, stamp current people
// positions, then recolour. Old activity fades out; colours
// shift from blue->red as a spot gets busier.
// =====================================================

async function tickLive() {
    if (hmMode !== "live" || !hmCamera) return;
    if (!heatBuf) heatBuf = new Float32Array(GW * GH);

    // 1) decay everything (previous state fades with time)
    for (let i = 0; i < heatBuf.length; i++) heatBuf[i] *= DECAY;

    // 2) stamp current positions
    let pos = [];
    try {
        const d = await API.get(`/api/cameras/${hmCamera}/heatmap/live_positions`);
        pos = d.positions || [];
    } catch (e) { /* keep decaying */ }

    for (const p of pos) {
        const gx = Math.floor(p.x * GW / FW);
        const gy = Math.floor(p.y * GH / FH);
        for (let dy = -3; dy <= 3; dy++) {
            for (let dx = -3; dx <= 3; dx++) {
                const x = gx + dx, y = gy + dy;
                if (x < 0 || y < 0 || x >= GW || y >= GH) continue;
                heatBuf[y * GW + x] += STAMP * Math.exp(-(dx * dx + dy * dy) / 6);
            }
        }
    }

    renderBuffer();
}

function renderBuffer() {
    const w = hmCanvas.clientWidth || 640;
    const h = Math.round(w * FH / FW);
    hmCanvas.width = w; hmCanvas.height = h; hmCanvas.style.height = h + "px";

    // paint the grid into a small canvas, then scale up with blur for smoothness
    const small = document.createElement("canvas");
    small.width = GW; small.height = GH;
    const sctx = small.getContext("2d");
    const img = sctx.createImageData(GW, GH);
    const d = img.data;
    for (let i = 0; i < heatBuf.length; i++) {
        const t = Math.min(1, heatBuf[i] / HEAT_MAX);
        const o = i * 4;
        if (t <= 0.02) { d[o + 3] = 0; continue; }
        const [r, g, b] = heatColor(t);
        d[o] = r; d[o + 1] = g; d[o + 2] = b;
        d[o + 3] = Math.round(Math.min(0.62, 0.12 + t * 0.65) * 255);
    }
    sctx.putImageData(img, 0, 0);

    hmCtx.clearRect(0, 0, w, h);
    hmCtx.imageSmoothingEnabled = true;
    hmCtx.filter = `blur(${Math.max(3, w * 0.012)}px)`;
    hmCtx.drawImage(small, 0, 0, w, h);
    hmCtx.filter = "none";
}

// ---- charts ----
function initHmCharts() {
    const opts = {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: { x: { ticks: { color: "#94a3b8" } }, y: { ticks: { color: "#94a3b8" }, beginAtZero: true } },
    };
    zoneDensityChart = new Chart(document.getElementById("zoneDensityChart"),
        { type: "bar", data: { labels: [], datasets: [{ data: [], backgroundColor: "#ef4444", borderRadius: 4 }] }, options: opts });
    hmHourlyChart = new Chart(document.getElementById("hmHourlyChart"),
        { type: "line", data: { labels: [], datasets: [{ data: [], borderColor: "#38bdf8", backgroundColor: "rgba(56,189,248,.15)", fill: true, tension: 0.3 }] }, options: opts });
}

// ---- data ----
async function loadCameras() {
    const cams = await API.get("/api/sources");
    const sel = document.getElementById("hm-camera");
    sel.innerHTML = cams.map(c => `<option value="${c.id}">${c.name}</option>`).join("");
    sel.addEventListener("change", () => selectCamera(parseInt(sel.value, 10)));
    if (cams.length) selectCamera(cams[0].id);
}

function selectCamera(id) {
    hmCamera = id;
    API.post(`/api/sources/${id}/start`).catch(() => {});
    grabReference();          // always show a background frame
    loadHeatmap();
}
// live mode keeps the background fresh
function refreshBg() {
    if (hmMode !== "live") return;     // historical uses a frozen reference frame
    if (hmCamera) hmBg.src = `/api/sources/${hmCamera}/snapshot?t=${Date.now()}`;
}
// capture a single reference snapshot (used as historical background)
function grabReference() {
    if (hmCamera) hmBg.src = `/api/sources/${hmCamera}/snapshot?t=${Date.now()}`;
}

async function loadHeatmap() {
    if (!hmCamera) return;
    const range = document.getElementById("hm-range").value;
    const d = await API.get(`/api/cameras/${hmCamera}/heatmap?mode=${hmMode}&range=${range}`);

    // historical = static density over the frozen reference frame.
    // live = driven by the decaying tickLive() loop (don't overwrite here).
    if (hmMode === "historical") {
        renderHeatmap(d.points);
    }

    document.getElementById("m-total").innerText = d.metrics.total_points;
    document.getElementById("m-peak").innerText = d.metrics.peak_density;
    document.getElementById("m-avg").innerText = d.metrics.avg_density;
    document.getElementById("m-hot").innerText =
        d.metrics.hot_zones[0] ? `${d.metrics.hot_zones[0].zone}` : "—";
    document.getElementById("m-cold").innerText =
        d.metrics.cold_zones[0] ? `${d.metrics.cold_zones[0].zone}` : "—";

    zoneDensityChart.data.labels = d.zone_density.map(z => z.zone);
    zoneDensityChart.data.datasets[0].data = d.zone_density.map(z => z.count);
    zoneDensityChart.update();

    hmHourlyChart.data.labels = d.hourly.labels;
    hmHourlyChart.data.datasets[0].data = d.hourly.counts;
    hmHourlyChart.update();
}

// ---- mode tabs ----
document.getElementById("mode-live").addEventListener("click", () => setMode("live"));
document.getElementById("mode-historical").addEventListener("click", () => setMode("historical"));
function setMode(m) {
    hmMode = m;
    document.getElementById("mode-live").classList.toggle("active", m === "live");
    document.getElementById("mode-historical").classList.toggle("active", m === "historical");
    document.getElementById("hm-range").style.display = m === "historical" ? "inline-block" : "none";
    if (m === "historical") {
        grabReference();   // freeze one reference frame to overlay history onto
    } else {
        heatBuf = null;    // start the live decay buffer fresh
        refreshBg();       // resume live background
    }
    loadHeatmap();
}
document.getElementById("hm-range").addEventListener("change", loadHeatmap);

// ---- boot ----
window.addEventListener("load", () => {
    initHmCharts();
    loadCameras();
    // live: refresh background + metrics/charts periodically
    setInterval(() => { if (hmMode === "live") { refreshBg(); loadHeatmap(); } }, 2500);
    // live: decaying heatmap accumulation runs faster for a smooth, evolving feel
    setInterval(tickLive, 600);
});
