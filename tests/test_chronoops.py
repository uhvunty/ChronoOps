import json
from models import Incident, PostMortem, db
from services.ai_service import _validate, analyze
from services.incident_memory import retrieve_similar
from services.log_analyzer import parse_logs


def test_startup_database_and_dashboard(client):
    assert client.get("/health").json["ok"] is True
    assert b"TOTAL INCIDENTS" in client.get("/").data


def test_text_json_and_otel_log_ingestion():
    text = parse_logs('2026-01-01T00:00:00Z ERROR service=api connection refused\nINFO service=api retry')
    assert text["counts"]["ERROR"] == 1
    assert text["services"] == ["api"]
    structured = parse_logs(json.dumps({"events": [{"timestamp": "2026-01-01T00:00:00Z", "level": "ERROR", "service": "db", "message": "pool exhausted"}]}))
    assert structured["events"][0]["service"] == "db"
    from services.log_analyzer import otel_event_adapter
    assert otel_event_adapter({"severity_text": "ERROR", "body": "failed", "attributes": {"service.name": "api"}})["service"] == "api"


def test_incident_analysis_feedback_resolution_and_persistent_memory(client, app):
    payload = {"title": "Checkout pool issue", "logs": "2026-01-01T00:00:00Z ERROR service=checkout-api pool exhausted\n2026-01-01T00:00:01Z ERROR service=checkout-api acquire connection timeout"}
    response = client.post("/incidents/", data=payload, follow_redirects=True)
    assert b"Local fallback analysis" in response.data
    with app.app_context():
        incident = Incident.query.first()
    assert incident is not None
    feedback = client.post(f"/incidents/{incident.id}/feedback", data={"hypothesis": "Connections are exhausted", "verdict": "confirmed", "notes": "verified metrics"})
    assert feedback.status_code == 302
    pm = {"confirmed_root_cause": "Long-running queries consumed all pool slots.", "actual_resolution": "Reviewed sessions and cleared confirmed stuck queries.", "recovery_outcome": "Pool wait returned to baseline.", "lessons_learned": "Watch pool wait time."}
    assert client.post(f"/incidents/{incident.id}/postmortem", data=pm).status_code == 302
    with app.app_context():
        resolved = Incident.query.get(incident.id)
        assert resolved.status == "Resolved" and resolved.postmortem
        match = retrieve_similar("billing database pool acquire timeout", [resolved])
        assert match and match[0]["score"] > 0
        old_id = resolved.id
    restart = __import__("app").create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": app.config["SQLALCHEMY_DATABASE_URI"], "GROQ_API_KEY": ""})
    with restart.app_context():
        restored = Incident.query.get(old_id)
        assert restored.postmortem.actual_resolution == pm["actual_resolution"]


def test_demo_seed_and_safe_reset(client, app):
    client.post("/demo/seed")
    with app.app_context():
        assert Incident.query.filter_by(is_demo=True).count() >= 4
    client.post("/incidents/", data={"logs": "ERROR service=real something broke"})
    client.post("/demo/reset")
    with app.app_context():
        assert Incident.query.filter_by(is_demo=True).count() == 0
        assert Incident.query.filter_by(is_demo=False).count() == 1


def test_local_analysis_is_validated_without_network():
    parsed = parse_logs("ERROR service=db pool exhausted")
    result, source = analyze(parsed, [], {"GROQ_API_KEY": "", "MAX_CONTEXT_CHARS": 1000})
    assert source == "local_fallback"
    assert result["suspected_causes"]
    assert 0 <= result["suspected_causes"][0]["confidence"] <= 1


def test_invalid_ai_structure_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        _validate({"suspected_causes": "not a list"})


def test_api_failure_falls_back_explicitly(monkeypatch):
    import requests
    from services import ai_service
    monkeypatch.setattr(ai_service.requests, "post", lambda *args, **kwargs: (_ for _ in ()).throw(requests.Timeout()))
    result, source = ai_service.analyze(parse_logs("ERROR service=api gateway timeout"), [], {"GROQ_API_KEY": "configured", "GROQ_MODEL": "test", "MAX_CONTEXT_CHARS": 1000, "MAX_COMPLETION_TOKENS": 20})
    assert source == "local_fallback"
    assert result["suspected_causes"]



def test_hindsight_memories_are_used_by_local_fallback():
    parsed = parse_logs("ERROR service=auth-api database connection pool exhausted")
    memory = {"text": "Verified prior incident: stale database connections exhausted the pool; recovery released stale connections."}
    result, source = analyze(
        parsed,
        [],
        {"GROQ_API_KEY": "", "MAX_CONTEXT_CHARS": 1000},
        hindsight_memories=[memory],
    )
    assert source == "local_fallback"
    assert result["historical_influence"]
    assert "Hindsight" in result["historical_influence"][0]["source"]
    assert any("Hindsight post-mortems" in item for item in result["recommendations"])
