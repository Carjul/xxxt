"""
Dispatcher de ejecución para campañas planificadas.
Llama a los servicios existentes según el tipo. No duplica lógica de creación.
"""
from datetime import datetime
from typing import Dict, Any
from typing import Any as Session

from ..meta_connections import get_active_token
from .planning_models import PlannedCampaign
from .language_models import MediaAsset, CopyBundle, LanguageCarnada


def execute_plan(plan: PlannedCampaign, db: Session) -> Dict[str, Any]:
    """Ejecuta la fila. Devuelve {ok, ids?, error?}. Actualiza el modelo en DB."""
    if not get_active_token(db):
        return _fail(plan, db, "No hay conexion Meta activa")

    plan.status = "executing"
    db.commit()

    try:
        if plan.type == "language":
            result = _exec_language(plan, db)
        elif plan.type == "normal":
            result = _exec_normal(plan, db)
        elif plan.type == "catalog":
            result = _exec_catalog(plan, db)
        else:
            return _fail(plan, db, f"Tipo desconocido: {plan.type}")
    except Exception as e:
        return _fail(plan, db, f"Excepción: {e}")

    if result.get("errors"):
        plan.status = "error"
        plan.error_msg = " · ".join(result["errors"])
        plan.result_ids = {k: v for k, v in result.items() if k != "errors"}
        db.commit()
        return {"ok": False, "result": result}

    plan.status = "done"
    plan.error_msg = ""
    plan.result_ids = result
    plan.executed_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "result": result}


def _fail(plan, db, msg):
    plan.status = "error"
    plan.error_msg = msg
    db.commit()
    return {"ok": False, "error": msg}


def _act(act_id: str) -> str:
    return act_id if act_id.startswith("act_") else f"act_{act_id}"


def _countries_list(s: str):
    return [c.strip().upper() for c in (s or "US").split(",") if c.strip()] or ["US"]


# ─── LANGUAGE ──────────────────────────────────────────────────────────────
def _exec_language(plan, db):
    from .language_trick import create_language_trick_multi_ad
    token = get_active_token(db)

    cfg_ads = (plan.config or {}).get("ads", [])
    if not cfg_ads:
        return {"errors": ["El plan no tiene ads en config"]}

    ads_data = []
    for i, a in enumerate(cfg_ads, start=1):
        real = db.query(MediaAsset).filter(MediaAsset.id == int(a["media_asset_id"])).first()
        defa = db.query(MediaAsset).filter(MediaAsset.id == int(a["default_media_id"])).first()
        bundle = db.query(CopyBundle).filter(CopyBundle.id == int(a["copy_bundle_id"])).first()
        if not (real and defa and bundle):
            return {"errors": [f"Ad #{i}: media o bundle no encontrado"]}
        for asset in (real, defa):
            if not asset.uploaded_to_meta or not asset.meta_id:
                return {"errors": [f"El creativo '{asset.name}' no está en Meta (sube en /media)"]}

        carn_ids = bundle.carnada_ids or []
        carn_objs = db.query(LanguageCarnada).filter(LanguageCarnada.id.in_(carn_ids)).all()
        by_id = {c.id: c for c in carn_objs}
        ordered = [by_id[i] for i in carn_ids if i in by_id]
        if not ordered:
            return {"errors": [f"Ad #{i}: bundle '{bundle.name}' no tiene carnadas"]}
        carnadas = [{
            "locale_id": c.locale_id, "locale_code": c.locale_code,
            "body": c.body, "title": c.title, "desc": c.description, "url": c.url,
        } for c in ordered]

        ads_data.append({
            "target_locale_id": plan.locale_id,
            "target_locale_code": "",  # no se usa, el AFS lo deriva
            "real_media_id": real.meta_id,
            "default_media_id": defa.meta_id,
            "is_video": real.type == "video",
            "real_body": bundle.real_body,
            "real_title": bundle.real_title,
            "real_desc": bundle.real_desc or "",
            "real_url": bundle.real_url,
            "url_tags": plan.url_tags,
            "carnadas": carnadas,
            "cta_type": a.get("cta_type", "LEARN_MORE"),
        })

    return create_language_trick_multi_ad(
        act_id=_act(plan.ad_account_id), token=token,
        page_id=plan.page_id, pixel_id=plan.pixel_id,
        name=plan.name,
        countries=_countries_list(plan.countries),
        age_min=plan.age_min, age_max=plan.age_max,
        adset_locale_id=plan.locale_id,
        daily_budget_cents=int(plan.daily_budget_usd * 100),
        is_cbo=(plan.cbo_or_abo == "CBO"),
        ads=ads_data,
        objective=plan.objective,
        optimization_goal=plan.optimization_goal,
        custom_event_type=plan.custom_event_type,
        bid_strategy=plan.bid_strategy,
        bid_amount_cents=int(plan.bid_amount_usd * 100),
        roas_floor=plan.roas_floor,
        instagram_id=plan.instagram_id or "",
    )


# ─── NORMAL ────────────────────────────────────────────────────────────────
def _exec_normal(plan, db):
    from .normal_campaign import create_normal_multi_ad
    token = get_active_token(db)

    cfg_ads = (plan.config or {}).get("ads", [])
    if not cfg_ads:
        return {"errors": ["El plan no tiene ads en config"]}

    ads_data = []
    for i, a in enumerate(cfg_ads, start=1):
        asset = db.query(MediaAsset).filter(MediaAsset.id == int(a["media_asset_id"])).first()
        if not asset:
            return {"errors": [f"Ad #{i}: creativo no encontrado"]}
        if not asset.uploaded_to_meta or not asset.meta_id:
            return {"errors": [f"El creativo '{asset.name}' no está en Meta"]}
        ads_data.append({
            "is_video": asset.type == "video",
            "meta_id": asset.meta_id,
            "body": a.get("body", ""),
            "title": a.get("title", ""),
            "description": a.get("description", ""),
            "link": a.get("link", ""),
            "cta_type": a.get("cta_type", "LEARN_MORE"),
        })

    return create_normal_multi_ad(
        act_id=_act(plan.ad_account_id), token=token,
        page_id=plan.page_id, pixel_id=plan.pixel_id,
        name=plan.name,
        countries=_countries_list(plan.countries),
        age_min=plan.age_min, age_max=plan.age_max,
        locale_id=plan.locale_id,
        daily_budget_cents=int(plan.daily_budget_usd * 100),
        is_cbo=(plan.cbo_or_abo == "CBO"),
        ads=ads_data,
        objective=plan.objective,
        optimization_goal=plan.optimization_goal,
        custom_event_type=plan.custom_event_type,
        bid_strategy=plan.bid_strategy,
        bid_amount_cents=int(plan.bid_amount_usd * 100),
        roas_floor=plan.roas_floor,
        instagram_id=plan.instagram_id or "",
        url_tags=plan.url_tags,
    )


# ─── CATALOG ───────────────────────────────────────────────────────────────
def _exec_catalog(plan, db):
    """
    El wizard de catálogo es complejo y vive en campaigns.py.
    Por ahora marcamos el plan como 'pending' con un mensaje pidiendo abrir
    el wizard manualmente. (En siguiente iteración expongo el helper para
    crear sin pasar por HTTP).
    """
    return {"errors": ["Catalog: usa el botón 'Abrir en wizard' (cargará la config) y dale Crear desde ahí. Soporte directo pendiente."]}
