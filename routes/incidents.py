import json
import hashlib
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from werkzeug.utils import secure_filename
from models import HindsightSync, Incident, IncidentFeedback, IncidentLog, PostMortem, db
from services.ai_service import analyze
from services.incident_memory import retrieve_similar
from services.hindsight_service import recall_incidents, retain_incident
from services.log_analyzer import parse_logs
from services.postmortem_service import save_postmortem
from services.runbook_service import relevant_runbooks

bp = Blueprint("incidents", __name__, url_prefix="/incidents")


@bp.get("/new")
def new():
    from services.demo_data import SAMPLES
    sample = SAMPLES.get(request.args.get("sample", ""), {})
    return render_template("new_incident.html", sample=sample.get("logs", ""), sample_title=sample.get("title", ""))


@bp.post("/")
def create():
    raw = request.form.get("logs", "")
    upload = request.files.get("file")
    if upload and upload.filename:
        if not upload.filename.lower().endswith((".log", ".txt", ".json")):
            flash("Use a .log, .txt or .json file.", "error")
            return redirect(url_for("incidents.new"))
        raw = upload.read(current_app.config["MAX_CONTENT_LENGTH"] + 1).decode("utf-8", "replace")
        if len(raw) > current_app.config["MAX_CONTENT_LENGTH"]:
            flash("File exceeds the 2 MB limit.", "error")
            return redirect(url_for("incidents.new"))
        raw = raw[:current_app.config["MAX_LOG_CHARS"]]
    if not raw.strip():
        flash("Paste logs or choose a log file.", "error")
        return redirect(url_for("incidents.new"))
    parsed = parse_logs(raw, current_app.config["MAX_LOG_CHARS"])
    existing = Incident.query.filter_by(fingerprint=parsed["fingerprint"]).order_by(Incident.created_at.desc()).first()
    if existing and existing.status != "Resolved":
        flash("These unchanged logs already have an active analysis. Open the existing incident.", "success")
        return redirect(url_for("incidents.detail", incident_id=existing.id))
    service = (parsed["services"] or ["unknown"])[0]
    title = request.form.get("title", "").strip()[:180] or f"{service} incident · {parsed['first_seen'].strftime('%b %d %H:%M')}"
    incident = Incident(title=title, service=service, summary=parsed["summary"], evidence=parsed["evidence"], fingerprint=parsed["fingerprint"], source="upload" if upload and upload.filename else "manual", is_demo=request.form.get("is_demo") == "1")
    incident.symptoms = "; ".join(row["message"][:160] for row in parsed["repeated"][:4]) or parsed["summary"]
    db.session.add(incident)
    for event in parsed["events"]:
        db.session.add(IncidentLog(incident=incident, occurred_at=event["timestamp"], level=event["level"], service=event["service"], message=event["message"]))
    db.session.flush()
    query = " ".join([incident.title, incident.service, incident.summary, incident.evidence])
    matches = retrieve_similar(query, Incident.query.filter(Incident.id != incident.id).all())
    hindsight_result = recall_incidents(query, limit=5)
    hindsight_memories = hindsight_result.get("memories", []) if hindsight_result.get("success") else []
    analysis, ai_source = analyze(parsed, matches, current_app.config, hindsight_memories=hindsight_memories)
    analysis["hindsight_memories"] = hindsight_memories
    analysis["hindsight_status"] = "connected" if hindsight_result.get("success") else "unavailable"
    analysis["hindsight_message"] = hindsight_result.get("message", "")
    incident.ai_source, incident.analysis_json, incident.category, incident.severity = ai_source, json.dumps(analysis), analysis.get("classification", "general"), analysis.get("severity", "Medium")
    db.session.commit()
    return redirect(url_for("incidents.detail", incident_id=incident.id))


@bp.get("/<int:incident_id>")
def detail(incident_id):
    incident = Incident.query.get_or_404(incident_id)
    analysis = json.loads(incident.analysis_json or "{}")
    matches = retrieve_similar(" ".join([incident.title, incident.service, incident.summary, incident.evidence]), Incident.query.filter(Incident.id != incident.id).all())
    hindsight_sync = HindsightSync.query.filter_by(incident_id=incident.id).first()
    return render_template("investigation.html", incident=incident, analysis=analysis, matches=matches, hindsight_sync=hindsight_sync, runbooks=relevant_runbooks(incident.service, incident.category))


@bp.post("/<int:incident_id>/feedback")
def feedback(incident_id):
    incident = Incident.query.get_or_404(incident_id)
    db.session.add(IncidentFeedback(incident=incident, hypothesis=request.form.get("hypothesis", "")[:1000], verdict=request.form.get("verdict", "reviewed")[:20], notes=request.form.get("notes", "")[:1000]))
    if request.form.get("verdict") == "confirmed" and request.form.get("hypothesis", "").strip():
        analysis = json.loads(incident.analysis_json or "{}")
        analysis["engineer_confirmed"] = request.form["hypothesis"][:1000]
        incident.analysis_json = json.dumps(analysis)
    db.session.commit()
    flash("Engineer feedback saved.", "success")
    return redirect(url_for("incidents.detail", incident_id=incident_id))


@bp.post("/<int:incident_id>/investigating")
def investigating(incident_id):
    incident = Incident.query.get_or_404(incident_id)
    if incident.status == "Open":
        incident.status = "Investigating"
        db.session.commit()
        flash("Incident moved to investigating.", "success")
    return redirect(url_for("incidents.detail", incident_id=incident_id))


@bp.post("/<int:incident_id>/postmortem")
def postmortem(incident_id):
    incident = Incident.query.get_or_404(incident_id)
    if not request.form.get("confirmed_root_cause", "").strip() or not request.form.get("actual_resolution", "").strip():
        flash("Confirmed cause and actual resolution are required to resolve an incident.", "error")
    else:
        pm = save_postmortem(incident, request.form)
        fingerprint_source = "\\n".join([
            incident.title, incident.service, incident.severity,
            pm.impact, pm.confirmed_root_cause, pm.actual_resolution,
            pm.recovery_outcome, pm.preventive_measures, pm.lessons_learned,
        ])
        content_hash = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()
        sync = HindsightSync.query.filter_by(incident_id=incident.id).first()
        if sync is None:
            sync = HindsightSync(incident_id=incident.id)
            db.session.add(sync)
        if sync.status != "retained" or sync.content_hash != content_hash:
            result = retain_incident(
                incident_id=f"INC-{incident.id:04d}",
                title=incident.title,
                service=incident.service,
                severity=incident.severity,
                root_cause=pm.confirmed_root_cause,
                resolution=pm.actual_resolution,
                lessons=pm.lessons_learned,
                impact=pm.impact,
                recovery_outcome=pm.recovery_outcome,
                preventive_measures=pm.preventive_measures,
            )
            sync.status = "retained" if result.get("success") else "failed"
            sync.content_hash = content_hash
            sync.message = result.get("message", "")
            if result.get("success"):
                from models import now_utc
                sync.retained_at = now_utc()
            db.session.commit()
            if result.get("success"):
                flash("Post-mortem saved and retained in Hindsight for future investigations.", "success")
            else:
                flash("Post-mortem saved locally, but Hindsight retention failed. Check that Hindsight is running; saving again will retry. " + result.get("message", ""), "warning")
        else:
            flash("Post-mortem saved. This unchanged version is already retained in Hindsight.", "success")
    return redirect(url_for("incidents.detail", incident_id=incident_id))


@bp.get("/history")
def history():
    return render_template("history.html", incidents=Incident.query.order_by(Incident.created_at.desc()).all())


@bp.get("/postmortems")
def postmortems():
    reports = Incident.query.join(Incident.postmortem).order_by(Incident.updated_at.desc()).all()
    return render_template("postmortems.html", incidents=reports)


@bp.get("/replay/<int:incident_id>")
def replay(incident_id):
    return render_template("replay.html", incident=Incident.query.get_or_404(incident_id))

