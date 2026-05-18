"""Cron: truco automático + notificaciones de approval y conversiones."""
import logging
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

from . import meta_api, notifier
from .config import TRICK_RUNNER_INTERVAL
from .database import MongoSession, SessionLocal
from .meta_connections import get_active_token, upsert_env_connection
from .models import Campaign, ProductSet, Catalog, Product, AppSettings

log = logging.getLogger("trick_runner")


def run_trick_check():
    """1. Detecta ads ACTIVE → apaga blancos + notifica approval.
       2. Polea insights → notifica conversiones nuevas."""
    db: MongoSession = SessionLocal()
    try:
        upsert_env_connection(db)
        token = get_active_token(db)
        if not token:
            return
        settings = db.query(AppSettings).first()
        notify_approval = bool(settings and settings.notify_on_approval)
        notify_conv = bool(settings and settings.notify_on_conversion)

        all_camps = db.query(Campaign).filter(Campaign.fb_ad_id.isnot(None)).all()
        log.info(f"[cron] revisando {len(all_camps)} campañas")

        for camp in all_camps:
            try:
                ad = meta_api.get_ad(camp.fb_ad_id, fields="id,effective_status", token=token)
                status = ad.get("effective_status")
                camp.last_status = status

                # 1. Notificar approval (una sola vez por campaña)
                if status == "ACTIVE" and not camp.notified_approval:
                    if notify_approval:
                        notifier.notify_approval(camp.name, camp.fb_ad_id, camp.ad_account_id)
                    camp.notified_approval = True

                # 2. Truco: apagar blancos
                if camp.trick_enabled and not camp.trick_executed and status == "ACTIVE":
                    _shutdown_clean_products(db, camp, token)
                    camp.trick_executed = True
                    camp.trick_executed_at = datetime.utcnow()

                # 3. Polling de conversiones
                if status == "ACTIVE" and camp.fb_campaign_id and notify_conv:
                    _check_conversions(db, camp, token)

                db.commit()
            except Exception as e:
                log.exception(f"[cron] fallo en campaña {camp.id}: {e}")
                db.rollback()
    finally:
        db.close()


def _shutdown_clean_products(db: MongoSession, campaign: Campaign, token: str):
    if not campaign.product_set_id:
        return
    pset = db.query(ProductSet).filter(ProductSet.id == campaign.product_set_id).first()
    if not pset:
        return
    catalog = db.query(Catalog).filter(Catalog.id == pset.catalog_id).first()
    if not catalog:
        return
    retailer_ids = pset.retailer_ids or []
    products = db.query(Product).filter(
        Product.catalog_id == catalog.id,
        Product.retailer_id.in_(retailer_ids),
        Product.tag == "clean",
    ).all()
    for p in products:
        try:
            meta_api.update_product_availability(catalog.fb_catalog_id, p.retailer_id, "out of stock", token=token)
            p.availability = "out of stock"
            log.info(f"[cron] producto {p.retailer_id} → out_of_stock")
        except Exception as e:
            log.exception(f"[cron] fallo apagando {p.retailer_id}: {e}")


def _check_conversions(db: MongoSession, camp: Campaign, token: str):
    """Compara conversiones actuales vs last_conversions. Si subió, notifica."""
    try:
        insights = meta_api.get_campaign_insights(camp.fb_campaign_id, token=token)
    except Exception as e:
        log.exception(f"[cron] insights fail {camp.id}: {e}")
        return
    current = meta_api.parse_purchases(insights)
    spend = float(insights.get("spend", "0") or 0)
    prev = camp.last_conversions or 0
    if current > prev:
        diff = current - prev
        notifier.notify_conversion(camp.name, diff, current, spend)
    camp.last_conversions = current
    camp.last_spend = spend


_scheduler: BackgroundScheduler | None = None


def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(run_trick_check, "interval", seconds=TRICK_RUNNER_INTERVAL,
                       id="trick_check", next_run_time=datetime.now())
    _scheduler.start()
    log.info(f"[cron] scheduler iniciado, cada {TRICK_RUNNER_INTERVAL}s")


def stop_scheduler():
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
