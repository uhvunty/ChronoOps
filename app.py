import json
import os
from threading import Lock
from flask import Flask, flash, redirect, render_template, url_for, request
from sqlalchemy import text
from dotenv import load_dotenv
load_dotenv()
from config import Config
from models import db
from routes.dashboard import bp as dashboard_bp
from routes.incidents import bp as incidents_bp
from routes.runbooks import bp as runbooks_bp
from services.demo_data import reset_demo, seed_demo
from services.hindsight_service import check_hindsight_health
import logging

logger = logging.getLogger(__name__)

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    db.init_app(app)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(incidents_bp)
    app.register_blueprint(runbooks_bp)
    app.jinja_env.filters["fromjson"] = lambda value: json.loads(value or "{}")

    # Delay schema initialization until the production app receives a request.
    # Importing this module (including pytest collection) must not touch SQLite.
    schema_lock = Lock()
    schema_initialized = False

    @app.before_request
    def initialize_database_schema():
        nonlocal schema_initialized
        if app.testing or schema_initialized or request.endpoint == "health":
            return
        with schema_lock:
            if not schema_initialized:
                db.create_all()
                schema_initialized = True

    @app.errorhandler(413)
    def too_large(_):
        flash("Upload is larger than the 2 MB limit.", "error")
        return redirect(url_for("incidents.new"))
    @app.post("/demo/seed")
    def demo_seed():
        count = seed_demo()
        flash(f"Demo data ready. Added {count} synthetic incidents; your real incidents were kept.", "success")
        return redirect(url_for("dashboard.index"))
    @app.post("/demo/reset")
    def demo_reset():
        reset_demo()
        flash("Only synthetic demo incidents and demo runbooks were removed.", "success")
        return redirect(url_for("dashboard.index"))
    @app.get("/health")
    def health():
        try:
            db.session.execute(text("SELECT 1"))
            database = {"status": "connected", "type": "sqlite"}
        except Exception:
            logger.exception("Database health check failed")
            db.session.rollback()
            database = {"status": "unavailable", "type": "sqlite"}
        hindsight = check_hindsight_health()
        groq_configured = bool(app.config.get("GROQ_API_KEY"))
        return {
            "ok": True,
            "status": "healthy" if database["status"] == "connected" else "degraded",
            "dependencies": {
                "database": database,
                "hindsight": {"status": hindsight.get("status", "unknown"), "message": hindsight.get("message", "Hindsight status could not be determined.")},
                "groq": {"status": "configured" if groq_configured else "not_configured", "availability": "not_checked"},
            },
        }
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
