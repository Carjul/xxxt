"""
Rutas del truco de idiomas (rediseñado):
  /media        — creativos (URL pública + opcional subida a Meta)
  /carnadas     — biblioteca global de carnadas por idioma
  /copies       — paquetes de copy (real + qué carnadas usar)
  /campaigns/language-trick — crear campaña con el truco
"""
import os
import tempfile
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from typing import Any as Session

from ..database import get_db
from ..meta_connections import get_active_token, get_effective_defaults
from ..services.language_models import MediaAsset, CopyBundle, LanguageCarnada
from ..services.meta_locales import META_LOCALES, locale_by_id
from ..services.language_trick import (
    upload_image, upload_video,
    create_language_trick_campaign,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────
# MEDIA / CREATIVOS (Sheet-style con URL)
# ─────────────────────────────────────────────────────────────────

@router.get("/media")
def list_media(request: Request, db: Session = Depends(get_db)):
    items = db.query(MediaAsset).order_by(MediaAsset.created_at.desc()).all()
    defaults = get_effective_defaults(db)
    return request.app.state.templates.TemplateResponse(request, "media/list.html", {
        "request": request, "items": items, "default_ad_account": defaults["ad_account_id"] or "",
    })


@router.post("/media")
def create_media(
    db: Session = Depends(get_db),
    name: str = Form(...),
    type: str = Form("image"),
    public_url: str = Form(...),
    notes: str = Form(""),
    is_default: str = Form(""),
):
    asset = MediaAsset(
        name=name.strip(),
        type=type if type in ("image", "video") else "image",
        public_url=public_url.strip(),
        notes=notes,
        uploaded_to_meta=False,
        is_default=(is_default == "yes"),
    )
    db.add(asset)
    db.commit()
    return RedirectResponse("/media", status_code=303)


@router.post("/media/{media_id}/upload")
def upload_media_to_meta(
    media_id: int,
    db: Session = Depends(get_db),
    ad_account_id: str = Form(""),
):
    """Descarga la URL pública y la sube a Meta. Marca uploaded_to_meta=True."""
    token = get_active_token(db)
    if not token:
        raise HTTPException(400, "No hay conexion Meta activa")

    m = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if not m or not m.public_url:
        raise HTTPException(400, "Creativo no encontrado o sin URL")

    act = (ad_account_id or m.ad_account_id or "").strip()
    if not act:
        raise HTTPException(400, "Indica ad_account_id (ej: act_123456789)")
    if not act.startswith("act_"):
        act = f"act_{act}"

    suffix = os.path.splitext(urlparse(m.public_url).path)[1].lower() or (".mp4" if m.type == "video" else ".jpg")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        try:
            with requests.get(m.public_url, stream=True, timeout=300) as r:
                r.raise_for_status()
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    tmp.write(chunk)
            tmp_path = tmp.name
        except Exception as e:
            raise HTTPException(400, f"No se pudo descargar la URL: {e}")

    try:
        if m.type == "video":
            meta_id = upload_video(act, token, tmp_path, title=m.name)
        else:
            meta_id = upload_image(act, token, tmp_path)

        if not meta_id:
            raise HTTPException(500, "Upload a Meta falló")

        m.meta_id = meta_id
        m.ad_account_id = act
        m.uploaded_to_meta = True
        db.commit()
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    return RedirectResponse("/media", status_code=303)


@router.post("/media/{media_id}/delete")
def delete_media(media_id: int, db: Session = Depends(get_db)):
    m = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if m:
        db.delete(m)
        db.commit()
    return RedirectResponse("/media", status_code=303)


@router.post("/media/bulk-delete")
async def bulk_delete_media(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("selected_ids") if x.isdigit()]
    if ids:
        db.query(MediaAsset).filter(MediaAsset.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
    return RedirectResponse("/media", status_code=303)


@router.get("/media/{media_id}/edit")
def edit_media_form(media_id: int, request: Request, db: Session = Depends(get_db)):
    m = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if not m:
        raise HTTPException(404, "No encontrado")
    return request.app.state.templates.TemplateResponse(request, "media/edit.html", {
        "request": request, "item": m,
    })


@router.post("/media/{media_id}/edit")
def edit_media(
    media_id: int,
    db: Session = Depends(get_db),
    name: str = Form(...),
    type: str = Form("image"),
    public_url: str = Form(...),
    notes: str = Form(""),
    is_default: str = Form(""),
):
    m = db.query(MediaAsset).filter(MediaAsset.id == media_id).first()
    if not m:
        raise HTTPException(404, "No encontrado")
    m.name = name.strip()
    m.type = type if type in ("image", "video") else "image"
    m.public_url = public_url.strip()
    m.notes = notes
    m.is_default = (is_default == "yes")
    db.commit()
    return RedirectResponse("/media", status_code=303)


# ─────────────────────────────────────────────────────────────────
# CARNADAS (biblioteca global por idioma)
# ─────────────────────────────────────────────────────────────────

@router.get("/carnadas")
def list_carnadas(request: Request, db: Session = Depends(get_db)):
    items = db.query(LanguageCarnada).order_by(LanguageCarnada.created_at.desc()).all()
    return request.app.state.templates.TemplateResponse(request, "carnadas/list.html", {
        "request": request, "items": items, "locales": META_LOCALES,
    })


@router.post("/carnadas")
def create_carnada(
    db: Session = Depends(get_db),
    locale_id: int = Form(...),
    body: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    url: str = Form(...),
    notes: str = Form(""),
):
    info = locale_by_id(locale_id)
    if not info:
        raise HTTPException(400, "Locale ID no reconocido")
    c = LanguageCarnada(
        locale_id=locale_id,
        locale_code=info["code"],
        language_name=info["name"],
        body=body, title=title, description=description, url=url, notes=notes,
    )
    db.add(c)
    db.commit()
    return RedirectResponse("/carnadas", status_code=303)


@router.post("/carnadas/{carnada_id}/delete")
def delete_carnada(carnada_id: int, db: Session = Depends(get_db)):
    c = db.query(LanguageCarnada).filter(LanguageCarnada.id == carnada_id).first()
    if c:
        db.delete(c)
        db.commit()
    return RedirectResponse("/carnadas", status_code=303)


@router.post("/carnadas/bulk-delete")
async def bulk_delete_carnadas(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    ids = [int(x) for x in form.getlist("selected_ids") if x.isdigit()]
    if ids:
        db.query(LanguageCarnada).filter(LanguageCarnada.id.in_(ids)).delete(synchronize_session=False)
        db.commit()
    return RedirectResponse("/carnadas", status_code=303)


@router.get("/carnadas/{carnada_id}/edit")
def edit_carnada_form(carnada_id: int, request: Request, db: Session = Depends(get_db)):
    c = db.query(LanguageCarnada).filter(LanguageCarnada.id == carnada_id).first()
    if not c:
        raise HTTPException(404, "No encontrado")
    return request.app.state.templates.TemplateResponse(request, "carnadas/edit.html", {
        "request": request, "item": c, "locales": META_LOCALES,
    })


@router.post("/carnadas/{carnada_id}/edit")
def edit_carnada(
    carnada_id: int,
    db: Session = Depends(get_db),
    locale_id: int = Form(...),
    body: str = Form(...),
    title: str = Form(...),
    description: str = Form(""),
    url: str = Form(...),
    notes: str = Form(""),
):
    c = db.query(LanguageCarnada).filter(LanguageCarnada.id == carnada_id).first()
    if not c:
        raise HTTPException(404, "No encontrado")
    info = locale_by_id(locale_id)
    if not info:
        raise HTTPException(400, "Locale ID no reconocido")
    c.locale_id = locale_id
    c.locale_code = info["code"]
    c.language_name = info["name"]
    c.body = body
    c.title = title
    c.description = description
    c.url = url
    c.notes = notes
    db.commit()
    return RedirectResponse("/carnadas", status_code=303)


# ─────────────────────────────────────────────────────────────────
# COPY BUNDLES
# ─────────────────────────────────────────────────────────────────

@router.get("/copies")
def list_copies(request: Request, db: Session = Depends(get_db)):
    items = db.query(CopyBundle).order_by(CopyBundle.created_at.desc()).all()
    return request.app.state.templates.TemplateResponse(request, "copies/list.html", {
        "request": request, "items": items,
    })


@router.get("/copies/new")
def new_copy(request: Request, db: Session = Depends(get_db)):
    carnadas = db.query(LanguageCarnada).order_by(LanguageCarnada.language_name).all()
    return request.app.state.templates.TemplateResponse(request, "copies/create.html", {
        "request": request, "locales": META_LOCALES, "carnadas": carnadas,
    })


@router.post("/copies")
async def create_copy(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    try:
        target_locale_id = int(form.get("target_locale_id", "6"))
    except ValueError:
        target_locale_id = 6
    info = locale_by_id(target_locale_id) or {"code": "en_XX"}

    # Respeta el orden de clic (carnada_order viene del JS); si no, cae al orden DOM
    order_raw = form.get("carnada_order", "")
    ordered_ids = [int(x) for x in order_raw.split(",") if x.strip().isdigit()] if order_raw else []
    selected_ids = {int(x) for x in form.getlist("carnada_ids") if x.isdigit()}
    carnada_ids = [i for i in ordered_ids if i in selected_ids]
    # añadir los que quedaron sin orden (defensa)
    for i in selected_ids:
        if i not in carnada_ids:
            carnada_ids.append(i)

    bundle = CopyBundle(
        name=form.get("name", "untitled"),
        real_body=form.get("real_body", ""),
        real_title=form.get("real_title", ""),
        real_desc=form.get("real_desc", ""),
        real_url=form.get("real_url", ""),
        target_locale_id=target_locale_id,
        target_locale_code=info["code"],
        carnada_ids=carnada_ids,
        # legacy compat
        real_label=info["code"],
        real_locales=[target_locale_id],
        default_copy={},
    )
    db.add(bundle)
    db.commit()
    return RedirectResponse("/copies", status_code=303)


@router.post("/copies/{copy_id}/delete")
def delete_copy(copy_id: int, db: Session = Depends(get_db)):
    c = db.query(CopyBundle).filter(CopyBundle.id == copy_id).first()
    if c:
        db.delete(c)
        db.commit()
    return RedirectResponse("/copies", status_code=303)


@router.get("/copies/{copy_id}/edit")
def edit_copy_form(copy_id: int, request: Request, db: Session = Depends(get_db)):
    c = db.query(CopyBundle).filter(CopyBundle.id == copy_id).first()
    if not c:
        raise HTTPException(404, "No encontrado")
    carnadas = db.query(LanguageCarnada).order_by(LanguageCarnada.language_name).all()
    selected_ids = c.carnada_ids or []
    return request.app.state.templates.TemplateResponse(request, "copies/edit.html", {
        "request": request, "item": c, "locales": META_LOCALES,
        "carnadas": carnadas, "selected_ids": selected_ids,
    })


@router.post("/copies/{copy_id}/edit")
async def edit_copy(copy_id: int, request: Request, db: Session = Depends(get_db)):
    c = db.query(CopyBundle).filter(CopyBundle.id == copy_id).first()
    if not c:
        raise HTTPException(404, "No encontrado")
    form = await request.form()
    try:
        target_locale_id = int(form.get("target_locale_id", "6"))
    except ValueError:
        target_locale_id = 6
    info = locale_by_id(target_locale_id) or {"code": "en_XX"}

    order_raw = form.get("carnada_order", "")
    ordered_ids = [int(x) for x in order_raw.split(",") if x.strip().isdigit()] if order_raw else []
    selected_ids = {int(x) for x in form.getlist("carnada_ids") if x.isdigit()}
    carnada_ids = [i for i in ordered_ids if i in selected_ids]
    for i in selected_ids:
        if i not in carnada_ids:
            carnada_ids.append(i)

    c.name = form.get("name", c.name)
    c.real_body = form.get("real_body", "")
    c.real_title = form.get("real_title", "")
    c.real_desc = form.get("real_desc", "")
    c.real_url = form.get("real_url", "")
    c.target_locale_id = target_locale_id
    c.target_locale_code = info["code"]
    c.carnada_ids = carnada_ids
    db.commit()
    return RedirectResponse("/copies", status_code=303)


# ─────────────────────────────────────────────────────────────────
# WIZARD: Selector de tipo + Campaña de idiomas con N ads
# ─────────────────────────────────────────────────────────────────

@router.get("/campaigns/new-type")
def new_campaign_type(request: Request):
    return request.app.state.templates.TemplateResponse(request, "campaigns/new_type.html", {
        "request": request,
    })


@router.get("/campaigns/new-language")
def new_lang_wizard(request: Request, db: Session = Depends(get_db)):
    from .. import meta_api
    from ..models import AppSettings

    media = db.query(MediaAsset).order_by(MediaAsset.name).all()
    copies = db.query(CopyBundle).order_by(CopyBundle.name).all()
    settings = db.query(AppSettings).first()
    if not settings:
        settings = AppSettings()
        db.add(settings)
        db.commit()
    defaults = get_effective_defaults(db)
    for key, value in defaults.items():
        setattr(settings, f"default_{key}", value)

    accounts, pages, pixels = [], [], []
    try:
        token = get_active_token(db)
        accounts = meta_api.list_ad_accounts(token=token)
        pages = meta_api.list_pages(token=token)
        if settings and settings.default_ad_account_id:
            try:
                pixels = meta_api.list_pixels(settings.default_ad_account_id, token=token)
            except Exception:
                pass
    except Exception:
        pass

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
        ("OFFSITE_CONVERSIONS", "Conversiones (pixel) — recomendado para Compra/Lead"),
        ("LANDING_PAGE_VIEWS", "Vistas de landing page"),
        ("LINK_CLICKS", "Clics en enlace"),
        ("IMPRESSIONS", "Impresiones"),
        ("REACH", "Alcance"),
        ("LEAD_GENERATION", "Generación de leads (formulario nativo FB)"),
    ]

    CTAS = ["LEARN_MORE", "SHOP_NOW", "SIGN_UP", "SUBSCRIBE", "GET_OFFER", "APPLY_NOW", "DOWNLOAD", "CONTACT_US"]

    return request.app.state.templates.TemplateResponse(request, "campaigns/new_language.html", {
        "request": request, "media": media, "copies": copies,
        "accounts": accounts, "pages": pages, "pixels": pixels,
        "settings": settings, "locales": META_LOCALES,
        "bid_strategies": BID_STRATEGIES,
        "objectives": OBJECTIVES, "event_types": EVENT_TYPES,
        "optimization_goals": OPTIMIZATION_GOALS, "ctas": CTAS,
    })


@router.get("/campaigns/new-normal")
def new_normal_wizard(request: Request, db: Session = Depends(get_db)):
    from .. import meta_api
    from ..models import AppSettings

    media = db.query(MediaAsset).order_by(MediaAsset.name).all()
    settings = db.query(AppSettings).first()
    if not settings:
        settings = AppSettings()
        db.add(settings)
        db.commit()
    defaults = get_effective_defaults(db)
    for key, value in defaults.items():
        setattr(settings, f"default_{key}", value)

    accounts, pages, pixels = [], [], []
    try:
        token = get_active_token(db)
        accounts = meta_api.list_ad_accounts(token=token)
        pages = meta_api.list_pages(token=token)
        if settings and settings.default_ad_account_id:
            try:
                pixels = meta_api.list_pixels(settings.default_ad_account_id, token=token)
            except Exception:
                pass
    except Exception:
        pass

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
        ("OFFSITE_CONVERSIONS", "Conversiones (pixel) — recomendado para Compra/Lead"),
        ("LANDING_PAGE_VIEWS", "Vistas de landing page"),
        ("LINK_CLICKS", "Clics en enlace"),
        ("IMPRESSIONS", "Impresiones"),
        ("REACH", "Alcance"),
    ]
    CTAS = ["LEARN_MORE", "SHOP_NOW", "SIGN_UP", "SUBSCRIBE", "GET_OFFER", "APPLY_NOW", "DOWNLOAD", "CONTACT_US"]

    return request.app.state.templates.TemplateResponse(request, "campaigns/new_normal.html", {
        "request": request, "media": media,
        "accounts": accounts, "pages": pages, "pixels": pixels,
        "settings": settings, "locales": META_LOCALES,
        "bid_strategies": BID_STRATEGIES, "objectives": OBJECTIVES,
        "event_types": EVENT_TYPES, "optimization_goals": OPTIMIZATION_GOALS,
        "ctas": CTAS,
    })


@router.post("/campaigns/new-normal")
async def post_normal_wizard(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    token = get_active_token(db)
    if not token:
        raise HTTPException(400, "No hay conexion Meta activa")

    act = form.get("ad_account_id", "").strip()
    if not act.startswith("act_"):
        act = f"act_{act}"

    import re
    ad_indices = set()
    pattern = re.compile(r"^ads\[(\d+)\]\[")
    for key in form.keys():
        m = pattern.match(key)
        if m:
            ad_indices.add(int(m.group(1)))
    if not ad_indices:
        raise HTTPException(400, "Necesitas al menos 1 ad")

    ads_data = []
    for idx in sorted(ad_indices):
        media_id_raw = form.get(f"ads[{idx}][media_asset_id]")
        if not media_id_raw:
            continue
        asset = db.query(MediaAsset).filter(MediaAsset.id == int(media_id_raw)).first()
        if not asset:
            raise HTTPException(400, f"Ad #{idx+1}: creativo no encontrado")
        if not asset.uploaded_to_meta or not asset.meta_id:
            raise HTTPException(400, f"El creativo '{asset.name}' no está en Meta. Ve a /media y dale 'Subir a Meta'.")

        ads_data.append({
            "is_video": asset.type == "video",
            "meta_id": asset.meta_id,
            "body": form.get(f"ads[{idx}][body]", ""),
            "title": form.get(f"ads[{idx}][title]", ""),
            "description": form.get(f"ads[{idx}][description]", ""),
            "link": form.get(f"ads[{idx}][link]", ""),
            "cta_type": form.get(f"ads[{idx}][cta_type]", "LEARN_MORE"),
        })

    if not ads_data:
        raise HTTPException(400, "No completaste ningún ad")

    countries = [c.strip().upper() for c in form.get("countries", "US").split(",") if c.strip()] or ["US"]
    bid_amount_raw = (form.get("bid_amount") or "").strip()
    bid_amount_cents = int(float(bid_amount_raw) * 100) if bid_amount_raw else 0
    roas_floor_raw = (form.get("roas_floor") or "").strip()
    roas_floor = float(roas_floor_raw) if roas_floor_raw else 0.0

    from ..services.normal_campaign import create_normal_multi_ad
    result = create_normal_multi_ad(
        act_id=act, token=token,
        page_id=form["page_id"], pixel_id=form["pixel_id"],
        name=form["name"],
        countries=countries,
        age_min=int(form.get("age_min", "18")),
        age_max=int(form.get("age_max", "65")),
        locale_id=int(form.get("locale_id", "6")),
        daily_budget_cents=int(float(form.get("daily_budget_usd", "5")) * 100),
        is_cbo=(form.get("cbo_or_abo", "ABO") == "CBO"),
        ads=ads_data,
        objective=form.get("objective", "OUTCOME_SALES"),
        optimization_goal=form.get("optimization_goal", "OFFSITE_CONVERSIONS"),
        custom_event_type=form.get("custom_event_type", "PURCHASE"),
        bid_strategy=form.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP"),
        bid_amount_cents=bid_amount_cents,
        roas_floor=roas_floor,
        instagram_id=form.get("instagram_id", "").strip(),
        url_tags=form.get("url_tags", ""),
    )
    status = 200 if not result.get("errors") else 400
    return JSONResponse({"ok": status == 200, "result": result}, status_code=status)


@router.post("/campaigns/new-language")
async def post_lang_wizard(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    token = get_active_token(db)
    if not token:
        raise HTTPException(400, "No hay conexion Meta activa")

    act = form.get("ad_account_id", "").strip()
    if not act.startswith("act_"):
        act = f"act_{act}"

    # Parsear los ads del form (ads[0][media_asset_id], etc.)
    import re
    ad_indices = set()
    pattern = re.compile(r"^ads\[(\d+)\]\[")
    for key in form.keys():
        m = pattern.match(key)
        if m:
            ad_indices.add(int(m.group(1)))

    if not ad_indices:
        raise HTTPException(400, "Necesitas al menos 1 ad")

    ads_data = []
    for idx in sorted(ad_indices):
        media_id_raw = form.get(f"ads[{idx}][media_asset_id]")
        default_id_raw = form.get(f"ads[{idx}][default_media_id]")
        copy_id_raw = form.get(f"ads[{idx}][copy_bundle_id]")
        if not (media_id_raw and default_id_raw and copy_id_raw):
            continue  # slot vacío, lo saltamos

        real_asset = db.query(MediaAsset).filter(MediaAsset.id == int(media_id_raw)).first()
        default_asset = db.query(MediaAsset).filter(MediaAsset.id == int(default_id_raw)).first()
        bundle = db.query(CopyBundle).filter(CopyBundle.id == int(copy_id_raw)).first()
        if not (real_asset and default_asset and bundle):
            raise HTTPException(400, f"Ad #{idx+1}: asset o bundle no encontrado")

        # Asegurar que estén subidos a Meta
        for a in (real_asset, default_asset):
            if not a.uploaded_to_meta or not a.meta_id:
                raise HTTPException(400, f"El creativo '{a.name}' aún no se subió a Meta. Ve a /media y dale 'Subir a Meta'.")

        carnadas_objs = db.query(LanguageCarnada).filter(
            LanguageCarnada.id.in_(bundle.carnada_ids or [])
        ).all()
        if not carnadas_objs:
            raise HTTPException(400, f"El paquete '{bundle.name}' no tiene carnadas")
        # Respetar el orden de carnada_ids del bundle
        carnadas_by_id = {c.id: c for c in carnadas_objs}
        carnadas_ordered = [carnadas_by_id[i] for i in (bundle.carnada_ids or []) if i in carnadas_by_id]

        carnadas = [{
            "locale_id": c.locale_id, "locale_code": c.locale_code,
            "body": c.body, "title": c.title, "desc": c.description, "url": c.url,
        } for c in carnadas_ordered]

        ads_data.append({
            "target_locale_id": bundle.target_locale_id or 6,
            "target_locale_code": bundle.target_locale_code or "en_XX",
            "real_media_id": real_asset.meta_id,
            "default_media_id": default_asset.meta_id,
            "is_video": real_asset.type == "video",
            "real_body": bundle.real_body,
            "real_title": bundle.real_title,
            "real_desc": bundle.real_desc or "",
            "real_url": bundle.real_url,
            "url_tags": form.get("url_tags", ""),
            "carnadas": carnadas,
            "cta_type": form.get(f"ads[{idx}][cta_type]", "LEARN_MORE"),
        })

    if not ads_data:
        raise HTTPException(400, "No completaste ningún ad (falta creativo/copy en todos los slots)")

    # Países (coma-separados)
    countries = [c.strip().upper() for c in form.get("countries", "US").split(",") if c.strip()]
    if not countries:
        countries = ["US"]

    # Bid amount: viene en USD, Meta usa centavos
    bid_amount_raw = (form.get("bid_amount") or "").strip()
    bid_amount_cents = int(float(bid_amount_raw) * 100) if bid_amount_raw else 0
    roas_floor_raw = (form.get("roas_floor") or "").strip()
    roas_floor = float(roas_floor_raw) if roas_floor_raw else 0.0

    from ..services.language_trick import create_language_trick_multi_ad
    result = create_language_trick_multi_ad(
        act_id=act,
        token=token,
        page_id=form["page_id"],
        pixel_id=form["pixel_id"],
        name=form["name"],
        countries=countries,
        age_min=int(form.get("age_min", "40")),
        age_max=int(form.get("age_max", "65")),
        adset_locale_id=int(form.get("adset_locale_id", "6")),
        daily_budget_cents=int(float(form.get("daily_budget_usd", "1.50")) * 100),
        is_cbo=(form.get("cbo_or_abo", "ABO") == "CBO"),
        ads=ads_data,
        objective=form.get("objective", "OUTCOME_SALES"),
        optimization_goal=form.get("optimization_goal", "OFFSITE_CONVERSIONS"),
        custom_event_type=form.get("custom_event_type", "PURCHASE"),
        bid_strategy=form.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP"),
        bid_amount_cents=bid_amount_cents,
        roas_floor=roas_floor,
        instagram_id=form.get("instagram_id", "").strip(),
    )

    status = 200 if not result.get("errors") else 400
    return JSONResponse({"ok": status == 200, "result": result}, status_code=status)


# ─────────────────────────────────────────────────────────────────
# LANGUAGE TRICK CAMPAIGN (single-ad, legacy)
# ─────────────────────────────────────────────────────────────────

@router.post("/campaigns/language-trick")
async def create_lang_campaign(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    token = get_active_token(db)
    if not token:
        raise HTTPException(400, "No hay conexion Meta activa")

    real_asset = db.query(MediaAsset).filter(MediaAsset.id == int(form["media_asset_id"])).first()
    default_asset = db.query(MediaAsset).filter(MediaAsset.id == int(form["default_media_id"])).first()
    copy_bundle = db.query(CopyBundle).filter(CopyBundle.id == int(form["copy_bundle_id"])).first()

    if not real_asset or not default_asset or not copy_bundle:
        raise HTTPException(400, "Faltan assets o copy bundle")

    act = form["ad_account_id"]
    if not act.startswith("act_"):
        act = f"act_{act}"

    # Auto-subir a Meta si todavía no se subieron
    for asset in (real_asset, default_asset):
        if not asset.uploaded_to_meta or not asset.meta_id:
            raise HTTPException(400, f"El creativo '{asset.name}' aún no se subió a Meta. Ve a /media y dale 'Subir a Meta'.")

    # Construir lista de carnadas desde el bundle
    carnadas_objs = db.query(LanguageCarnada).filter(
        LanguageCarnada.id.in_(copy_bundle.carnada_ids or [])
    ).all()
    carnadas = [{
        "locale_id": c.locale_id, "locale_code": c.locale_code,
        "body": c.body, "title": c.title, "desc": c.description, "url": c.url,
    } for c in carnadas_objs]

    if not carnadas:
        raise HTTPException(400, "El paquete de copy no tiene carnadas seleccionadas.")

    is_video = real_asset.type == "video"

    result = create_language_trick_campaign(
        act_id=act,
        token=token,
        page_id=form["page_id"],
        pixel_id=form["pixel_id"],
        name=form["name"],
        country=form.get("country", "US"),
        age_min=int(form.get("age_min", "40")),
        age_max=int(form.get("age_max", "65")),
        target_locale_id=copy_bundle.target_locale_id,
        target_locale_code=copy_bundle.target_locale_code,
        real_media_id=real_asset.meta_id,
        default_media_id=default_asset.meta_id,
        is_video=is_video,
        real_body=copy_bundle.real_body,
        real_title=copy_bundle.real_title,
        real_desc=copy_bundle.real_desc or "",
        real_url=copy_bundle.real_url,
        url_tags=form.get("url_tags", ""),
        daily_budget_cents=int(float(form.get("daily_budget_usd", "1.50")) * 100),
        carnadas=carnadas,
        is_cbo=(form.get("cbo_or_abo", "ABO") == "CBO"),
    )

    if result.get("errors"):
        return JSONResponse({"ok": False, "errors": result["errors"], "ids": result}, status_code=400)
    return JSONResponse({"ok": True, "ids": result})
