from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from typing import Any as Session

from ..database import get_db
from ..models import Campaign
from ..trick_runner import run_trick_check

router = APIRouter()


@router.get("/trick")
def trick_dashboard(request: Request, db: Session = Depends(get_db)):
    pending = db.query(Campaign).filter(
        Campaign.trick_enabled == True, Campaign.trick_executed == False
    ).all()
    done = db.query(Campaign).filter(
        Campaign.trick_enabled == True, Campaign.trick_executed == True
    ).order_by(Campaign.trick_executed_at.desc()).all()
    return request.app.state.templates.TemplateResponse(request, "trick.html", {
        "request": request, "pending": pending, "done": done,
    })


@router.post("/trick/run-now")
def run_now():
    run_trick_check()
    return RedirectResponse("/trick", status_code=303)
