import json
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import RedirectResponse
from typing import Any as Session

from .. import meta_api
from ..database import get_db
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
OBJECTIVES = ["OUTCOME_SALES", "OUTCOME_LEADS", "OUTCOME_TRAFFIC", "OUTCOME_AWARENESS", "OUTCOME_ENGAGEMENT"]
EVENT_TYPES = ["PURCHASE", "INITIATE_CHECKOUT", "ADD_TO_CART", "LEAD", "COMPLETE_REGISTRATION", "VIEW_CONTENT"]
OPTIMIZATION_GOALS = [
    ("OFFSITE_CONVERSIONS", "Conversiones (pixel)"),
    ("VALUE", "Valor / ROAS"),
    ("LANDING_PAGE_VIEWS", "Vistas de landing page"),
    ("LINK_CLICKS", "Clics en enlace"),
    ("IMPRESSIONS", "Impresiones"),
    ("REACH", "Alcance"),
]


def _get_settings_with_defaults(db: Session) -> AppSettings:
    settings = db.query(AppSettings).first()
    if not settings:
        settings = AppSettings()
        db.add(settings)
        db.commit()
    defaults = get_effective_defaults(db)
    for key, value in defaults.items():
        setattr(settings, f"default_{key}", value)
    return settings


def _build_campaign_context(request: Request, db: Session, *, form: dict | None = None, error: str | None = None):
    settings = _get_settings_with_defaults(db)
    catalogs = db.query(Catalog).all()
    sets = db.query(ProductSet).all()
    templates = db.query(CampaignTemplate).order_by(CampaignTemplate.created_at.desc()).all()

    accounts, pages, pixels = [], [], []
    try:
        token = get_active_token(db)
        if token:
            accounts = meta_api.list_ad_accounts(token=token)
            pages = meta_api.list_pages(token=token)
            pixel_account_id = (form or {}).get("ad_account_id") or settings.default_ad_account_id
            if pixel_account_id:
                try:
                    pixels = meta_api.list_pixels(pixel_account_id, token=token)
                except Exception:
                    pass
    except Exception:
        pass

    from ..services.meta_locales import META_LOCALES
    return {
        "request": request, "settings": settings,
        "catalogs": catalogs, "sets": sets, "templates": templates,
        "accounts": accounts, "pages": pages, "pixels": pixels,
        "bid_strategies": BID_STRATEGIES, "ctas": CTAS,
        "objectives": OBJECTIVES, "event_types": EVENT_TYPES,
        "optimization_goals": OPTIMIZATION_GOALS,
        "locales": META_LOCALES,
        "form": form,
        "error": error,
    }


def _campaign_error(request: Request, db: Session, message: str, form: dict | None = None):
    return request.app.state.templates.TemplateResponse(
        request,
        "campaigns/wizard.html",
        _build_campaign_context(request, db, form=form, error=message),
        status_code=400,
    )


@router.get("/campaigns")
def list_campaigns(request: Request, db: Session = Depends(get_db)):
    camps = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return request.app.state.templates.TemplateResponse(request, "campaigns/list.html", {
        "request": request, "campaigns": camps,
    })


@router.get("/campaigns/new")
def new_campaign(request: Request, db: Session = Depends(get_db)):
    return request.app.state.templates.TemplateResponse(
        request,
        "campaigns/wizard.html",
        _build_campaign_context(request, db),
    )


@router.post("/campaigns")
async def create_campaign(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cfg = {k: v for k, v in form.items()}

    name = cfg.get("name", "").strip()
    ad_account_id = cfg.get("ad_account_id", "").replace("act_", "")
    if not name or not ad_account_id:
        return _campaign_error(request, db, "Nombre y cuenta publicitaria son obligatorios", cfg)

    objective = cfg.get("objective", "OUTCOME_SALES")
    budget_type = cfg.get("budget_type", "daily")
    try:
        budget_amount = float(cfg.get("budget_amount", "10"))
    except ValueError:
        return _campaign_error(request, db, "Presupuesto inválido", cfg)
    cbo = cfg.get("cbo_or_abo", "CBO") == "CBO"
    bid_strategy = cfg.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP")
    bid_amount = cfg.get("bid_amount", "")
    roas_floor = cfg.get("roas_floor", "")
    spend_cap = cfg.get("spend_cap", "")
    age_min = int(cfg.get("age_min", "40"))
    age_max = int(cfg.get("age_max", "65"))
    countries = [c.strip() for c in cfg.get("countries", "US").split(",") if c.strip()]
    page_id = (cfg.get("page_id") or "").strip()
    pixel_id = (cfg.get("pixel_id") or "").strip()
    instagram_id = cfg.get("instagram_id", "") or None
    optimization_goal = cfg.get("optimization_goal", "OFFSITE_CONVERSIONS")
    custom_event_type = cfg.get("custom_event_type", "PURCHASE")
    if not page_id:
        return _campaign_error(request, db, "Página de Facebook es obligatoria para crear el anuncio", cfg)
    try:
        set_db_id = int(cfg.get("product_set_id"))
    except (TypeError, ValueError):
        return _campaign_error(request, db, "Product set es obligatorio", cfg)
    pset = db.query(ProductSet).filter(ProductSet.id == set_db_id).first()
    if not pset or not pset.fb_set_id:
        return _campaign_error(request, db, "Product set debe estar sincronizado con Meta antes", cfg)
    catalog = db.query(Catalog).filter(Catalog.id == pset.catalog_id).first()
    settings = _get_settings_with_defaults(db)
    if not settings.default_business_id:
        return _campaign_error(request, db, "Configura un Business Manager antes de crear campañas con catálogo", cfg)
    if catalog and catalog.business_id and catalog.business_id != settings.default_business_id:
        return _campaign_error(request, db, "El catálogo seleccionado pertenece a otro BM distinto al configurado", cfg)

    lander = cfg.get("lander", "").strip()
    if not lander:
        return _campaign_error(request, db, "Lander URL es obligatorio", cfg)
    message = cfg.get("message", "{{product.description}}")
    cta_type = cfg.get("cta_type", "LEARN_MORE")
    url_tags = cfg.get("url_tags", "")
    use_video = cfg.get("use_video", "yes") == "yes"
    multi_advertiser_optout = cfg.get("multi_advertiser_optout", "yes") == "yes"
    trick_enabled = cfg.get("trick_enabled", "no") == "yes"

    save_template = cfg.get("save_as_template", "")

    # Nuevos campos: nombres custom + scheduling + multi-locale
    adset_name_custom = cfg.get("adset_name", "").strip()
    ad_name_custom = cfg.get("ad_name", "").strip()
    start_time = cfg.get("start_time", "").strip()
    end_time = cfg.get("end_time", "").strip()
    if budget_type == "lifetime" and not end_time:
        return _campaign_error(request, db, "El presupuesto total/lifetime necesita fecha de fin", cfg)
    if bid_strategy == "LOWEST_COST_WITH_MIN_ROAS":
        optimization_goal = "VALUE"
    if optimization_goal in ("OFFSITE_CONVERSIONS", "VALUE") and not pixel_id:
        return _campaign_error(request, db, "Pixel es obligatorio para optimizar por conversiones o valor/ROAS", cfg)
    # locale_ids puede venir como múltiples inputs (chips) o coma-separados
    try:
        locale_ids_multi = form.getlist("locale_ids")
    except Exception:
        locale_ids_multi = []
    locale_ids = []
    for raw in locale_ids_multi:
        for part in str(raw).split(","):
            part = part.strip()
            if part.isdigit():
                locale_ids.append(int(part))

    log_lines = []
    out = {}

    try:
        camp_payload = {
            "name": name,
            "objective": objective,
            "status": "PAUSED",
            "buying_type": "AUCTION",
            "special_ad_categories": json.dumps([]),
            "is_adset_budget_sharing_enabled": False,
        }
        if cbo:
            # En CBO: budget + bid_strategy van en campaña
            camp_payload["bid_strategy"] = bid_strategy
            if budget_type == "daily":
                camp_payload["daily_budget"] = int(budget_amount * 100)
            else:
                camp_payload["lifetime_budget"] = int(budget_amount * 100)
        if spend_cap:
            try:
                camp_payload["spend_cap"] = int(float(spend_cap) * 100)
            except ValueError:
                pass

        camp_res = meta_api.create_campaign(ad_account_id, camp_payload)
        out["campaign_id"] = camp_res["id"]
        log_lines.append(f"campaign {camp_res['id']}")

        targeting = {
            "age_min": age_min, "age_max": age_max,
            "geo_locations": {"countries": countries},
            **({"locales": locale_ids} if locale_ids else {}),
            "publisher_platforms": ["facebook", "instagram", "audience_network", "messenger"],
            "facebook_positions": ["feed", "biz_disco_feed", "facebook_reels",
                                   "facebook_reels_overlay", "profile_feed", "right_hand_column",
                                   "notification", "instream_video", "marketplace", "story", "search"],
            "instagram_positions": ["stream", "ig_search", "story", "explore", "reels",
                                    "explore_home", "profile_feed"],
            "device_platforms": ["mobile", "desktop"],
            "messenger_positions": ["story"],
            "audience_network_positions": ["classic", "rewarded_video"],
            "targeting_automation": {"advantage_audience": 0},
        }

        promoted_object = {"product_set_id": pset.fb_set_id}
        if optimization_goal in ("OFFSITE_CONVERSIONS", "VALUE"):
            promoted_object.update({
                "pixel_id": pixel_id,
                "custom_event_type": custom_event_type,
            })

        adset_payload = {
            "name": (adset_name_custom if adset_name_custom else f"AS-{name}"),
            "campaign_id": camp_res["id"],
            "billing_event": "IMPRESSIONS",
            "optimization_goal": optimization_goal,
            "promoted_object": json.dumps(promoted_object),
            "targeting": json.dumps(targeting),
            "status": "PAUSED",
        }
        if start_time:
            adset_payload["start_time"] = start_time
        if end_time:
            adset_payload["end_time"] = end_time
        if not cbo:
            # En ABO: budget + bid_strategy van en adset
            adset_payload["bid_strategy"] = bid_strategy
            if budget_type == "daily":
                adset_payload["daily_budget"] = int(budget_amount * 100)
            else:
                adset_payload["lifetime_budget"] = int(budget_amount * 100)

        # bid_amount y roas_floor SIEMPRE van en el adset (también en CBO)
        if bid_strategy in ("COST_CAP", "LOWEST_COST_WITH_BID_CAP") and bid_amount:
            try:
                adset_payload["bid_amount"] = int(float(bid_amount) * 100)
            except ValueError:
                pass
        elif bid_strategy == "LOWEST_COST_WITH_MIN_ROAS" and roas_floor:
            try:
                adset_payload["bid_constraints"] = json.dumps({"roas_average_floor": int(float(roas_floor) * 10000)})
            except ValueError:
                pass

        adset_res = meta_api.create_adset(ad_account_id, adset_payload)
        out["adset_id"] = adset_res["id"]
        log_lines.append(f"adset {adset_res['id']}")

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
        if use_video:
            td["format_option"] = "single_video"
        story_spec = {"page_id": page_id, "template_data": td}
        if instagram_id:
            story_spec["instagram_user_id"] = instagram_id

        creative_payload = {
            "name": (f"CR-{ad_name_custom}" if ad_name_custom else f"CR-{name}"),
            "object_story_spec": json.dumps(story_spec),
            "product_set_id": pset.fb_set_id,
        }
        if url_tags:
            creative_payload["url_tags"] = url_tags
        if multi_advertiser_optout:
            creative_payload["is_multi_advertiser_ads_opted_in"] = False

        creative_res = meta_api.create_adcreative(ad_account_id, creative_payload)
        out["creative_id"] = creative_res["id"]
        log_lines.append(f"creative {creative_res['id']}")

        ad_payload = {
            "name": (ad_name_custom if ad_name_custom else f"AD-{name}"),
            "adset_id": adset_res["id"],
            "creative": json.dumps({"creative_id": creative_res["id"]}),
            "status": "PAUSED",
        }
        ad_res = meta_api.create_ad(ad_account_id, ad_payload)
        out["ad_id"] = ad_res["id"]
        log_lines.append(f"ad {ad_res['id']}")

    except Exception as e:
        return _campaign_error(request, db, str(e), cfg)

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
def delete_campaign(camp_id: int, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == camp_id).first()
    if c:
        db.delete(c)
        db.commit()
    return RedirectResponse("/campaigns", status_code=303)
