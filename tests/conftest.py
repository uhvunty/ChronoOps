import pytest
from app import create_app
from models import db


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}", "WTF_CSRF_ENABLED": False})
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
def isolate_hindsight_calls(monkeypatch):
    """Keep the automated test suite offline and out of the real memory bank."""
    from routes import incidents as incident_routes

    monkeypatch.setattr(
        incident_routes,
        "recall_incidents",
        lambda query, limit=5: {"success": True, "memories": [], "message": "Test stub"},
    )
    monkeypatch.setattr(
        incident_routes,
        "retain_incident",
        lambda **kwargs: {"success": True, "message": "Test stub retained"},
    )
