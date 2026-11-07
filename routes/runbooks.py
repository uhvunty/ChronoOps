from flask import Blueprint, render_template
from models import Runbook

bp = Blueprint("runbooks", __name__, url_prefix="/runbooks")


@bp.get("/")
def index():
    return render_template("runbooks.html", runbooks=Runbook.query.order_by(Runbook.created_at.desc()).all())
