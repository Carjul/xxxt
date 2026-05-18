import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import SESSION_SECRET, PUBLIC_BASE_URL
from .database import Base, MongoSession, SessionLocal, engine, get_db, migrate_db
from .meta_connections import get_active_connection, get_active_token, upsert_env_connection
from .models import Catalog, Product, ProductSet, Campaign, CampaignTemplate
from .routers import setup, catalogs, products, sets, campaigns, templates as tpl_router, trick, feed
from .trick_runner import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_db()
    db = SessionLocal()
    try:
        upsert_env_connection(db)
        if get_active_token(db):
            start_scheduler()
    finally:
        db.close()
    yield
    stop_scheduler()


app = FastAPI(title="FB Catalog Dashboard", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")
app.state.templates = templates

app.include_router(setup.router)
app.include_router(catalogs.router)
app.include_router(products.router)
app.include_router(sets.router)
app.include_router(campaigns.router)
app.include_router(tpl_router.router)
app.include_router(trick.router)
app.include_router(feed.router)


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: MongoSession = Depends(get_db)):
    active_connection = get_active_connection(db)
    stats = {
        "catalogs": db.query(Catalog).count(),
        "products": db.query(Product).count(),
        "sets": db.query(ProductSet).count(),
        "campaigns": db.query(Campaign).count(),
        "templates": db.query(CampaignTemplate).count(),
    }
    pending_trick = db.query(Campaign).filter(
        Campaign.trick_enabled == True, Campaign.trick_executed == False
    ).count()

    return templates.TemplateResponse(request, "home.html", {
        "request": request, "stats": stats,
        "pending_trick": pending_trick,
        "token_set": bool(get_active_token(db)),
        "active_connection": active_connection,
        "public_base": PUBLIC_BASE_URL,
    })


@app.get("/health")
def health():
    return {"status": "ok"}
