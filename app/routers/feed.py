"""Sirve el CSV público que Meta consulta como product feed."""
import csv
import io
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from typing import Any as Session

from ..database import get_db
from ..models import Catalog, Product

router = APIRouter()

COLS = ["id", "title", "description", "availability", "condition", "price",
        "link", "image_link", "brand", "video[0].url"]


@router.get("/feed/{slug}.csv")
def serve_feed(slug: str, db: Session = Depends(get_db)):
    cat = db.query(Catalog).filter(Catalog.feed_slug == slug).first()
    if not cat:
        raise HTTPException(404)
    products = db.query(Product).filter(Product.catalog_id == cat.id).all()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLS)
    for p in products:
        w.writerow([
            p.retailer_id, p.title, p.description, p.availability, p.condition,
            p.price, p.link, p.image_link, p.brand, p.video_url or "",
        ])

    return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8")
