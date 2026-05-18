from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse

from ..database import MongoSession, get_db
from ..models import CampaignTemplate

router = APIRouter()


@router.get("/templates")
def list_templates(request: Request, db: MongoSession = Depends(get_db)):
    tpls = db.query(CampaignTemplate).order_by(CampaignTemplate.created_at.desc()).all()
    return request.app.state.templates.TemplateResponse(request, "templates_/list.html", {
        "request": request, "templates": tpls,
    })


@router.get("/templates/{tpl_id}/json")
def get_template_json(tpl_id: int, db: MongoSession = Depends(get_db)):
    t = db.query(CampaignTemplate).filter(CampaignTemplate.id == tpl_id).first()
    if not t:
        raise HTTPException(404)
    return JSONResponse({"id": t.id, "name": t.name, "config": t.config})


@router.post("/templates/{tpl_id}/delete")
def delete_template(tpl_id: int, db: MongoSession = Depends(get_db)):
    t = db.query(CampaignTemplate).filter(CampaignTemplate.id == tpl_id).first()
    if t:
        db.delete(t)
        db.commit()
    return RedirectResponse("/templates", status_code=303)
