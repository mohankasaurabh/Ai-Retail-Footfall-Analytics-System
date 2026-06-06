// =====================================================
// Heatmap Analytics — live + historical density
// =====================================================

const FW = 1280, FH = 720;
let hmCamera = null;
let hmMode = "live";
let zoneDensityChart, hmHourlyChart;

// ---- live decaying-heatmap accumulation grid ----
const GW = 192, GH = 108;          // accumulation grid (16:9)
const DECAY = 0.92;                // per-tick decay (trail cools red->blue over ~secs)
const HEAT_MAX = 2.5;              // intensity that maps to "hottest" (red)
const STAMP = 5.0;                 // over-stamp (clamped) -> solid RED core at current spot
let heatBuf = null;                // Float32Array(GW*GH)

const hmCanvas = document.getElementById("hm-canvas");
const hmBg = document.getElementById("hm-bg");
const hmCtx = hmCanvas.getContext("2d");

// ---- heat colour ramp (blue→green→yellow→red) ----
function _ramp(stops, t) {
    t = Math.max(0, Math.min(1, t));
    const seg = t * (stops.length - 1), i = Math.floor(seg), f = seg - i;
    const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)];
    return [Math.round(a[0] + (b[0] - a[0]) * f),
            Math.round(a[1] + (b[1] - a[1]) * f),
            Math.round(a[2] + (b[2] - a[2]) * f)];
}

// live heatmap ramp (blue -> red)
function heatColor(t) {
    return _ramp([[37, 99, 235], [34, 197, 94], [234, 179, 8], [239, 68, 68]], t);
}

// JET-style colormap for the historical map (Ultralytics look):
// blue -> cyan -> green -> yellow -> orange -> red
function heatColorJet(t) {
    return _ramp([
        [0, 0, 255], [0, 200, 255], [0, 255, 120],
        [200, 255, 0], [255, 160, 0], [255, 0, 0],
    ], t);
}

function renderHeatmap(points) {
    const w = hmCanvas.clientWidth || 640;
    const h = Math.round(w * FH / FW);
    hmCanvas.width = w; hmCanvas.height = h; hmCanvas.style.height = h + "px";
    hmCtx.clearRect(0, 0, w, h);
    if (!points || !points.length) return;

    // 1) accumulate into a FLOAT grid (no 8-bit clipping) so dense corridors
    //    keep a true gradient instead of saturating to solid red.
    const GW = 256, GH = Math.round(GW * FH / FW);
    const buf = new Float32Array(GW * GH);
    for (const p of points) {
        const gx = Math.round(p.x * GW / FW);
        const gy = Math.round(p.y * GH / FH);
        for (let dy = -4; dy <= 4; dy++) {
            for (let dx = -4; dx <= 4; dx++) {
                const x = gx + dx, y = gy + dy;
                if (x < 0 || y < 0 || x >= GW || y >= GH) continue;
                buf[y * GW + x] += Math.exp(-(dx * dx + dy * dy) / 10);
            }
        }
    }
    let max = 1;
    for (let i = 0; i < buf.length; i++) if (buf[i] > max) max = buf[i];

    // 2) colour the small grid with the JET ramp (blue->...->red),
    //    transparent where there is no traffic
    const small = document.createElement("canvas");
    small.width = GW; small.height = GH;
    const sctx = small.getContext("2d");
    const img = sctx.createImageData(GW, GH);
    const d = img.data;
    for (let i = 0; i < buf.length; i++) {
        const o = i * 4;
        const norm = buf[i] / max;
        if (norm < 0.02) { d[o + 3] = 0; continue; }   // no traffic -> clear
        const t = Math.pow(norm, 0.85);                 // spread the gradient
        const [r, g, b] = heatColorJet(t);
        d[o] = r; d[o + 1] = g; d[o + 2] = b;
        d[o + 3] = Math.round(Math.min(0.82, 0.4 + 0.45 * t) * 255);
    }
    sctx.putImageData(img, 0, 0);

    // 3) scale up with blur -> smooth continuous trails (Ultralytics look)
    hmCtx.imageSmoothingEnabled = true;
    hmCtx.filter = `blur(${Math.max(4, w * 0.012)}px)`;
    hmCtx.drawImage(small, 0, 0, w, h);
    hmCtx.filter = "none";
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
                const idx = y * GW + x;
                // clamp so a current spot pins to RED and starts cooling the
                // instant the person moves on (clean comet trail)
                heatBuf[idx] = Math.min(
                    HEAT_MAX, heatBuf[idx] + STAMP * Math.exp(-(dx * dx + dy * dy) / 6));
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
        // JET ramp: current spot red -> trail cools orange/yellow/green/blue
        const [r, g, b] = heatColorJet(t);
        d[o] = r; d[o + 1] = g; d[o + 2] = b;
        d[o + 3] = Math.round(Math.min(0.78, 0.2 + t * 0.6) * 255);
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
// live mode keeps the background fresh (clean = un-annotated, no zone boxes)
function refreshBg() {
    if (hmMode !== "live") return;     // historical uses a frozen reference frame
    if (hmCamera) hmBg.src = `/api/sources/${hmCamera}/snapshot?clean=1&t=${Date.now()}`;
}
// capture a single clean reference snapshot (used as historical background)
function grabReference() {
    if (hmCamera) hmBg.src = `/api/sources/${hmCamera}/snapshot?clean=1&t=${Date.now()}`;
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
