"""
Routes para la vista Sheet de Planificación de campañas.
Aislado: no modifica el flujo existente. Reusa servicios.
"""
import json
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from typing import Any as Session

from ..database import get_db
from ..services.planning_models import PlannedCampaign
from ..services.planning_executor import execute_plan
from ..services.language_models import MediaAsset, CopyBundle
from ..services.meta_locales import META_LOCALES

router = APIRouter()


# ─── Constantes UI ──────────────────────────────────────────────────────────
BID_STRATEGIES = [
    ("LOWEST_COST_WITHOUT_CAP", "Volumen más alto"),
    ("COST_CAP", "Objetivo de costo por resultado"),
    ("LOWEST_COST_WITH_MIN_ROAS", "Objetivo de ROAS"),
    ("LOWEST_COST_WITH_BID_CAP", "Límite de puja"),
]
OBJECTIVES = [
    ("OUTCOME_SALES", "Ventas"),
    ("OUTCOME_LEADS", "Leads"),
    ("OUTCOME_TRAFFIC", "Tráfico"),
    ("OUTCOME_AWARENESS", "Reconocimiento"),
    ("OUTCOME_ENGAGEMENT", "Interacción"),
]
EVENT_TYPES = [
    ("PURCHASE", "Compra"),
    ("INITIATE_CHECKOUT", "Inicio de checkout"),
    ("ADD_TO_CART", "Añadir al carrito"),
    ("LEAD", "Lead"),
    ("COMPLETE_REGISTRATION", "Registro completo"),
    ("VIEW_CONTENT", "Vista de contenido"),
]
OPTIMIZATION_GOALS = [
    ("OFFSITE_CONVERSIONS", "Conversiones (pixel)"),
    ("LANDING_PAGE_VIEWS", "Vistas de landing page"),
    ("LINK_CLICKS", "Clics en enlace"),
    ("IMPRESSIONS", "Impresiones"),
    ("REACH", "Alcance"),
]
CTAS = ["LEARN_MORE", "SHOP_NOW", "SIGN_UP", "SUBSCRIBE", "GET_OFFER", "APPLY_NOW", "DOWNLOAD", "CONTACT_US"]


def _fetch_meta_dropdowns(db):
    from .. import meta_api
    from ..meta_connections import get_active_token, get_effective_defaults
    from ..models import AppSettings
    settings = db.query(AppSettings).first()
    if not settings:
        settings = AppSettings()
        db.add(settings)
        db.commit()
    defaults = get_effective_defaults(db)
    token = get_active_token(db)
    accounts, pages, pixels = [], [], []
    try:
        accounts = meta_api.list_ad_accounts(token=token)
        pages = meta_api.list_pages(token=token)
        if defaults["ad_account_id"]:
            try:
                pixels = meta_api.list_pixels(defaults["ad_account_id"], token=token)
            except Exception:
                pass
    except Exception:
        pass
    for key, value in defaults.items():
        setattr(settings, f"default_{key}", value)
    return settings, accounts, pages, pixels


# ─── LIST (sheet view) ──────────────────────────────────────────────────────
@router.get("/planning")
def planning_list(request: Request, db: Session = Depends(get_db)):
    items = db.query(PlannedCampaign).order_by(PlannedCampaign.created_at.desc()).all()
    return request.app.state.templates.TemplateResponse(request, "planning/list.html", {
        "request": request, "items": items, "locales": META_LOCALES,
    })


# ─── NEW (type selector) ────────────────────────────────────────────────────
@router.get("/planning/new")
def planning_new(request: Request):
    return request.app.state.templates.TemplateResponse(request, "planning/new_type.html", {
        "request": request,
    })


def _common_ctx(db):
    settings, accounts, pages, pixels = _fetch_meta_dropdowns(db)
    return {
        "accounts": accounts, "pages": pages, "pixels": pixels, "settings": settings,
        "locales": META_LOCALES,
        "bid_strategies": BID_STRATEGIES, "objectives": OBJECTIVES,
        "event_types": EVENT_TYPES, "optimization_goals": OPTIMIZATION_GOALS,
        "ctas": CTAS,
    }


@router.get("/planning/new-language")
def planning_new_lang(request: Request, db: Session = Depends(get_db)):
    media = db.query(MediaAsset).order_by(MediaAsset.name).all()
    copies = db.query(CopyBundle).order_by(CopyBundle.name).all()
    ctx = _common_ctx(db)
    ctx.update({"request": request, "media": media, "copies": copies, "edit": None})
    return request.app.state.templates.TemplateResponse(request, "planning/form_language.html", ctx)


@router.get("/planning/new-normal")
def planning_new_normal(request: Request, db: Session = Depends(get_db)):
    media = db.query(MediaAsset).order_by(MediaAsset.name).all()
    ctx = _common_ctx(db)
    ctx.update({"request": request, "media": media, "edit": None})
    return request.app.state.templates.TemplateResponse(request, "planning/form_normal.html", ctx)


# ─── CREATE ─────────────────────────────────────────────────────────────────
def _parse_ads_from_form(form, keys):
    """Extrae filas ads[N][k] del form, devuelve lista en orden."""
    import re
    indices = set()
    pattern = re.compile(r"^ads\[(\d+)\]\[")
    for k in form.keys():
        m = pattern.match(k)
        if m:
            indices.add(int(m.group(1)))
    rows = []
    for i in sorted(indices):
        row = {k: form.get(f"ads[{i}][{k}]", "") for k in keys}
        # skip vacíos
        if any(v.strip() for v in row.values() if isinstance(v, str)):
            rows.append(row)
    return rows


def _save_plan(form, type_, plan=None, db=None):
    """Crea o actualiza un plan desde form data."""
    if plan is None:
        plan = PlannedCampaign(type=type_, status="pending")
        db.add(plan)

    plan.name = form.get("name", "untitled").strip()
    plan.ad_account_id = form.get("ad_account_id", "")
    plan.page_id = form.get("page_id", "")
    plan.pixel_id = form.get("pixel_id", "")
    plan.instagram_id = form.get("instagram_id", "")
    plan.cbo_or_abo = form.get("cbo_or_abo", "ABO")
    plan.daily_budget_usd = float(form.get("daily_budget_usd", "5") or 5)
    plan.bid_strategy = form.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP")
    plan.bid_amount_usd = float(form.get("bid_amount", "0") or 0)
    plan.roas_floor = float(form.get("roas_floor", "0") or 0)
    plan.countries = form.get("countries", "US")
    plan.age_min = int(form.get("age_min", "18") or 18)
    plan.age_max = int(form.get("age_max", "65") or 65)
    plan.locale_id = int(form.get("locale_id", "6") or 6)
    plan.objective = form.get("objective", "OUTCOME_SALES")
    plan.optimization_goal = form.get("optimization_goal", "OFFSITE_CONVERSIONS")
    plan.custom_event_type = form.get("custom_event_type", "PURCHASE")
    plan.url_tags = form.get("url_tags", "")

    if type_ == "language":
        ads = _parse_ads_from_form(form, ["media_asset_id", "default_media_id", "copy_bundle_id", "cta_type"])
        plan.config = {"ads": ads}
    elif type_ == "normal":
        ads = _parse_ads_from_form(form, ["media_asset_id", "body", "title", "description", "link", "cta_type"])
        plan.config = {"ads": ads}

    return plan


@router.post("/planning/new-language")
async def planning_create_lang(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    _save_plan(form, "language", db=db)
    db.commit()
    return RedirectResponse("/planning", status_code=303)


@router.post("/planning/new-normal")
async def planning_create_normal(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    _save_plan(form, "normal", db=db)
    db.commit()
    return RedirectResponse("/planning", status_code=303)


# ─── EDIT ───────────────────────────────────────────────────────────────────
@router.get("/planning/{plan_id}/edit")
def planning_edit_form(plan_id: int, request: Request, db: Session = Depends(get_db)):
    plan = db.query(PlannedCampaign).filter(PlannedCampaign.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "No encontrado")
    ctx = _common_ctx(db)
    ctx.update({"request": request, "edit": plan})
    if plan.type == "language":
        ctx["media"] = db.query(MediaAsset).order_by(MediaAsset.name).all()
        ctx["copies"] = db.query(CopyBundle).order_by(CopyBundle.name).all()
        return request.app.state.templates.TemplateResponse(request, "planning/form_language.html", ctx)
    if plan.type == "normal":
        ctx["media"] = db.query(MediaAsset).order_by(MediaAsset.name).all()
        return request.app.state.templates.TemplateResponse(request, "planning/form_normal.html", ctx)
    raise HTTPException(400, f"Tipo no soportado: {plan.type}")


@router.post("/planning/{plan_id}/edit")
async def planning_edit(plan_id: int, request: Request, db: Session = Depends(get_db)):
    plan = db.query(PlannedCampaign).filter(PlannedCampaign.id == plan_id).first()
    if not plan:
        raise HTTPException(404, "No encontrado")
    form = await request.form()
    _save_plan(form, plan.type, plan=plan, db=db)
    if plan.status == "error":
        plan.status = "pending"
        plan.error_msg = ""
    db.commit()
    return RedirectResponse("/planning", status_code=303)


# ─── DELETE / DUPLICATE ─────────────────────────────────────────────────────
@router.post("/planning/{plan_id}/delete")
def planning_delete(plan_id: int, db: Session = Depends(get_db)):
    p = db.query(PlannedCampaign).filter(PlannedCampaign.id == plan_id).first()
    if p:
        db.delete(p)
        db.commit()
    return RedirectResponse("/planning", status_code=303)


@router.post("/planning/{plan_id}/duplicate")
def planning_duplicate(plan_id: int, db: Session = Depends(get_db)):
    p = db.query(PlannedCampaign).filter(PlannedCampaign.id == plan_id).first()
    if not p:
        raise HTTPException(404)
    clone = PlannedCampaign(
        type=p.type, status="pending", name=f"{p.name} (copia)",
        ad_account_id=p.ad_account_id, page_id=p.page_id, pixel_id=p.pixel_id,
        instagram_id=p.instagram_id, cbo_or_abo=p.cbo_or_abo,
        daily_budget_usd=p.daily_budget_usd, bid_strategy=p.bid_strategy,
        bid_amount_usd=p.bid_amount_usd, roas_floor=p.roas_floor,
        countries=p.countries, age_min=p.age_min, age_max=p.age_max,
        locale_id=p.locale_id, objective=p.objective,
        optimization_goal=p.optimization_goal,
        custom_event_type=p.custom_event_type,
        url_tags=p.url_tags, config=p.config,
    )
    db.add(clone)
    db.commit()
    return RedirectResponse("/planning", status_code=303)


@router.post("/planning/bulk-delete")
async def planning_bulk_delete(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("selected_ids") if x.isdigit()]
    if ids:
        db.query(PlannedCampaign).filter(PlannedCampaign.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
    return RedirectResponse("/planning", status_code=303)


# ─── EXECUTE ────────────────────────────────────────────────────────────────
@router.post("/planning/{plan_id}/execute")
def planning_execute_one(plan_id: int, db: Session = Depends(get_db)):
    p = db.query(PlannedCampaign).filter(PlannedCampaign.id == plan_id).first()
    if not p:
        raise HTTPException(404)
    execute_plan(p, db)
    return RedirectResponse("/planning", status_code=303)


@router.post("/planning/execute-pending")
def planning_execute_all_pending(db: Session = Depends(get_db)):
    pendings = db.query(PlannedCampaign).filter(PlannedCampaign.status.in_(["pending", "error"])).all()
    for p in pendings:
        execute_plan(p, db)
    return RedirectResponse("/planning", status_code=303)
