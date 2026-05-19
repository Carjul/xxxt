from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from typing import Any as Session

from .. import meta_api
from ..database import get_db
from ..models import Catalog, Product, ProductSet

router = APIRouter()


def _build_set_name(products: list[Product]) -> str:
    """Genera nombre tipo 05_L01_V1+V2+V3 según video_labels."""
    labels = [p.video_label for p in products if p.video_label]
    if not labels:
        ids = [p.retailer_id for p in products]
        return "+".join(ids)

    base_parts = labels[0].split("_")
    if len(base_parts) >= 3:
        base = "_".join(base_parts[:2])
    else:
        base = ""

    versions = []
    for label in labels:
        parts = label.split("_")
        if len(parts) >= 3:
            versions.append(parts[-1])
        else:
            versions.append(label)

    if base:
        return f"{base}_{'+'.join(versions)}"
    return "+".join(versions)


@router.get("/catalogs/{cat_id}/sets")
def list_sets(cat_id: int, request: Request, db: Session = Depends(get_db)):
    cat = db.query(Catalog).filter(Catalog.id == cat_id).first()
    if not cat:
        raise HTTPException(404)
    sets = db.query(ProductSet).filter(ProductSet.catalog_id == cat_id).all()
    products = db.query(Product).filter(Product.catalog_id == cat_id).all()
    return request.app.state.templates.TemplateResponse(request, "sets/list.html", {
        "request": request, "catalog": cat, "sets": sets, "products": products,
    })


@router.get("/catalogs/{cat_id}/sets/new")
def new_set(cat_id: int, request: Request, db: Session = Depends(get_db)):
    cat = db.query(Catalog).filter(Catalog.id == cat_id).first()
    if not cat:
        raise HTTPException(404)
    products = db.query(Product).filter(Product.catalog_id == cat_id).all()
    return request.app.state.templates.TemplateResponse(request, "sets/builder.html", {
        "request": request, "catalog": cat, "products": products,
    })


@router.post("/catalogs/{cat_id}/sets")
async def create_set(cat_id: int, request: Request, db: Session = Depends(get_db)):
    cat = db.query(Catalog).filter(Catalog.id == cat_id).first()
    if not cat:
        raise HTTPException(404)

    form = await request.form()
    selected_ids = form.getlist("product_ids")
    custom_name = (form.get("name") or "").strip()
    sync_to_meta = form.get("sync_to_meta") == "yes"

    if not selected_ids:
        return RedirectResponse(f"/catalogs/{cat_id}/sets/new?error=select_at_least_one", status_code=303)

    products = db.query(Product).filter(
        Product.catalog_id == cat_id,
        Product.id.in_([int(x) for x in selected_ids])
    ).all()

    name = custom_name or _build_set_name(products)
    retailer_ids = [p.retailer_id for p in products]

    fb_set_id = None
    if sync_to_meta and not cat.fb_catalog_id.startswith("local-"):
        try:
            res = meta_api.create_product_set(cat.fb_catalog_id, name, retailer_ids)
            fb_set_id = res.get("id")
        except Exception as e:
            return RedirectResponse(f"/catalogs/{cat_id}/sets/new?error={str(e)[:80]}", status_code=303)

    pset = ProductSet(catalog_id=cat_id, name=name, retailer_ids=retailer_ids, fb_set_id=fb_set_id)
    db.add(pset)
    db.commit()

    return RedirectResponse(f"/catalogs/{cat_id}/sets", status_code=303)


@router.get("/catalogs/{cat_id}/sets/{set_id}/edit")
def edit_set(cat_id: int, set_id: int, request: Request, db: Session = Depends(get_db)):
    cat = db.query(Catalog).filter(Catalog.id == cat_id).first()
    pset = db.query(ProductSet).filter(ProductSet.id == set_id).first()
    if not cat or not pset:
        raise HTTPException(404)
    products = db.query(Product).filter(Product.catalog_id == cat_id).all()
    return request.app.state.templates.TemplateResponse(request, "sets/builder.html", {
        "request": request, "catalog": cat, "products": products,
        "pset": pset, "selected_ids": [p.id for p in products if p.retailer_id in (pset.retailer_ids or [])],
    })


@router.post("/catalogs/{cat_id}/sets/{set_id}")
async def update_set(cat_id: int, set_id: int, request: Request, db: Session = Depends(get_db)):
    cat = db.query(Catalog).filter(Catalog.id == cat_id).first()
    pset = db.query(ProductSet).filter(ProductSet.id == set_id).first()
    if not cat or not pset:
        raise HTTPException(404)

    form = await request.form()
    selected_ids = form.getlist("product_ids")
    custom_name = (form.get("name") or "").strip()
    sync_to_meta = form.get("sync_to_meta") == "yes"

    if not selected_ids:
        return RedirectResponse(f"/catalogs/{cat_id}/sets/{set_id}/edit?error=select_at_least_one", status_code=303)

    products = db.query(Product).filter(
        Product.catalog_id == cat_id,
        Product.id.in_([int(x) for x in selected_ids])
    ).all()

    name = custom_name or _build_set_name(products)
    retailer_ids = [p.retailer_id for p in products]
    pset.name = name
    pset.retailer_ids = retailer_ids

    if sync_to_meta and not cat.fb_catalog_id.startswith("local-"):
        try:
            if pset.fb_set_id:
                meta_api.update_product_set(pset.fb_set_id, name, retailer_ids)
            else:
                res = meta_api.create_product_set(cat.fb_catalog_id, name, retailer_ids)
                pset.fb_set_id = res.get("id")
        except Exception as e:
            return RedirectResponse(f"/catalogs/{cat_id}/sets/{set_id}/edit?error={str(e)[:80]}", status_code=303)

    db.commit()
    return RedirectResponse(f"/catalogs/{cat_id}/sets", status_code=303)


@router.post("/catalogs/{cat_id}/sets/{set_id}/sync")
def sync_set(cat_id: int, set_id: int, db: Session = Depends(get_db)):
    cat = db.query(Catalog).filter(Catalog.id == cat_id).first()
    pset = db.query(ProductSet).filter(ProductSet.id == set_id).first()
    if not cat or not pset:
        raise HTTPException(404)
    if cat.fb_catalog_id.startswith("local-"):
        return RedirectResponse(f"/catalogs/{cat_id}/sets?error=catalog_not_synced", status_code=303)
    try:
        if pset.fb_set_id:
            meta_api.update_product_set(pset.fb_set_id, pset.name, pset.retailer_ids or [])
        else:
            res = meta_api.create_product_set(cat.fb_catalog_id, pset.name, pset.retailer_ids or [])
            pset.fb_set_id = res.get("id")
        db.commit()
    except Exception as e:
        return RedirectResponse(f"/catalogs/{cat_id}/sets?error={str(e)[:80]}", status_code=303)
    return RedirectResponse(f"/catalogs/{cat_id}/sets?synced=1", status_code=303)


@router.post("/catalogs/{cat_id}/sets/{set_id}/delete")
def delete_set(cat_id: int, set_id: int, db: Session = Depends(get_db)):
    s = db.query(ProductSet).filter(ProductSet.id == set_id).first()
    if s:
        db.delete(s)
        db.commit()
    return RedirectResponse(f"/catalogs/{cat_id}/sets", status_code=303)
