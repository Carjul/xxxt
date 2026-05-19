import secrets
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from typing import Any as Session

from .. import meta_api
from ..database import get_db
from ..meta_connections import get_effective_defaults
from ..models import Catalog, AppSettings
from ..config import PUBLIC_BASE_URL

router = APIRouter()


@router.get("/catalogs")
def list_catalogs(request: Request, db: Session = Depends(get_db)):
    catalogs = db.query(Catalog).order_by(Catalog.created_at.desc()).all()
    return request.app.state.templates.TemplateResponse(request, "catalogs/list.html", {
        "request": request, "catalogs": catalogs,
        "public_base": PUBLIC_BASE_URL,
    })


@router.get("/catalogs/new")
def new_catalog(request: Request, db: Session = Depends(get_db)):
    s = db.query(AppSettings).first()
    if not s:
        s = AppSettings()
        db.add(s)
        db.commit()
    defaults = get_effective_defaults(db)
    for key, value in defaults.items():
        setattr(s, f"default_{key}", value)
    return request.app.state.templates.TemplateResponse(request, "catalogs/create.html", {
        "request": request, "settings": s,
    })


@router.post("/catalogs")
def create_catalog(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    business_id: str = Form(...),
    pixel_id: str = Form(""),
    sync_to_meta: str = Form(""),
):
    feed_slug = secrets.token_urlsafe(8)

    fb_catalog_id = ""
    fb_feed_id = None
    error = None

    if sync_to_meta == "yes":
        try:
            res = meta_api.create_catalog(business_id, name)
            fb_catalog_id = res["id"]
            if pixel_id:
                try:
                    meta_api.attach_pixel_to_catalog(fb_catalog_id, pixel_id)
                except Exception as e:
                    error = f"Catálogo creado pero falló asociar pixel: {e}"
            csv_url = f"{PUBLIC_BASE_URL}/feed/{feed_slug}.csv"
            try:
                feed_res = meta_api.create_feed(fb_catalog_id, f"Feed {name}", csv_url)
                fb_feed_id = feed_res.get("id")
            except Exception as e:
                error = (error + " | " if error else "") + f"Feed no creado: {e}"
        except Exception as e:
            s = db.query(AppSettings).first()
            if s:
                defaults = get_effective_defaults(db)
                for key, value in defaults.items():
                    setattr(s, f"default_{key}", value)
            return request.app.state.templates.TemplateResponse(request, "catalogs/create.html", {
                "request": request, "settings": s,
                "error": f"Error creando catálogo en Meta: {e}",
                "form": {"name": name, "business_id": business_id, "pixel_id": pixel_id},
            })
    else:
        fb_catalog_id = f"local-{feed_slug}"

    cat = Catalog(
        name=name,
        fb_catalog_id=fb_catalog_id,
        business_id=business_id,
        feed_slug=feed_slug,
        fb_feed_id=fb_feed_id,
    )
    db.add(cat)
    db.commit()
    db.refresh(cat)

    return RedirectResponse(f"/catalogs/{cat.id}/products", status_code=303)


@router.post("/catalogs/{cat_id}/delete")
def delete_catalog(cat_id: int, db: Session = Depends(get_db)):
    cat = db.query(Catalog).filter(Catalog.id == cat_id).first()
    if not cat:
        raise HTTPException(404)
    db.delete(cat)
    db.commit()
    return RedirectResponse("/catalogs", status_code=303)
