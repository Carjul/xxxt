import json
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import RedirectResponse

from .. import meta_api
from ..meta_api import MetaApiError
from ..database import MongoSession, get_db
from ..meta_connections import get_active_token, get_effective_defaults
from ..models import Campaign, Catalog, ProductSet, CampaignTemplate, AppSettings

router = APIRouter()


BID_STRATEGIES = [
    ("LOWEST_COST_WITHOUT_CAP", "Volumen más alto"),
    ("COST_CAP", "Objetivo de costo por resultado"),
    ("LOWEST_COST_WITH_MIN_ROAS", "Objetivo de ROAS"),
    ("LOWEST_COST_WITH_BID_CAP", "Límite de puja"),
]
CTAS = ["LEARN_MORE", "SHOP_NOW", "SIGN_UP", "SUBSCRIBE", "GET_OFFER", "APPLY_NOW", "DOWNLOAD"]
OBJECTIVES = ["OUTCOME_SALES"]
EVENT_TYPES = ["PURCHASE", "INITIATED_CHECKOUT", "ADD_TO_CART", "LEAD", "COMPLETE_REGISTRATION", "CONTENT_VIEW"]


@router.get("/campaigns")
def list_campaigns(request: Request, db: MongoSession = Depends(get_db)):
    camps = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return request.app.state.templates.TemplateResponse(request, "campaigns/list.html", {
        "request": request, "campaigns": camps,
    })


@router.get("/campaigns/new")
def new_campaign(request: Request, db: MongoSession = Depends(get_db)):
    s = db.query(AppSettings).first()
    defaults = get_effective_defaults(db)
    catalogs = db.query(Catalog).all()
    sets = db.query(ProductSet).all()
    templates = db.query(CampaignTemplate).order_by(CampaignTemplate.created_at.desc()).all()

    accounts, pages, pixels = [], [], []
    token = get_active_token(db)
    try:
        if token:
            accounts = meta_api.list_ad_accounts(token=token)
            pages = meta_api.list_pages(token=token)
        if defaults["ad_account_id"]:
            try:
                pixels = meta_api.list_pixels(defaults["ad_account_id"], token=token)
            except Exception:
                pass
    except Exception:
        pass

    return request.app.state.templates.TemplateResponse(request, "campaigns/wizard.html", {
        "request": request, "settings": s,
        "defaults": defaults,
        "catalogs": catalogs, "sets": sets, "templates": templates,
        "accounts": accounts, "pages": pages, "pixels": pixels,
        "bid_strategies": BID_STRATEGIES, "ctas": CTAS,
        "objectives": OBJECTIVES, "event_types": EVENT_TYPES,
    })


@router.post("/campaigns")
async def create_campaign(request: Request, db: MongoSession = Depends(get_db)):
    form = await request.form()
    cfg = {k: v for k, v in form.items()}
    token = get_active_token(db)
    defaults = get_effective_defaults(db)

    if not token:
        raise HTTPException(400, "No hay una conexion Meta activa")

    name = cfg.get("name", "").strip()
    ad_account_id = cfg.get("ad_account_id", "").replace("act_", "")
    if not name or not ad_account_id:
        raise HTTPException(400, "name y ad_account_id son obligatorios")

    objective = cfg.get("objective", "OUTCOME_SALES")
    budget_type = cfg.get("budget_type", "daily")
    budget_amount = float(cfg.get("budget_amount", "10"))
    cbo = cfg.get("cbo_or_abo", "CBO") == "CBO"
    bid_strategy = cfg.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP")
    bid_amount = cfg.get("bid_amount", "")
    roas_floor = cfg.get("roas_floor", "")
    spend_cap = cfg.get("spend_cap", "")
    age_min = int(cfg.get("age_min", "40"))
    age_max = int(cfg.get("age_max", "65"))
    countries = [c.strip() for c in cfg.get("countries", "US").split(",") if c.strip()]
    page_id = cfg.get("page_id")
    pixel_id = cfg.get("pixel_id")
    instagram_id = cfg.get("instagram_id", "") or None
    custom_event_type = cfg.get("custom_event_type", "PURCHASE")
    set_db_id = int(cfg.get("product_set_id"))
    pset = db.query(ProductSet).filter(ProductSet.id == set_db_id).first()
    if not pset or not pset.fb_set_id:
        raise HTTPException(400, "Product set debe estar sincronizado con Meta antes")
    catalog = db.query(Catalog).filter(Catalog.id == pset.catalog_id).first()
    if not catalog or not catalog.fb_catalog_id or catalog.fb_catalog_id.startswith("local-"):
        raise HTTPException(400, "El catalogo del product set debe estar sincronizado con Meta antes")

    if objective != "OUTCOME_SALES":
        raise HTTPException(400, "Por ahora las campanas de catalogo solo soportan OUTCOME_SALES")
    if budget_type != "daily":
        raise HTTPException(400, "Por ahora solo esta soportado presupuesto diario para evitar errores de Meta")
    if not page_id:
        raise HTTPException(400, "Selecciona una pagina de Facebook")
    if not pixel_id:
        raise HTTPException(400, "Selecciona un pixel")
    if not cfg.get("lander", "").strip():
        raise HTTPException(400, "Lander URL es obligatoria")
    if bid_strategy in {"COST_CAP", "LOWEST_COST_WITH_BID_CAP"} and not str(bid_amount).strip():
        raise HTTPException(400, "La estrategia de puja seleccionada requiere Bid amount")
    if bid_strategy == "LOWEST_COST_WITH_MIN_ROAS" and not str(roas_floor).strip():
        raise HTTPException(400, "La estrategia de puja ROAS requiere ROAS floor")

    lander = cfg.get("lander", "")
    message = cfg.get("message", "{{product.description}}")
    cta_type = cfg.get("cta_type", "LEARN_MORE")
    url_tags = cfg.get("url_tags", "")
    use_video = cfg.get("use_video", "yes") == "yes"
    multi_advertiser_optout = cfg.get("multi_advertiser_optout", "yes") == "yes"
    trick_enabled = cfg.get("trick_enabled", "no") == "yes"

    save_template = cfg.get("save_as_template", "")

    out = {}

    try:
        effective_instagram_id = instagram_id
        if not effective_instagram_id:
            try:
                for page in meta_api.list_pages(token=token):
                    if str(page.get("id")) == str(page_id):
                        ig_account = page.get("instagram_business_account") or {}
                        effective_instagram_id = ig_account.get("id") or None
                        break
            except Exception:
                pass

        camp_payload = {
            "name": name,
            "objective": objective,
            "status": "PAUSED",
            "special_ad_categories": json.dumps([]),
            "is_adset_budget_sharing_enabled": False,
        }
        if cbo:
            camp_payload["daily_budget"] = int(budget_amount * 100)
        if spend_cap:
            try:
                camp_payload["spend_cap"] = int(float(spend_cap) * 100)
            except ValueError:
                pass

        camp_res = meta_api.create_campaign(ad_account_id, camp_payload, token=token)
        out["campaign_id"] = camp_res["id"]

        targeting = {
            "age_min": age_min,
            "age_max": age_max,
            "geo_locations": {"countries": countries},
            "targeting_automation": {"advantage_audience": 0},
        }
        if not effective_instagram_id:
            targeting["publisher_platforms"] = ["facebook"]

        adset_payload = {
            "name": f"AS-{name}",
            "campaign_id": camp_res["id"],
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "VALUE" if bid_strategy == "LOWEST_COST_WITH_MIN_ROAS" else "OFFSITE_CONVERSIONS",
            "promoted_object": json.dumps({
                "product_set_id": pset.fb_set_id,
                "pixel_id": pixel_id,
                "custom_event_type": custom_event_type,
            }),
            "targeting": json.dumps(targeting),
            "status": "PAUSED",
        }
        if bid_strategy != "LOWEST_COST_WITHOUT_CAP":
            adset_payload["bid_strategy"] = bid_strategy
        if not cbo:
            adset_payload["daily_budget"] = int(budget_amount * 100)

        if bid_strategy == "COST_CAP" and bid_amount:
            adset_payload["bid_amount"] = int(float(bid_amount) * 100)
        elif bid_strategy == "LOWEST_COST_WITH_BID_CAP" and bid_amount:
            adset_payload["bid_amount"] = int(float(bid_amount) * 100)
        elif bid_strategy == "LOWEST_COST_WITH_MIN_ROAS" and roas_floor:
            try:
                adset_payload["bid_constraints"] = json.dumps({"roas_average_floor": int(float(roas_floor) * 10000)})
            except ValueError:
                pass

        adset_res = meta_api.create_adset(ad_account_id, adset_payload, token=token)
        out["adset_id"] = adset_res["id"]

        headline = cfg.get("headline", "").strip() or "{{product.name}}"
        link_description = cfg.get("link_description", "").strip()
        td = {
            "link": lander,
            "message": message,
            "name": headline,
            "call_to_action": {"type": cta_type, "value": {"link": lander}},
        }
        if link_description:
            td["description"] = link_description
        story_spec = {"page_id": page_id, "template_data": td}

        creative_payload = {
            "name": f"CR-{name}",
            "object_story_spec": json.dumps(story_spec),
            "product_set_id": pset.fb_set_id,
        }
        if effective_instagram_id:
            creative_payload["instagram_user_id"] = effective_instagram_id
        if url_tags:
            creative_payload["url_tags"] = url_tags

        creative_res = meta_api.create_adcreative(ad_account_id, creative_payload, token=token)
        out["creative_id"] = creative_res["id"]

        ad_payload = {
            "name": f"AD-{name}",
            "adset_id": adset_res["id"],
            "creative": json.dumps({"creative_id": creative_res["id"]}),
            "status": "PAUSED",
        }
        ad_res = meta_api.create_ad(ad_account_id, ad_payload, token=token)
        out["ad_id"] = ad_res["id"]

    except MetaApiError as e:
        step = "campaign"
        if out.get("campaign_id") and not out.get("adset_id"):
            step = "adset"
        elif out.get("adset_id") and not out.get("creative_id"):
            step = "creative"
        elif out.get("creative_id"):
            step = "ad"
        message = e.payload.get("error", {}).get("message", str(e))
        subcode = e.payload.get("error", {}).get("error_subcode")
        user_title = e.payload.get("error", {}).get("error_user_title")
        user_msg = e.payload.get("error", {}).get("error_user_msg")
        detail_parts = [f"Paso: {step}", f"Meta: {message}"]
        if user_title:
            detail_parts.append(user_title)
        if user_msg:
            detail_parts.append(user_msg)
        if subcode:
            detail_parts.append(f"subcode {subcode}")
        error_message = " | ".join(detail_parts)

    except Exception as e:
        error_message = f"Error creando campana en Meta: {e}"

    else:
        error_message = None

    if error_message:
        return request.app.state.templates.TemplateResponse(request, "campaigns/wizard.html", {
            "request": request, "error": error_message,
            "settings": db.query(AppSettings).first(),
            "defaults": defaults,
            "catalogs": db.query(Catalog).all(),
            "sets": db.query(ProductSet).all(),
            "templates": db.query(CampaignTemplate).all(),
            "accounts": [], "pages": [], "pixels": [],
            "bid_strategies": BID_STRATEGIES, "ctas": CTAS,
            "objectives": OBJECTIVES, "event_types": EVENT_TYPES,
            "form": cfg,
        }, status_code=400)

    db_camp = Campaign(
        fb_campaign_id=out.get("campaign_id"),
        fb_adset_id=out.get("adset_id"),
        fb_creative_id=out.get("creative_id"),
        fb_ad_id=out.get("ad_id"),
        name=name,
        ad_account_id=ad_account_id,
        catalog_id=catalog.id if catalog else None,
        product_set_id=pset.id,
        config=cfg,
        trick_enabled=trick_enabled,
    )
    db.add(db_camp)

    if save_template:
        tpl = CampaignTemplate(name=save_template, config=cfg)
        db.add(tpl)

    db.commit()
    return RedirectResponse(f"/campaigns?created={db_camp.id}", status_code=303)


@router.post("/campaigns/{camp_id}/delete")
def delete_campaign(camp_id: int, db: MongoSession = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == camp_id).first()
    if c:
        db.delete(c)
        db.commit()
    return RedirectResponse("/campaigns", status_code=303)
