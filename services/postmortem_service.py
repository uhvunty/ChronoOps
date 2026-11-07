from models import Incident, PostMortem, db


def save_postmortem(incident, data):
    pm = incident.postmortem or PostMortem(incident=incident)
    for field in ("impact", "confirmed_root_cause", "actual_resolution", "recovery_outcome", "preventive_measures", "lessons_learned", "engineer_feedback"):
        setattr(pm, field, str(data.get(field, "")).strip()[:4000])
    db.session.add(pm)
    incident.status = "Resolved"
    db.session.commit()
    return pm
