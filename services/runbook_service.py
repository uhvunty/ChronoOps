from models import Runbook


def relevant_runbooks(service, category):
    rows = Runbook.query.order_by(Runbook.created_at.desc()).all()
    return sorted(rows, key=lambda r: (r.service.lower() not in (service.lower(), "any"), r.category.lower() != category.lower()))[:8]
