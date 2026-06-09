"""
=====================================================
AI Retail Footfall & Consumer Analytics Platform
Application Factory
=====================================================

Creates the Flask application, wires Flask-SocketIO for
real-time push, initializes the database, and registers
every blueprint (pages + REST API + streaming).

Real-time delivery uses Socket.IO (see backend/websocket).
The legacy polling endpoints are kept intact as a fallback
so the dashboard works even if a websocket cannot connect.
"""

from flask import Flask
from flask_cors import CORS
from flask_socketio import SocketIO

# =====================================
# BLUEPRINTS
# =====================================

from backend.routes.dashboard_routes import dashboard_bp
from backend.routes.stream_routes import stream_bp
from backend.routes.analytics_routes import analytics_bp
from backend.routes.api_routes import api_bp
from backend.routes.report_routes import report_bp
from backend.routes.source_routes import source_bp
from backend.routes.zone_routes import zone_bp
from backend.routes.heatmap_routes import heatmap_bp
from backend.routes.customer_routes import customer_bp
from backend.routes.settings_routes import settings_bp

# =====================================
# WEBSOCKET + DATABASE
# =====================================

from backend.websocket.socket_events import register_socket_events
from backend.database.init_db import init_database
from backend.database.db_writer import db_writer

# =====================================
# GLOBAL SOCKETIO INSTANCE
# =====================================
# threading async mode is used (not eventlet) because the
# MJPEG video generator and the torch/cv2 pipeline are
# blocking; threading avoids monkey-patch conflicts.

socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode="threading"
)


def create_app():

    app = Flask(__name__)

    app.config["SECRET_KEY"] = "ai-retail-analytics-secret"

    # =====================================
    # CORS
    # =====================================

    CORS(app)

    # =====================================
    # DATABASE
    # =====================================

    init_database()

    # start the batched async DB writer (used by concurrent workers)
    db_writer.start()

    # =====================================
    # REGISTER BLUEPRINTS
    # =====================================

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(stream_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(source_bp)
    app.register_blueprint(zone_bp)
    app.register_blueprint(heatmap_bp)
    app.register_blueprint(customer_bp)
    app.register_blueprint(settings_bp)

    # =====================================
    # SOCKETIO
    # =====================================

    socketio.init_app(app)

    register_socket_events(socketio)

    return app



