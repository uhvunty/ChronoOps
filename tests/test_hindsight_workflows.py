import json
from types import SimpleNamespace

import pytest

from models import HindsightSync, Incident, PostMortem, db
from routes import incidents as incident_routes
from services import ai_service, hindsight_service
from services.log_analyzer import parse_logs


def _install_fake_hindsight(
    monkeypatch, *, results=None, recall_error=None, retain_error=None, retain_success=True
):
    calls = {"clients": [], "banks": [], "recalls": [], "retains": []}

    class FakeClient:
        def __init__(self, **kwargs):
            calls["clients"].append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def create_bank(self, **kwargs):
            calls["banks"].append(kwargs)

        def recall(self, **kwargs):
            calls["recalls"].append(kwargs)
            if recall_error:
                raise recall_error
            return SimpleNamespace(results=results)

        def retain(self, **kwargs):
            calls["retains"].append(kwargs)
            if retain_error:
                raise retain_error
            return SimpleNamespace(success=retain_success)

    monkeypatch.setattr(hindsight_service, "Hindsight", FakeClient)
    monkeypatch.setattr(hindsight_service, "_configure_local_no_proxy", lambda: None)
    return calls


def _create_incident(app, *, status="Open", title="Pool wait issue"):
    with app.app_context():
        incident = Incident(
            title=title,
            service="checkout-api",
            status=status,
            summary="Database pool wait time increased.",
            evidence="ERROR service=checkout-api database pool wait timeout",
            symptoms="pool wait timeout",
        )
        db.session.add(incident)
        db.session.flush()
        if status == "Resolved":
            db.session.add(
                PostMortem(
                    incident=incident,
                    confirmed_root_cause="Long-running queries occupied the pool.",
                    actual_resolution="Cleared confirmed stuck sessions.",
                )
            )
        db.session.commit()
        return incident.id


def _verified_postmortem(resolution="Cleared confirmed stuck sessions."):
    return {
        "confirmed_root_cause": "Long-running queries occupied the pool.",
        "actual_resolution": resolution,
        "recovery_outcome": "Pool wait returned to baseline.",
        "lessons_learned": "Watch pool wait time.",
        "verification_confirmed": "1",
    }


def test_hindsight_recall_sends_explicit_timeout_and_token_budget(monkeypatch):
    calls = _install_fake_hindsight(
        monkeypatch,
        results=[SimpleNamespace(text="Earlier verified pool incident.")],
    )
    monkeypatch.setattr(hindsight_service, "HINDSIGHT_TIMEOUT_SECONDS", 12.5)
    monkeypatch.setattr(hindsight_service, "HINDSIGHT_RECALL_MAX_TOKENS", 700)

    result = hindsight_service.recall_incidents("new pool timeout", limit=1)

    assert result["success"] is True
    assert result["status"] == "success_with_memories"
    assert result["memories"] == [{"text": "Earlier verified pool incident."}]
    assert calls["clients"] == [
        {
            "base_url": hindsight_service.HINDSIGHT_URL,
            "timeout": 12.5,
            "user_agent": "chronoops-incident-response/1.0",
        }
    ]
    assert calls["recalls"][0]["max_tokens"] == 700
    assert calls["recalls"][0]["query"] == "new pool timeout"


def test_hindsight_recall_empty_is_success_not_unavailable(monkeypatch):
    _install_fake_hindsight(monkeypatch, results=[])

    result = hindsight_service.recall_incidents("unseen failure")

    assert result["success"] is True
    assert result["status"] == "success_empty"
    assert result["memories"] == []


def test_hindsight_recall_failure_is_safe_and_logged(monkeypatch, caplog):
    _install_fake_hindsight(
        monkeypatch,
        recall_error=RuntimeError("internal endpoint detail"),
    )

    result = hindsight_service.recall_incidents("pool failure")

    assert result["success"] is False
    assert result["status"] == "unavailable"
    assert result["memories"] == []
    assert "internal endpoint detail" not in result["message"]
    assert "internal endpoint detail" in caplog.text


def test_hindsight_retain_uses_stable_document_replace(monkeypatch):
    calls = _install_fake_hindsight(monkeypatch)
    monkeypatch.setattr(hindsight_service, "HINDSIGHT_TIMEOUT_SECONDS", 9.0)

    result = hindsight_service.retain_incident(
        incident_id="INC-0007",
        title="Pool wait",
        service="checkout-api",
        severity="High",
        root_cause="Long-running queries occupied the pool.",
        resolution="Cleared confirmed stuck sessions.",
        lessons="Watch pool wait time.",
    )

    assert result["success"] is True
    assert calls["clients"][0]["timeout"] == 9.0
    assert calls["retains"][0]["document_id"] == "chronoops-INC-0007"
    assert calls["retains"][0]["update_mode"] == "replace"
    assert "VERIFIED CHRONOOPS INCIDENT POST-MORTEM" in calls["retains"][0]["content"]


def test_hindsight_retain_failure_returns_safe_result(monkeypatch, caplog):
    _install_fake_hindsight(monkeypatch, retain_error=RuntimeError("internal retain detail"))

    result = hindsight_service.retain_incident(
        incident_id="INC-0008",
        title="Pool wait",
        service="checkout-api",
        severity="High",
        root_cause="Long-running queries occupied the pool.",
        resolution="Cleared confirmed stuck sessions.",
        lessons="Watch pool wait time.",
    )

    assert result["success"] is False
    assert "internal retain detail" not in result["message"]
    assert "internal retain detail" in caplog.text


def test_hindsight_retain_rejects_unsuccessful_api_response(monkeypatch):
    _install_fake_hindsight(monkeypatch, retain_success=False)

    result = hindsight_service.retain_incident(
        incident_id="INC-0009",
        title="Pool wait",
        service="checkout-api",
        severity="High",
        root_cause="Long-running queries occupied the pool.",
        resolution="Cleared confirmed stuck sessions.",
        lessons="Watch pool wait time.",
    )

    assert result["success"] is False
    assert "saved locally" in result["message"]


def test_new_incident_passes_hindsight_and_sqlite_matches_separately(client, app, monkeypatch):
    _create_incident(app, status="Resolved", title="Prior checkout pool exhaustion")
    memory = {"text": "Hindsight memory: prior verified pool recovery."}
    captured = {}

    monkeypatch.setattr(
        incident_routes,
        "recall_incidents",
        lambda query, limit=5: {
            "success": True,
            "status": "success_with_memories",
            "memories": [memory],
            "message": "Recall succeeded.",
        },
    )

    def analyze_stub(parsed, matches, config, hindsight_memories=None):
        captured["matches"] = matches
        captured["hindsight_memories"] = hindsight_memories
        return {
            "classification": "database connectivity",
            "severity": "High",
            "summary": parsed["summary"],
            "suspected_causes": [],
            "recommendations": [],
        }, "local_fallback"

    monkeypatch.setattr(incident_routes, "analyze", analyze_stub)
    response = client.post(
        "/incidents/",
        data={
            "title": "Billing pool acquisition timeout",
            "logs": "ERROR service=billing-api database pool acquisition timeout",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert captured["matches"]
    assert captured["hindsight_memories"] == [memory]
    assert b"RECALL SUCCEEDED" in response.data
    assert b"Hindsight memory: prior verified pool recovery." in response.data
    assert b"Local incident index" in response.data
    assert b"Prior checkout pool exhaustion" in response.data
    assert b"AI-generated investigation recommendations" in response.data
    assert b"1 actual Hindsight memories" in response.data
    with app.app_context():
        new_incident = Incident.query.filter_by(title="Billing pool acquisition timeout").one()
        analysis = json.loads(new_incident.analysis_json)
        assert analysis["hindsight_status"] == "success_with_memories"
        assert analysis["hindsight_memories"] == [memory]


def test_demo_retains_then_later_incident_uses_only_actual_recalled_context(
    client, app, monkeypatch
):
    retained = []
    captured_analysis = {}

    def retain_stub(**kwargs):
        retained.append(kwargs)
        return {"success": True, "message": "test retained"}

    def recall_stub(query, limit=5):
        if not retained:
            return {"success": True, "status": "success_empty", "memories": [], "message": "No memories."}
        record = retained[-1]
        text = (
            f"VERIFIED CHRONOOPS INCIDENT POST-MORTEM\n"
            f"Title: {record['title']}\n"
            f"Verified root cause: {record['root_cause']}\n"
            f"Actual resolution: {record['resolution']}"
        )
        return {"success": True, "status": "success_with_memories", "memories": [{"text": text}], "message": "Recalled retained test post-mortem."}

    def analyze_stub(parsed, matches, config, hindsight_memories=None):
        captured_analysis["matches"] = matches
        captured_analysis["hindsight_memories"] = hindsight_memories
        result = ai_service.fallback_analysis(parsed, hindsight_memories)
        return result, "local_fallback"

    monkeypatch.setattr(incident_routes, "retain_incident", retain_stub)
    monkeypatch.setattr(incident_routes, "recall_incidents", recall_stub)
    monkeypatch.setattr(incident_routes, "analyze", analyze_stub)

    first = client.post("/incidents/", data={
        "title": "Demo · Checkout DB pool saturation",
        "logs": "ERROR service=checkout-api connection pool exhausted; acquire wait timed out",
        "is_demo": "1",
    }, follow_redirects=True)
    assert b"RECALL SUCCEEDED" in first.data
    assert b"NO MATCHES" in first.data
    with app.app_context():
        first_incident = Incident.query.filter_by(title="Demo · Checkout DB pool saturation").one()
        first_id = first_incident.id

    postmortem = {
        **_verified_postmortem("Reviewed active queries and released confirmed stalled sessions."),
        "verification_confirmed": "1",
    }
    saved = client.post(f"/incidents/{first_id}/postmortem", data=postmortem, follow_redirects=True)
    assert b"Hindsight retention: <b>RETAINED" in saved.data
    assert len(retained) == 1
    assert retained[0]["incident_id"].startswith("DEMO-")
    with app.app_context():
        sync = HindsightSync.query.filter_by(incident_id=first_id).one()
        assert sync.status == "retained"
        assert sync.retained_at is not None

    second = client.post("/incidents/", data={
        "title": "Demo · Billing DB wait time rising",
        "logs": "WARN service=billing-api database checkout latency high\nERROR service=billing-api acquire operation timed out; too many sessions queued",
        "is_demo": "1",
    }, follow_redirects=True)
    assert b"RECALL SUCCEEDED" in second.data
    assert b"MEMORIES FOUND" in second.data
    assert b"Demo \xc2\xb7 Checkout DB pool saturation" in second.data
    assert b"Local incident index" in second.data
    assert b"AI-generated investigation recommendations" in second.data
    assert b"1 actual Hindsight memories" in second.data
    assert captured_analysis["hindsight_memories"]
    assert captured_analysis["hindsight_memories"][0]["text"].startswith("VERIFIED CHRONOOPS")
    assert captured_analysis["matches"]
    with app.app_context():
        second_incident = Incident.query.filter_by(title="Demo · Billing DB wait time rising").one()
        analysis = json.loads(second_incident.analysis_json)
        assert analysis["context_sources"] == {"hindsight_memory_count": 1, "sqlite_match_count": 1}


def test_demo_retain_key_is_repeatable_for_same_label(client, app, monkeypatch):
    incident_id = _create_incident(app, title="Demo · Same pool sample")
    with app.app_context():
        incident = db.session.get(Incident, incident_id)
        incident.is_demo = True
        db.session.commit()
    identifiers = []
    monkeypatch.setattr(incident_routes, "retain_incident", lambda **kwargs: identifiers.append(kwargs["incident_id"]) or {"success": True})
    client.post(f"/incidents/{incident_id}/postmortem", data=_verified_postmortem())
    with app.app_context():
        first_sync = HindsightSync.query.filter_by(incident_id=incident_id).one()
        first_sync.status = "failed"
        first_sync.retained_at = None
        db.session.commit()
    client.post(f"/incidents/{incident_id}/postmortem", data=_verified_postmortem())
    assert identifiers[0] == identifiers[1]


def test_groq_prompt_keeps_hindsight_and_sqlite_sources_separate(monkeypatch):
    local_incident = SimpleNamespace(
        id=42,
        postmortem=SimpleNamespace(
            confirmed_root_cause="A long-running query occupied the pool.",
            actual_resolution="Cleared the stuck query.",
        ),
        service="checkout-api",
        category="database connectivity",
    )
    captured = {}
    response_body = {
        "classification": "database connectivity",
        "severity": "High",
        "summary": "Pool acquisition timed out.",
        "suspected_causes": [],
        "recommendations": ["Check active sessions."],
    }

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": json.dumps(response_body)}}]}

    def post_stub(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return FakeResponse()

    monkeypatch.setattr(ai_service.requests, "post", post_stub)
    hindsight_memories = [{"text": "Hindsight: prior verified pool recovery."}]
    matches = [{"incident": local_incident, "score": 0.75}]

    result, source = ai_service.analyze(
        parse_logs("ERROR service=checkout-api database pool timeout"),
        matches,
        {
            "GROQ_API_KEY": "test-only-placeholder",
            "GROQ_MODEL": "test-model",
            "MAX_CONTEXT_CHARS": 2000,
            "MAX_COMPLETION_TOKENS": 100,
        },
        hindsight_memories=hindsight_memories,
    )

    prompt = json.loads(captured["kwargs"]["json"]["messages"][0]["content"])
    assert source == "groq"
    assert result["recommendations"] == ["Check active sessions."]
    assert prompt["hindsight_memories"] == ["Hindsight: prior verified pool recovery."]
    assert prompt["historical_incidents"] == [
        {
            "id": 42,
            "similarity": 0.75,
            "root_cause": "A long-running query occupied the pool.",
            "resolution": "Cleared the stuck query.",
            "service": "checkout-api",
            "category": "database connectivity",
        }
    ]


@pytest.mark.parametrize(
    ("result", "status_text", "empty_text"),
    [
        (
            {"success": True, "status": "success_empty", "memories": [], "message": "No matches."},
            b"RECALL SUCCEEDED \xc2\xb7 NO MATCHES",
            b"An empty result does not mean Hindsight is disconnected.",
        ),
        (
            {"success": False, "status": "unavailable", "memories": [], "message": "Unavailable."},
            b"HINDSIGHT UNAVAILABLE",
            b"The Hindsight recall request failed.",
        ),
    ],
)
def test_incident_view_distinguishes_empty_recall_from_failure(
    client, monkeypatch, result, status_text, empty_text
):
    monkeypatch.setattr(incident_routes, "recall_incidents", lambda query, limit=5: result)
    monkeypatch.setattr(
        incident_routes,
        "analyze",
        lambda parsed, matches, config, hindsight_memories=None: (
            {"summary": parsed["summary"], "suspected_causes": [], "recommendations": []},
            "local_fallback",
        ),
    )

    response = client.post(
        "/incidents/",
        data={"title": "No-history incident", "logs": "ERROR service=api cache timeout"},
        follow_redirects=True,
    )

    assert status_text in response.data
    assert empty_text in response.data


def test_unexpected_recall_exception_does_not_stop_incident_creation(client, app, monkeypatch):
    def raise_unexpected(query, limit=5):
        raise RuntimeError("private endpoint details")

    monkeypatch.setattr(incident_routes, "recall_incidents", raise_unexpected)
    monkeypatch.setattr(
        incident_routes,
        "analyze",
        lambda parsed, matches, config, hindsight_memories=None: (
            {"summary": parsed["summary"], "suspected_causes": [], "recommendations": []},
            "local_fallback",
        ),
    )

    response = client.post(
        "/incidents/",
        data={"title": "Continue offline", "logs": "ERROR service=api cache timeout"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"HINDSIGHT UNAVAILABLE" in response.data
    assert b"private endpoint details" not in response.data
    with app.app_context():
        incident = Incident.query.filter_by(title="Continue offline").one()
        assert incident.ai_source == "local_fallback"
        assert json.loads(incident.analysis_json)["hindsight_status"] == "unavailable"


def test_unverified_or_incomplete_postmortem_is_not_saved_or_retained(
    client, app, monkeypatch
):
    incident_id = _create_incident(app)
    retain_calls = []
    monkeypatch.setattr(
        incident_routes,
        "retain_incident",
        lambda **kwargs: retain_calls.append(kwargs) or {"success": True},
    )
    incomplete_forms = [
        {**_verified_postmortem(), "confirmed_root_cause": "   "},
        {**_verified_postmortem(), "actual_resolution": ""},
        {key: value for key, value in _verified_postmortem().items() if key != "verification_confirmed"},
    ]

    for form in incomplete_forms:
        response = client.post(
            f"/incidents/{incident_id}/postmortem", data=form, follow_redirects=True
        )
        assert b"engineer verification are required" in response.data

    with app.app_context():
        incident = db.session.get(Incident, incident_id)
        assert incident.status == "Open"
        assert incident.postmortem is None
        assert HindsightSync.query.filter_by(incident_id=incident_id).first() is None
    assert retain_calls == []


def test_postmortem_retention_success_skips_unchanged_duplicate(client, app, monkeypatch):
    incident_id = _create_incident(app)
    calls = []
    monkeypatch.setattr(
        incident_routes,
        "retain_incident",
        lambda **kwargs: calls.append(kwargs) or {"success": True},
    )
    form = _verified_postmortem()

    assert client.post(f"/incidents/{incident_id}/postmortem", data=form).status_code == 302
    with app.app_context():
        sync = HindsightSync.query.filter_by(incident_id=incident_id).one()
        retained_at = sync.retained_at
        assert sync.status == "retained"
        assert retained_at is not None
        assert db.session.get(Incident, incident_id).postmortem is not None

    assert client.post(f"/incidents/{incident_id}/postmortem", data=form).status_code == 302
    with app.app_context():
        sync = HindsightSync.query.filter_by(incident_id=incident_id).one()
        assert sync.status == "retained"
        assert sync.retained_at == retained_at
    assert len(calls) == 1


def test_failed_edit_clears_old_timestamp_and_retry_succeeds(client, app, monkeypatch):
    incident_id = _create_incident(app)
    outcomes = [True, False, True]
    calls = []

    def retain_stub(**kwargs):
        calls.append(kwargs)
        return {"success": outcomes.pop(0)}

    monkeypatch.setattr(incident_routes, "retain_incident", retain_stub)
    initial = _verified_postmortem()
    edited = _verified_postmortem("Cleared stuck sessions and verified pool wait returned to baseline.")

    client.post(f"/incidents/{incident_id}/postmortem", data=initial)
    with app.app_context():
        first_sync = HindsightSync.query.filter_by(incident_id=incident_id).one()
        assert first_sync.status == "retained"
        assert first_sync.retained_at is not None

    client.post(f"/incidents/{incident_id}/postmortem", data=edited)
    with app.app_context():
        failed_sync = HindsightSync.query.filter_by(incident_id=incident_id).one()
        assert failed_sync.status == "failed"
        assert failed_sync.retained_at is None
        assert "saved locally" in failed_sync.message
        assert db.session.get(Incident, incident_id).postmortem.actual_resolution == edited["actual_resolution"]

    report = client.get("/incidents/postmortems")
    assert b"HINDSIGHT FAILED" in report.data
    assert b"HINDSIGHT RETAINED" not in report.data

    failed_response = client.post(
        f"/incidents/{incident_id}/postmortem", data=edited, follow_redirects=True
    )
    assert b"internal endpoint" not in failed_response.data
    with app.app_context():
        retried_sync = HindsightSync.query.filter_by(incident_id=incident_id).one()
        assert retried_sync.status == "retained"
        assert retried_sync.retained_at is not None
    assert len(calls) == 3


def test_unexpected_retention_exception_keeps_local_postmortem(client, app, monkeypatch):
    incident_id = _create_incident(app)

    def raise_unexpected(**kwargs):
        raise RuntimeError("private endpoint details")

    monkeypatch.setattr(incident_routes, "retain_incident", raise_unexpected)
    response = client.post(
        f"/incidents/{incident_id}/postmortem",
        data=_verified_postmortem(),
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"private endpoint details" not in response.data
    with app.app_context():
        incident = db.session.get(Incident, incident_id)
        sync = HindsightSync.query.filter_by(incident_id=incident_id).one()
        assert incident.status == "Resolved"
        assert incident.postmortem is not None
        assert sync.status == "failed"
        assert sync.retained_at is None
