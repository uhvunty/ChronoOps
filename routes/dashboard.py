from datetime import datetime, timedelta
from flask import Blueprint, render_template
from sqlalchemy import case, func
from models import Incident, IncidentLog, PostMortem, db

bp = Blueprint("dashboard", __name__)


@bp.get("/")
def index():
    total = Incident.query.count()
    active = Incident.query.filter(Incident.status != "Resolved").count()
    resolved = Incident.query.filter_by(status="Resolved").count()
    severity = {name: Incident.query.filter_by(severity=name).count() for name in ("Critical", "High", "Medium", "Low")}
    recent = Incident.query.order_by(Incident.updated_at.desc()).limit(8).all()
    trend = db.session.query(func.date(Incident.created_at), func.count(Incident.id)).filter(Incident.created_at >= datetime.utcnow() - timedelta(days=6)).group_by(func.date(Incident.created_at)).all()
    health = db.session.query(IncidentLog.service, func.max(IncidentLog.occurred_at), func.sum(case((IncidentLog.level.in_(["ERROR", "CRITICAL", "FATAL"]), 1), else_=0))).group_by(IncidentLog.service).limit(6).all()
    return render_template("dashboard.html", total=total, active=active, resolved=resolved, severity=severity, recent=recent, trend=trend, health=health)
