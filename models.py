from datetime import datetime, timezone
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def now_utc():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Incident(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    service = db.Column(db.String(100), default="unknown", nullable=False)
    category = db.Column(db.String(80), default="general", nullable=False)
    severity = db.Column(db.String(20), default="Medium", nullable=False)
    status = db.Column(db.String(24), default="Open", nullable=False)
    summary = db.Column(db.Text, default="", nullable=False)
    symptoms = db.Column(db.Text, default="", nullable=False)
    evidence = db.Column(db.Text, default="", nullable=False)
    fingerprint = db.Column(db.String(64), default="", nullable=False)
    source = db.Column(db.String(30), default="manual", nullable=False)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)
    ai_source = db.Column(db.String(30), default="pending", nullable=False)
    analysis_json = db.Column(db.Text, default="{}", nullable=False)
    created_at = db.Column(db.DateTime, default=now_utc, nullable=False)
    updated_at = db.Column(db.DateTime, default=now_utc, onupdate=now_utc, nullable=False)
    logs = db.relationship("IncidentLog", back_populates="incident", cascade="all, delete-orphan", order_by="IncidentLog.occurred_at")
    postmortem = db.relationship("PostMortem", back_populates="incident", uselist=False, cascade="all, delete-orphan")
    feedback = db.relationship("IncidentFeedback", back_populates="incident", cascade="all, delete-orphan")
    runbooks = db.relationship("Runbook", back_populates="source_incident")


class IncidentLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey("incident.id", ondelete="CASCADE"), nullable=False)
    occurred_at = db.Column(db.DateTime, default=now_utc, nullable=False)
    level = db.Column(db.String(12), default="INFO", nullable=False)
    service = db.Column(db.String(100), default="unknown", nullable=False)
    message = db.Column(db.Text, nullable=False)
    incident = db.relationship("Incident", back_populates="logs")


class PostMortem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey("incident.id", ondelete="CASCADE"), unique=True, nullable=False)
    impact = db.Column(db.Text, default="", nullable=False)
    confirmed_root_cause = db.Column(db.Text, nullable=False)
    actual_resolution = db.Column(db.Text, nullable=False)
    recovery_outcome = db.Column(db.Text, default="", nullable=False)
    preventive_measures = db.Column(db.Text, default="", nullable=False)
    lessons_learned = db.Column(db.Text, default="", nullable=False)
    engineer_feedback = db.Column(db.Text, default="", nullable=False)
    created_at = db.Column(db.DateTime, default=now_utc, nullable=False)
    incident = db.relationship("Incident", back_populates="postmortem")


class Runbook(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source_incident_id = db.Column(db.Integer, db.ForeignKey("incident.id", ondelete="SET NULL"))
    title = db.Column(db.String(180), nullable=False)
    service = db.Column(db.String(100), default="any", nullable=False)
    category = db.Column(db.String(80), default="general", nullable=False)
    trigger_conditions = db.Column(db.Text, default="", nullable=False)
    investigation_steps = db.Column(db.Text, default="", nullable=False)
    recovery_steps = db.Column(db.Text, default="", nullable=False)
    verification_checklist = db.Column(db.Text, default="", nullable=False)
    is_demo = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=now_utc, nullable=False)
    source_incident = db.relationship("Incident", back_populates="runbooks")


class IncidentFeedback(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(db.Integer, db.ForeignKey("incident.id", ondelete="CASCADE"), nullable=False)
    hypothesis = db.Column(db.Text, nullable=False)
    verdict = db.Column(db.String(20), nullable=False)
    notes = db.Column(db.Text, default="", nullable=False)
    created_at = db.Column(db.DateTime, default=now_utc, nullable=False)
    incident = db.relationship("Incident", back_populates="feedback")



class HindsightSync(db.Model):
    """Tracks whether each verified post-mortem was successfully retained."""
    id = db.Column(db.Integer, primary_key=True)
    incident_id = db.Column(
        db.Integer,
        db.ForeignKey("incident.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    status = db.Column(db.String(20), default="pending", nullable=False)
    content_hash = db.Column(db.String(64), default="", nullable=False)
    message = db.Column(db.Text, default="", nullable=False)
    retained_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=now_utc, onupdate=now_utc, nullable=False)
    incident = db.relationship("Incident")
