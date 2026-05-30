# 🛍️ AI Retail Footfall & Consumer Analytics Platform

> Enterprise retail intelligence generated **purely from CCTV cameras** — no
> RFID, no BLE beacons, no floor sensors, no wearables, no mobile apps.
> Inspired by TangoEye, RetailNext, ShopperTrak and Smart-Mall analytics suites.

A modular, multi-page enterprise SaaS platform that turns ordinary camera feeds
(webcam / video file / RTSP / IP / NVR) into real-time business intelligence:
footfall, occupancy, **concurrent multi-camera** monitoring, customer
re-identification, demographics, interactive zone analytics, dwell time, queues,
customer journeys, live + historical heatmaps, reports, alerts and configuration.

---

## ✨ The 8 Modules

| # | Module | Route | Highlights |
|---|--------|-------|-----------|
| 1 | **Camera & Media Sources** | `/sources` | Add/edit/delete CCTV·RTSP·IP·NVR·webcam·video sources, upload clips, per-source **AI model toggles**, start/stop, status |
| 2 | **Executive Dashboard** | `/` | KPI cards, realtime overview (live count, M/F, age), system health, alerts feed, **live snapshot grid** |
| 3 | **Live Monitoring** | `/live` | **Per-camera concurrent** annotated feeds, per-person overlay (`#id Gender Age Zone mm:ss`), live metrics |
| 4 | **Zone Analytics** | `/zones` | **Interactive polygon/rectangle editor**, per-zone dwell/visitors/revisits, journey paths + conversion funnel |
| 5 | **Heatmap Analytics** | `/heatmaps` | **Live decaying** heatmap (fades over time) + **historical full-coverage** density map over a frozen reference frame, range-selectable, hot/cold zones, charts |
| 6 | **Customer Analytics** | `/customers` | Persistent customers, journeys, dwell, **repeat-visitor detection**, demographics (InsightFace + voting) |
| 7 | **Reports & Insights** | `/reports` | Daily/weekly/monthly **CSV / Excel / PDF** exports + summary |
| 8 | **Settings** | `/settings` | AI model defaults, DB backend, camera defaults, ReID threshold/timeout, alert thresholds |

Plus a global **topbar** (store selector · date range · notifications bell · theme toggle · profile)
and a real-time **alert engine** (camera-offline, low-FPS, occupancy, queue congestion).

---

## 🏗️ Architecture

```
                  ┌─────────────────────────────────────────────┐
                  │  MediaSourceService (worker registry)        │
                  │  start / stop / status / snapshots           │
                  └───────────────┬──────────────────────────────┘
                                  │ one daemon thread per ACTIVE source
        ┌─────────────────────────┴───────────────────────────────┐
        ▼                                                           ▼
  CameraWorker(cam 1)                                        CameraWorker(cam N)
  capture → throttle → Pipeline → JPEG/metrics buffers       (runs concurrently)
        │                                                           │
        └───────────────────────┬───────────────────────────────────┘
                                 ▼  per-camera Pipeline
   Detection(YOLO11) → Tracking(ByteTrack) → ReID(OSNet, shared registry, cached)
        → Demographics(InsightFace + voting) → Zones(polygon) → Dwell → Queue
                                 │
            ┌────────────────────┼─────────────────────────────┐
            ▼                    ▼                              ▼
   AnalyticsService        BatchedDBWriter                 AlertService
   (per-camera metrics)    (async, thread-safe)            (threshold checks)
            │                    ▼
            │            SQLite / Postgres / MySQL
            ▼                    ▼
   Flask-SocketIO (live push)  +  REST API (blueprints)
                                 ▼
        SaaS Frontend (base.html shell + per-page modules, Chart.js / ApexCharts)
```

**Frame pipeline:** `Camera → YOLO11 → ByteTrack → OSNet ReID → Identity →
Demographics → Zones → Dwell → Journey → Database → Dashboard`
(heatmaps render on the Heatmaps page from movement data, not baked into the live feed)

### Key design points
- **True concurrent multi-camera:** each active source runs its own worker thread +
  `Pipeline` instance (own tracker/zones/heatmap state). Per-source **FPS throttle** and
  **AI model toggles** keep load manageable.
- **Shared ReID registry** (`global_registry`, thread-locked) links the same person
  **across cameras** (cross-camera / multi-camera customers). ReID is **cached per
  track** and re-matched only periodically (identity is stable) — the main lever that
  keeps the video smooth at a steady throttled FPS.
- **Demographics:** InsightFace (RetinaFace detector + gender/age) run whole-frame,
  mapped to tracks, with **per-ReID confidence-weighted voting** for a stable label.
  (Face-based, so it needs resolvable faces — see Notes.)
- **Live vs historical heatmaps:** the **live** map is a decaying intensity field fed by
  current positions (old activity fades); the **historical** map is a full-coverage,
  density-proportional field rendered over a frozen reference frame.
- **Thread-safe persistence:** workers enqueue rows to a single **batched async writer**
  (no per-frame commits, no shared Session across threads). Lifecycle events
  (customer/zone visits) use scoped sessions on appear/disappear only.
- **Single-tenant ready for multi-tenant:** every table carries `store_id`; a default
  store is seeded. (Auth + real multi-store enforcement is the one deferred phase.)

---

## 🧰 Tech Stack

**Backend:** Python 3.11 · Flask · Flask-SocketIO · SQLAlchemy 2 · SQLite (Postgres/MySQL-ready)
**AI:** Ultralytics YOLO11 · ByteTrack · OSNet (torchreid) · InsightFace (RetinaFace + gender/age, ONNX) · OpenCV · Torch · NumPy · Pandas
**Frontend:** HTML5 · CSS3 · JS · Bootstrap-style theming · Chart.js · ApexCharts · Socket.IO (dark/light)
**Reports:** pandas (CSV) · openpyxl (Excel) · matplotlib (PDF)
**Deploy:** Docker · Docker Compose · Nginx

---

## 📂 Project Structure

```
AI-RETAIL-ANALYTICS/
├── app.py / run.py              # app factory (SocketIO, DB, blueprints) + entry point
├── ai_engine/
│   ├── detection/               # YOLO11 person detection
│   ├── tracking/                # ByteTrack + utils
│   ├── reid/                    # OSNet, feature extractor, shared global identity registry
│   ├── demographics/            # InsightFace engine (gender/age) + per-ReID voting
│   ├── analytics/               # zone_analytics (polygons), dwell_time, heatmap, queue, journey
│   ├── association/             # customer profile / identity / session
│   └── stream/                  # legacy camera_manager / frame_processor (single-cam, retained)
├── backend/
│   ├── routes/                  # dashboard, source, zone, heatmap, customer, analytics,
│   │                            #   report, settings, api, stream
│   ├── services/                # media_source_service, camera_worker, pipeline,
│   │                            #   analytics_service, customer_session, alert_service,
│   │                            #   settings_service, report_service
│   ├── websocket/               # socket_events (metrics/chart push + alert eval)
│   └── database/                # db (scoped sessions), models, repository, db_writer, seed, init_db
├── templates/                   # base.html + 8 module pages + components/ (sidebar, topbar, cards, charts)
├── static/
│   ├── css/                     # style.css (theme), dashboard.css, analytics.css
│   └── js/                      # core/ (api, state), websocket.js, pages/ (one per module)
├── configs/  data/  logs/  reports/  tests/  docker/
```

---

## 🚀 Installation & Run

```bash
python3.11 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# optional: drop a demo clip at data/videos/mall.mp4
python run.py                        # http://localhost:5000
```

First run downloads YOLO11 (`yolo11s.pt`), OSNet weights, and the InsightFace
`buffalo_l` pack automatically. The DB is auto-created and seeded (default store +
3 sources + 4 zones) on startup.

**Database backend** — defaults to SQLite. For Postgres/MySQL set `DATABASE_URL`, e.g.:
```bash
export DATABASE_URL="postgresql+psycopg2://user:pw@host/retail"
```

---

## 🔌 API Reference

### Pages
`/` · `/sources` · `/live` · `/zones` · `/heatmaps` · `/customers` · `/reports` · `/settings`

### Media sources
| Method | Endpoint | Purpose |
|---|---|---|
| GET/POST | `/api/sources` | list (with runtime status) / create |
| GET/PUT/DELETE | `/api/sources/<id>` | read / update / delete |
| POST | `/api/sources/<id>/start` · `/stop` | runtime control |
| GET | `/api/sources/<id>/metrics` | per-camera live metrics |
| GET | `/api/sources/<id>/snapshot` | latest annotated JPEG |
| POST | `/api/sources/upload` | upload MP4/AVI/MOV |
| GET | `/video_feed/<id>` | per-camera MJPEG stream |

### Zones
`GET/POST /api/cameras/<id>/zones` · `PUT/DELETE /api/zones/<zone_id>` ·
`GET /api/cameras/<id>/zones/metrics` · `GET /api/cameras/<id>/zones/journey`

### Heatmaps
`GET /api/cameras/<id>/heatmap?mode=live|historical&range=1h|6h|24h|week|month|all`
`GET /api/cameras/<id>/heatmap/live_positions` — current people positions (drives the live decaying map)

### Customers
`GET /api/customers?range=&camera=` · `GET /api/customers/<id>` ·
`GET /api/customers/demographics` · `GET /api/customers/returning`

### Dashboard / reports / settings / alerts
`GET /api/dashboard` · `GET /api/reports/summary?type=` ·
`GET /api/reports/<daily|weekly|monthly>?fmt=csv|excel|pdf` ·
`GET/PUT /api/settings` · `GET /api/alerts` · `POST /api/alerts/<id>/ack` · `GET /api/stores`

### WebSocket (Socket.IO)
Server pushes `metrics` (aggregate KPIs) and `chart` (history) ~1 Hz; the alert engine
runs each tick. Client may emit `request_metrics`.

> Legacy single-camera endpoints (`/analytics`, `/chart_data`, `/video_feed`,
> `/switch_camera`, `/export/<fmt>`, `/insights` …) are retained for back-compat.

---

## 🗄️ Database Schema

`Store · User(stub) · Camera · Zone · Customer · CustomerVisit · ZoneVisit ·
JourneyStep · DemographicSample · MovementPoint · QueueEvent · AnalyticsSnapshot ·
Alert · Setting · HeatmapBin` (+ legacy `AnalyticsLog`, `MovementLog`).

All analytics tables carry `store_id` / `camera_id`. Tables auto-create + seed on boot.

---

## 🐳 Deployment

```bash
cd docker && docker compose up --build      # app + Nginx reverse proxy
```
Nginx proxies HTTP, the MJPEG streams and the Socket.IO upgrade. Mount `data/` and the
DB volume for persistence. For production run behind Nginx with a proper WSGI worker.

---

## 🧪 Testing

```bash
pytest -q
```

---

## 🛣️ Build History (delivered in phases)

1. **Data & service foundation** — full schema, scoped sessions, batched writer, per-camera analytics
2. **Multi-camera engine** — concurrent workers + per-camera Pipeline + source APIs + per-camera feeds
3. **Frontend shell** — `base.html`, sidebar/topbar, core JS, executive dashboard
4. **Camera Sources** — CRUD, upload, model toggles, status
5. **Zone Analytics** — DB polygons, interactive editor, dwell + journeys + funnel
6. **Heatmap Analytics** — live + historical density, hot/cold zones
7. **Customer Analytics** — persistent customers, visits, returning detection
8. **Reports** — daily/weekly/monthly CSV/Excel/PDF
9. **Settings + Alerts** — persisted config + threshold alert engine

**Post-build refinements:**
- Live Monitoring rebuilt as a per-camera multi-feed grid; heatmap overlay removed from live feeds.
- Demographics moved from Haar+DeepFace → **InsightFace (RetinaFace + gender/age) with per-ReID voting**.
- Heatmaps reworked: **live decaying** map (fades over time) + **historical full-coverage**,
  density-proportional field on a frozen reference frame.
- Zone editor: **Freeze Frame** + click-to-draw fix.
- Performance: **cached ReID**, lighter demographics + YOLO `imgsz`, smoothed/throttled output FPS.

**Deferred:** Phase 10 — authentication + real multi-store enforcement (single-tenant by design today).

---

## ⚠️ Notes

- **Compute:** YOLO+OSNet+InsightFace per concurrent stream is heavy on one machine — mitigated
  by per-source FPS throttle, **cached ReID** (re-match every N frames), demographics-every-N-frames,
  YOLO `imgsz=960`, and per-source model toggles. Output FPS is throttled and smoothed.
  Recommend ≤2–3 active streams on a laptop/CPU.
- **Demographics** use InsightFace (RetinaFace) + per-ReID voting and need **resolvable faces**;
  far-field CCTV crowd footage may yield few/no age/gender samples (a footage limitation, not a
  code issue) — a closer source / entrance cam / webcam populates them. For pure back-view / far
  footage a full-body gender classifier would be the next step (not yet added).
- **Workers run continuously** once started (always-on processing), independent of who is viewing a feed.

## 📸 Screenshots

> _Placeholder — add screenshots of Dashboard, Camera Sources, Live Monitoring,
> Zone Editor, Heatmaps, Customer Analytics, Reports and Settings._
