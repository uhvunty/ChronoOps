from datetime import timedelta
from flask import Blueprint, render_template
from sqlalchemy import case, func
from models import HindsightSync, Incident, IncidentLog, db, now_utc
from services.hindsight_service import check_hindsight_health

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    total = Incident.query.count()
    active = Incident.query.filter(Incident.status != "Resolved").count()
    resolved = Incident.query.filter_by(status="Resolved").count()
    locally_indexed = Incident.query.join(Incident.postmortem).filter(Incident.status == "Resolved").count()
    real_syncs = HindsightSync.query.join(Incident).filter(Incident.is_demo.is_(False))
    retained = real_syncs.filter(HindsightSync.status == "retained").count()
    retention_pending = real_syncs.filter(HindsightSync.status == "pending").count()
    retention_failed = real_syncs.filter(HindsightSync.status == "failed").count()
    retention_not_submitted = Incident.query.outerjoin(
        HindsightSync, HindsightSync.incident_id == Incident.id
    ).join(Incident.postmortem).filter(
        Incident.is_demo.is_(False), Incident.status == "Resolved", HindsightSync.id.is_(None)
    ).count()
    last_retained = db.session.query(func.max(HindsightSync.retained_at)).join(Incident).filter(
        Incident.is_demo.is_(False), HindsightSync.status == "retained", HindsightSync.retained_at.isnot(None)
    ).scalar()
    hindsight_health = check_hindsight_health()
    severity = {name: Incident.query.filter_by(severity=name).count() for name in ("Critical", "High", "Medium", "Low")}
    recent = Incident.query.order_by(Incident.updated_at.desc()).limit(8).all()
    trend = db.session.query(func.date(Incident.created_at), func.count(Incident.id)).filter(Incident.created_at >= now_utc() - timedelta(days=6)).group_by(func.date(Incident.created_at)).all()
    health = db.session.query(IncidentLog.service, func.max(IncidentLog.occurred_at), func.sum(case((IncidentLog.level.in_(["ERROR", "CRITICAL", "FATAL"]), 1), else_=0))).group_by(IncidentLog.service).limit(6).all()
    return render_template(
        "dashboard.html", total=total, active=active, resolved=resolved,
        locally_indexed=locally_indexed, retained=retained,
        retention_pending=retention_pending, retention_failed=retention_failed,
        retention_not_submitted=retention_not_submitted,
        last_retained=last_retained, hindsight_health=hindsight_health,
        severity=severity, recent=recent, trend=trend, health=health,
    )
