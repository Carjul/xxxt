import json
from fastapi import APIRouter, Depends, Request, Form, HTTPException
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


@router.get("/campaigns")
def list_campaigns(request: Request, db: Session = Depends(get_db)):
    camps = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    return request.app.state.templates.TemplateResponse(request, "campaigns/list.html", {
        "request": request, "campaigns": camps,
    })


@router.get("/campaigns/new")
def new_campaign(request: Request, db: Session = Depends(get_db)):
    s = db.query(AppSettings).first()
    if not s:
        s = AppSettings()
        db.add(s)
        db.commit()
    defaults = get_effective_defaults(db)
    for key, value in defaults.items():
        setattr(s, f"default_{key}", value)
    catalogs = db.query(Catalog).all()
    sets = db.query(ProductSet).all()
    templates = db.query(CampaignTemplate).order_by(CampaignTemplate.created_at.desc()).all()

    accounts, pages, pixels = [], [], []
    try:
        token = get_active_token(db)
        accounts = meta_api.list_ad_accounts(token=token)
        pages = meta_api.list_pages(token=token)
        if s and s.default_ad_account_id:
            try:
                pixels = meta_api.list_pixels(s.default_ad_account_id, token=token)
            except Exception:
                pass
    except Exception:
        pass

    return request.app.state.templates.TemplateResponse(request, "campaigns/wizard.html", {
        "request": request, "settings": s,
        "catalogs": catalogs, "sets": sets, "templates": templates,
        "accounts": accounts, "pages": pages, "pixels": pixels,
        "bid_strategies": BID_STRATEGIES, "ctas": CTAS,
        "objectives": OBJECTIVES, "event_types": EVENT_TYPES,
    })


@router.post("/campaigns")
async def create_campaign(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    cfg = {k: v for k, v in form.items()}

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

    lander = cfg.get("lander", "")
    message = cfg.get("message", "{{product.description}}")
    cta_type = cfg.get("cta_type", "LEARN_MORE")
    url_tags = cfg.get("url_tags", "")
    use_video = cfg.get("use_video", "yes") == "yes"
    multi_advertiser_optout = cfg.get("multi_advertiser_optout", "yes") == "yes"
    trick_enabled = cfg.get("trick_enabled", "no") == "yes"

    save_template = cfg.get("save_as_template", "")

    log_lines = []
    out = {}

    try:
        camp_payload = {
            "name": name,
            "objective": objective,
            "status": "PAUSED",
            "buying_type": "AUCTION",
            "special_ad_categories": json.dumps([]),
            "is_adset_budget_sharing_enabled": cbo,
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

        adset_payload = {
            "name": f"AS-{name}",
            "campaign_id": camp_res["id"],
            "billing_event": "IMPRESSIONS",
            "optimization_goal": "OFFSITE_CONVERSIONS",
            "promoted_object": json.dumps({
                "product_set_id": pset.fb_set_id,
                "pixel_id": pixel_id,
                "custom_event_type": custom_event_type,
            }),
            "targeting": json.dumps(targeting),
            "status": "PAUSED",
        }
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
            "name": f"CR-{name}",
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
            "name": f"AD-{name}",
            "adset_id": adset_res["id"],
            "creative": json.dumps({"creative_id": creative_res["id"]}),
            "status": "PAUSED",
        }
        ad_res = meta_api.create_ad(ad_account_id, ad_payload)
        out["ad_id"] = ad_res["id"]
        log_lines.append(f"ad {ad_res['id']}")

    except Exception as e:
        return request.app.state.templates.TemplateResponse(request, "campaigns/wizard.html", {
            "request": request, "error": str(e),
            "settings": db.query(AppSettings).first(),
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
def delete_campaign(camp_id: int, db: Session = Depends(get_db)):
    c = db.query(Campaign).filter(Campaign.id == camp_id).first()
    if c:
        db.delete(c)
        db.commit()
    return RedirectResponse("/campaigns", status_code=303)
