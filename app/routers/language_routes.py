"""
Routers nuevos para Truco de Idiomas: media library, copy bundles, y campaign endpoint.

Para registrar en main.py:
    from .routers import language_routes
    app.include_router(language_routes.router)
"""
import os
import tempfile
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import FB_ACCESS_TOKEN
from ..services.language_models import MediaAsset, CopyBundle
from ..services.language_trick import (
    upload_image, upload_video,
    create_language_trick_campaign,
    DEFAULT_LANG_COPY,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────
# MEDIA LIBRARY
# ─────────────────────────────────────────────────────────────────

@router.get("/media")
def list_media(request: Request, db: Session = Depends(get_db)):
    items = db.query(MediaAsset).order_by(MediaAsset.created_at.desc()).all()
    return request.app.state.templates.TemplateResponse(request, "media/list.html", {
        "request": request, "items": items,
    })


@router.post("/media/upload")
async def upload_media(
    request: Request,
    db: Session = Depends(get_db),
    ad_account_id: str = Form(...),
    file: UploadFile = File(...),
    is_default: str = Form(""),
    language_label: str = Form("en_XX"),
    notes: str = Form(""),
):
    if not FB_ACCESS_TOKEN:
        raise HTTPException(400, "FB_ACCESS_TOKEN no configurado")

    # Guardar temporalmente
    suffix = os.path.splitext(file.filename)[1].lower()
    is_video = suffix in (".mp4", ".mov", ".avi", ".mkv")

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        act = ad_account_id if ad_account_id.startswith("act_") else f"act_{ad_account_id}"
        if is_video:
            meta_id = upload_video(act, FB_ACCESS_TOKEN, tmp_path, title=file.filename)
        else:
            meta_id = upload_image(act, FB_ACCESS_TOKEN, tmp_path)

        if not meta_id:
            raise HTTPException(500, "Upload a Meta falló")

        asset = MediaAsset(
            name=file.filename,
            type="video" if is_video else "image",
            local_path=tmp_path,
            meta_id=meta_id,
            ad_account_id=act,
            is_default=(is_default == "yes"),
            language_label=language_label,
            notes=notes,
        )
        db.add(asset)
        db.commit()
    finally:
        # Mantener archivo o borrar — aquí lo borramos al final
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


# ─────────────────────────────────────────────────────────────────
# COPY BUNDLES (multi-idioma)
# ─────────────────────────────────────────────────────────────────

@router.get("/copies")
def list_copies(request: Request, db: Session = Depends(get_db)):
    items = db.query(CopyBundle).order_by(CopyBundle.created_at.desc()).all()
    return request.app.state.templates.TemplateResponse(request, "copies/list.html", {
        "request": request, "items": items,
    })


@router.get("/copies/new")
def new_copy(request: Request):
    return request.app.state.templates.TemplateResponse(request, "copies/create.html", {
        "request": request, "default_copy": DEFAULT_LANG_COPY,
    })


@router.post("/copies")
async def create_copy(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    default_copy = {}
    for lang in ["fr", "ru", "ja", "ar"]:
        default_copy[lang] = {
            "body": form.get(f"{lang}_body", ""),
            "title": form.get(f"{lang}_title", ""),
            "desc": form.get(f"{lang}_desc", ""),
            "url": form.get(f"{lang}_url", "https://example.com"),
        }

    real_locales_raw = form.get("real_locales", "6")
    try:
        real_locales = [int(x.strip()) for x in real_locales_raw.split(",") if x.strip()]
    except ValueError:
        real_locales = [6]

    bundle = CopyBundle(
        name=form.get("name", "untitled"),
        real_body=form.get("real_body", ""),
        real_title=form.get("real_title", ""),
        real_desc=form.get("real_desc", ""),
        real_url=form.get("real_url", ""),
        real_label=form.get("real_label", "en_XX"),
        real_locales=real_locales,
        default_copy=default_copy,
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


# ─────────────────────────────────────────────────────────────────
# LANGUAGE TRICK CAMPAIGN ENDPOINT
# ─────────────────────────────────────────────────────────────────

@router.post("/campaigns/language-trick")
async def create_lang_campaign(request: Request, db: Session = Depends(get_db)):
    """
    Crea una campaña con truco de idiomas.
    Recibe: ad_account_id, page_id, pixel_id, name, country, age_min, age_max,
            media_asset_id (real), default_media_id (carnada), copy_bundle_id,
            daily_budget_usd, url_tags
    """
    form = await request.form()
    if not FB_ACCESS_TOKEN:
        raise HTTPException(400, "FB_ACCESS_TOKEN no configurado")

    real_asset = db.query(MediaAsset).filter(MediaAsset.id == int(form["media_asset_id"])).first()
    default_asset = db.query(MediaAsset).filter(MediaAsset.id == int(form["default_media_id"])).first()
    copy_bundle = db.query(CopyBundle).filter(CopyBundle.id == int(form["copy_bundle_id"])).first()

    if not real_asset or not default_asset or not copy_bundle:
        raise HTTPException(400, "Faltan assets o copy bundle")

    act = form["ad_account_id"]
    if not act.startswith("act_"):
        act = f"act_{act}"

    is_video = real_asset.type == "video"

    result = create_language_trick_campaign(
        act_id=act,
        token=FB_ACCESS_TOKEN,
        page_id=form["page_id"],
        pixel_id=form["pixel_id"],
        name=form["name"],
        country=form.get("country", "US"),
        age_min=int(form.get("age_min", "40")),
        age_max=int(form.get("age_max", "65")),
        real_locales=copy_bundle.real_locales or [6],
        real_label=copy_bundle.real_label,
        real_media_id=real_asset.meta_id,
        default_media_id=default_asset.meta_id,
        is_video=is_video,
        real_body=copy_bundle.real_body,
        real_title=copy_bundle.real_title,
        real_desc=copy_bundle.real_desc or "",
        real_url=copy_bundle.real_url,
        url_tags=form.get("url_tags", ""),
        daily_budget_cents=int(float(form.get("daily_budget_usd", "1.50")) * 100),
        default_copy=copy_bundle.default_copy,
        is_cbo=(form.get("cbo_or_abo", "ABO") == "CBO"),
    )

    if result.get("errors"):
        return JSONResponse({"ok": False, "errors": result["errors"], "ids": result}, status_code=400)
    return JSONResponse({"ok": True, "ids": result})
