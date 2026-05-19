from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from typing import Any as Session

from ..database import get_db
from ..models import Catalog, Product

router = APIRouter()


@router.get("/catalogs/{cat_id}/products")
def list_products(cat_id: int, request: Request, db: Session = Depends(get_db)):
    cat = db.query(Catalog).filter(Catalog.id == cat_id).first()
    if not cat:
        raise HTTPException(404)
    products = db.query(Product).filter(Product.catalog_id == cat_id).order_by(Product.id).all()
    return request.app.state.templates.TemplateResponse(request, "products/list.html", {
        "request": request, "catalog": cat, "products": products,
    })


@router.post("/catalogs/{cat_id}/products/bulk")
async def bulk_save(cat_id: int, request: Request, db: Session = Depends(get_db)):
    cat = db.query(Catalog).filter(Catalog.id == cat_id).first()
    if not cat:
        raise HTTPException(404)
    form = await request.form()
    count = int(form.get("row_count", "0"))
    for i in range(count):
        pid = form.get(f"id_{i}", "").strip()
        retailer_id = form.get(f"retailer_id_{i}", "").strip()
        title = form.get(f"title_{i}", "").strip()
        link = form.get(f"link_{i}", "").strip()
        image_link = form.get(f"image_link_{i}", "").strip()
        if not retailer_id or not title or not link or not image_link:
            continue
        data = {
            "catalog_id": cat_id,
            "retailer_id": retailer_id,
            "title": title,
            "description": form.get(f"description_{i}", ""),
            "availability": form.get(f"availability_{i}", "in stock"),
            "condition": "new",
            "price": form.get(f"price_{i}", "10.00 USD"),
            "link": link,
            "image_link": image_link,
            "brand": form.get(f"brand_{i}", "Brand"),
            "video_url": form.get(f"video_url_{i}", "") or None,
            "video_label": form.get(f"video_label_{i}", "") or None,
            "tag": form.get(f"tag_{i}", "dirty"),
        }
        if pid:
            p = db.query(Product).filter(Product.id == int(pid)).first()
            if p:
                for k, v in data.items():
                    if k != "catalog_id":
                        setattr(p, k, v)
        else:
            db.add(Product(**data))
    db.commit()
    return RedirectResponse(f"/catalogs/{cat_id}/products?saved=1", status_code=303)


@router.post("/catalogs/{cat_id}/products/{prod_id}/delete")
def delete_product(cat_id: int, prod_id: int, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == prod_id).first()
    if p:
        db.delete(p)
        db.commit()
    return RedirectResponse(f"/catalogs/{cat_id}/products", status_code=303)
