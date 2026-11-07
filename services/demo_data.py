from models import Incident, IncidentLog, PostMortem, Runbook, db
from services.log_analyzer import parse_logs

SAMPLES = {
    "pool-first": {"title": "Demo · Checkout DB pool saturation", "service": "checkout-api", "logs": "2026-11-06T12:02:00Z ERROR service=checkout-api Failed to acquire database connection: pool exhausted\n2026-11-06T12:02:04Z ERROR service=checkout-api request timeout waiting for connection\n2026-11-06T12:02:08Z WARN service=checkout-api db pool active=40 idle=0 max=40\n2026-11-06T12:02:11Z ERROR service=checkout-api Failed to acquire database connection: pool exhausted", "resolve": True},
    "pool-second": {"title": "Demo · Billing DB wait time rising", "service": "billing-api", "logs": "2026-11-07T09:11:00Z WARN service=billing-api database checkout latency 1800ms\n2026-11-07T09:11:03Z ERROR service=billing-api acquire connection timed out after 2s\n2026-11-07T09:11:09Z ERROR service=billing-api too many connections waiting for pool slot\n2026-11-07T09:11:14Z WARN service=billing-api pool active=32 idle=0 max=32"},
    "gateway": {"title": "Demo · Edge upstream timeout", "service": "api-gateway", "logs": "2026-11-07T08:00:00Z ERROR service=api-gateway upstream timeout after 30s\n2026-11-07T08:00:04Z WARN service=api-gateway retry budget exhausted"},
    "memory": {"title": "Demo · Worker memory pressure", "service": "worker", "logs": "2026-11-07T07:20:00Z WARN service=worker memory usage 91%\n2026-11-07T07:20:08Z ERROR service=worker out of memory allocating buffer"},
    "dependency": {"title": "Demo · Search dependency unavailable", "service": "search-api", "logs": "2026-11-07T06:30:00Z ERROR service=search-api dependency catalog unavailable\n2026-11-07T06:30:02Z WARN service=search-api connection reset by peer"}
}


def seed_demo():
    made = 0
    for key in ("pool-first", "gateway", "memory", "dependency"):
        sample = SAMPLES[key]
        if Incident.query.filter_by(title=sample["title"]).first():
            continue
        parsed = parse_logs(sample["logs"])
        inc = Incident(title=sample["title"], service=sample["service"], category="database connectivity" if key == "pool-first" else key, severity="High", status="Resolved", summary=parsed["summary"], evidence=parsed["evidence"], symptoms=parsed["summary"], fingerprint=parsed["fingerprint"], source="demo", is_demo=True, ai_source="demo sample", analysis_json="{}")
        db.session.add(inc)
        for e in parsed["events"]:
            db.session.add(IncidentLog(incident=inc, occurred_at=e["timestamp"], level=e["level"], service=e["service"], message=e["message"]))
        if key == "pool-first":
            db.session.flush()
            db.session.add(PostMortem(incident=inc, impact="Checkout requests queued during the pool saturation window.", confirmed_root_cause="A burst of long-running checkout queries occupied every configured database pool connection.", actual_resolution="After reviewing active queries, the on-call engineer terminated the confirmed stuck sessions and safely raised the application pool limit for the affected service.", recovery_outcome="Checkout error rate returned to baseline and pool wait time cleared.", preventive_measures="Alert on pool wait time; cap query duration; review pool sizing against database capacity.", lessons_learned="Correlate application pool saturation with database active sessions before changing pool settings."))
        made += 1
    if not Runbook.query.filter_by(title="Database connection pool saturation").first():
        db.session.add(Runbook(title="Database connection pool saturation", service="checkout-api", category="database connectivity", trigger_conditions="Pool active connections at configured max with connection acquisition timeouts.", investigation_steps="1. Check pool active, idle and wait counts.\n2. Correlate timestamps with database active sessions and slow query samples.\n3. Check recent deploys and connection leaks.", recovery_steps="1. Review sessions with the database owner.\n2. Stop only confirmed stuck work using approved operational procedures.\n3. Adjust pool limits only after confirming database capacity.", verification_checklist="Confirm pool wait time and error rate returned to baseline; watch through a normal traffic period.", is_demo=True))
    db.session.commit()
    return made


def reset_demo():
    for incident in Incident.query.filter_by(is_demo=True).all():
        db.session.delete(incident)
    Runbook.query.filter_by(is_demo=True).delete(synchronize_session=False)
    db.session.commit()
