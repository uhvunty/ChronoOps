import json
import os
from flask import Flask, flash, redirect, render_template, url_for
from dotenv import load_dotenv
load_dotenv()
from config import Config
from models import db
from routes.dashboard import bp as dashboard_bp
from routes.incidents import bp as incidents_bp
from routes.runbooks import bp as runbooks_bp
from services.demo_data import reset_demo, seed_demo

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
        return {"ok": True, "database": "sqlite", "llm": "groq configured" if app.config.get("GROQ_API_KEY") else "local fallback"}
    with app.app_context():
        if not app.testing:
            db.create_all()
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
