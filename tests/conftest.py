import os

# Avoid loading a developer's .env while importing the app for tests.
os.environ["PYTHON_DOTENV_DISABLED"] = "1"

import pytest
from app import create_app
from models import db


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}", "WTF_CSRF_ENABLED": False, "GROQ_API_KEY": ""})
    with app.app_context():
        db.create_all()
    yield app
    with app.app_context():
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()



@pytest.fixture(autouse=True)
def isolate_external_services(monkeypatch):
    """Keep ordinary tests offline and out of real Hindsight/Groq services."""
    from routes import incidents as incident_routes
    from routes import dashboard as dashboard_routes
    import app as app_module
    from services import ai_service

    monkeypatch.setattr(
        incident_routes,
        "recall_incidents",
        lambda query, limit=5: {
            "success": True,
            "status": "success_empty",
            "memories": [],
            "message": "Test stub",
        },
    )
    offline_health = lambda: {"status": "unknown", "message": "Hindsight health probe disabled in offline tests."}
    monkeypatch.setattr(dashboard_routes, "check_hindsight_health", offline_health)
    monkeypatch.setattr(app_module, "check_hindsight_health", offline_health)
    monkeypatch.setattr(
        incident_routes,
        "retain_incident",
        lambda **kwargs: {"success": True, "message": "Test stub retained"},
    )

    def reject_groq_network(*args, **kwargs):
        raise AssertionError("Tests must not send network requests to Groq")

    monkeypatch.setattr(ai_service.requests, "post", reject_groq_network)
