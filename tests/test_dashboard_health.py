from datetime import datetime
import re

from models import HindsightSync, Incident, PostMortem, db


def _incident(title, *, demo=False, status="Resolved", sync=None, retained_at=None, has_postmortem=True):
    item = Incident(
        title=title, service="payments", status=status, is_demo=demo,
        summary="Synthetic test incident", evidence="",
    )
    db.session.add(item)
    db.session.flush()
    if status == "Resolved" and has_postmortem:
        db.session.add(PostMortem(
            incident_id=item.id,
            confirmed_root_cause="Pool saturation",
            actual_resolution="Released stalled sessions",
        ))
    if sync:
        db.session.add(HindsightSync(
            incident_id=item.id, status=sync, content_hash="test",
            retained_at=retained_at,
        ))
    return item


def test_dashboard_counts_local_and_real_hindsight_states_separately(client, app):
    with app.app_context():
        _incident("Retained", sync="retained", retained_at=datetime(2026, 11, 6, 12, 30))
        _incident("Failed stale timestamp", sync="failed", retained_at=datetime(2030, 1, 1))
        _incident("Pending", sync="pending")
        _incident("Not submitted")
        _incident("Resolved without postmortem", status="Resolved", has_postmortem=False)
        _incident("Investigating", status="Investigating")
        _incident("Demo retained", demo=True, sync="retained", retained_at=datetime(2026, 11, 7))
        _incident("Demo local", demo=True)
        db.session.commit()

    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert re.search(r"TOTAL INCIDENTS</label><b>(\d+)</b>", html).group(1) == "8"
    assert re.search(r"LOCAL POST-MORTEMS</label><b class=\"cyan\">(\d+)</b>", html).group(1) == "6"
    assert re.search(r"HINDSIGHT RETAINED</label><b class=\"cyan\">(\d+)</b>", html).group(1) == "1"
    assert "Pending retention</span><b>1</b>" in html
    assert "Failed retention</span><b>1</b>" in html
    assert "Not submitted</span><b>1</b>" in html
    assert "Nov 06, 2026 · 12:30 UTC" in html
    assert "Jan 01, 2030" not in html
    assert "HINDSIGHT UNKNOWN" in html
    assert "Demo records are excluded" in html


def test_health_reports_dependencies_without_exposing_groq_key(client, app, monkeypatch):
    import app as app_module

    app.config["GROQ_API_KEY"] = "secret-test-marker"
    monkeypatch.setattr(app_module, "check_hindsight_health", lambda: {
        "status": "unavailable", "message": "Hindsight did not respond to its health check."
    })
    response = client.get("/health")
    body = response.get_json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["status"] == "healthy"
    assert body["dependencies"]["database"] == {"status": "connected", "type": "sqlite"}
    assert body["dependencies"]["hindsight"]["status"] == "unavailable"
    assert body["dependencies"]["groq"] == {"status": "configured", "availability": "not_checked"}
    assert "secret-test-marker" not in response.get_data(as_text=True)


def test_dashboard_hindsight_unavailable_does_not_hide_local_index(client, app, monkeypatch):
    from routes import dashboard

    with app.app_context():
        _incident("Local only", sync="failed")
        db.session.commit()
    monkeypatch.setattr(dashboard, "check_hindsight_health", lambda: {
        "status": "disconnected", "message": "Hindsight is not accepting connections."
    })
    html = client.get("/").get_data(as_text=True)
    assert "HINDSIGHT DISCONNECTED" in html
    assert "Hindsight is not accepting connections." in html
    assert "LOCAL POST-MORTEMS" in html


def test_health_optional_hindsight_failure_keeps_application_available(client, monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "check_hindsight_health", lambda: {
        "status": "unknown", "message": "Hindsight status could not be determined."
    })
    body = client.get("/health").get_json()
    assert body["ok"] is True
    assert body["dependencies"]["hindsight"]["status"] == "unknown"

