"""
Servicio para crear campañas Meta NORMALES (sin truco de catálogo ni idiomas).

Estructura: 1 campaña → 1 adset → N ads.
Cada ad lleva un creativo (imagen o video subido a Meta) + copy + lander.
"""
import json
from typing import List, Dict, Any, Optional

import requests

GRAPH = "https://graph.facebook.com/v21.0"


def _build_targeting(countries, age_min: int, age_max: int, locales: List[int]) -> str:
    if isinstance(countries, str):
        countries = [countries]
    return json.dumps({
        "geo_locations": {"countries": countries},
        "age_min": age_min, "age_max": age_max,
        "locales": locales,
        "targeting_automation": {"advantage_audience": 0},
    })


def _get_page_backed_ig(page_id: str, token: str) -> Optional[str]:
    try:
        pages = requests.get(f"{GRAPH}/me/accounts",
                             params={"fields": "id,access_token", "limit": 100,
                                     "access_token": token}, timeout=30).json()
        page_token = next((p["access_token"] for p in pages.get("data", []) if p["id"] == page_id), None)
        if not page_token:
            return None
        igs = requests.get(f"{GRAPH}/{page_id}/page_backed_instagram_accounts",
                           params={"access_token": page_token}, timeout=30).json()
        for ig in igs.get("data", []):
            return ig["id"]
    except Exception:
        pass
    return None


def create_normal_multi_ad(
    act_id: str, token: str, page_id: str, pixel_id: str,
    name: str, countries, age_min: int, age_max: int,
    locale_id: int,
    daily_budget_cents: int,
    is_cbo: bool,
    ads: List[Dict[str, Any]],
    objective: str = "OUTCOME_SALES",
    optimization_goal: str = "OFFSITE_CONVERSIONS",
    custom_event_type: str = "PURCHASE",
    bid_strategy: str = "LOWEST_COST_WITHOUT_CAP",
    bid_amount_cents: int = 0,
    roas_floor: float = 0.0,
    instagram_id: str = "",
    url_tags: str = "",
    adset_name: str = "",
    locale_ids: Optional[List[int]] = None,
    start_time: str = "",
    end_time: str = "",
) -> Dict[str, Any]:
    """
    Crea 1 campaña + 1 adset + N ads sin truco.
    Cada item de `ads` debe traer:
      {is_video, meta_id, body, title, description, link, cta_type}
    """
    out = {"errors": [], "ads": []}

    # 1. Campaign
    camp_payload = {
        "name": name,
        "objective": objective,
        "status": "PAUSED",
        "buying_type": "AUCTION",
        "special_ad_categories": json.dumps([]),
        "is_adset_budget_sharing_enabled": is_cbo,
        "access_token": token,
    }
    if is_cbo:
        camp_payload["daily_budget"] = daily_budget_cents
        camp_payload["bid_strategy"] = bid_strategy

    r = requests.post(f"{GRAPH}/{act_id}/campaigns", data=camp_payload, timeout=60).json()
    if "error" in r:
        out["errors"].append(f"campaign: {r['error'].get('error_user_msg') or r['error'].get('message')}")
        return out
    out["campaign_id"] = r["id"]

    # 2. IG
    ig_id = instagram_id or _get_page_backed_ig(page_id, token)

    # 3. AdSet — soporta multi-locale (ej: en_US + en_XX + en_GB)
    locales_for_targeting = locale_ids if locale_ids else [locale_id]
    targeting = _build_targeting(countries, age_min, age_max, locales_for_targeting)

    adset_payload = {
        "name": (adset_name.strip() if adset_name and adset_name.strip() else f"AS-{name}"),
        "campaign_id": out["campaign_id"],
        "billing_event": "IMPRESSIONS",
        "optimization_goal": optimization_goal,
        "targeting": targeting,
        "promoted_object": json.dumps({"pixel_id": pixel_id, "custom_event_type": custom_event_type}),
        "status": "PAUSED",
        "access_token": token,
    }
    if start_time:
        adset_payload["start_time"] = start_time
    if end_time:
        adset_payload["end_time"] = end_time
    if not is_cbo:
        adset_payload["daily_budget"] = daily_budget_cents
        adset_payload["bid_strategy"] = bid_strategy
    if bid_strategy in ("COST_CAP", "LOWEST_COST_WITH_BID_CAP") and bid_amount_cents > 0:
        adset_payload["bid_amount"] = bid_amount_cents
    if bid_strategy == "LOWEST_COST_WITH_MIN_ROAS" and roas_floor > 0:
        adset_payload["bid_constraints"] = json.dumps({"roas_average_floor": int(roas_floor * 10000)})

    r = requests.post(f"{GRAPH}/{act_id}/adsets", data=adset_payload, timeout=60).json()
    if "error" in r:
        out["errors"].append(f"adset: {r['error'].get('error_user_msg') or r['error'].get('message')}")
        return out
    out["adset_id"] = r["id"]

    # 4. Por cada ad → creative + ad
    for idx, a in enumerate(ads, start=1):
        link_data = {
            "link": a["link"],
            "message": a["body"],
            "name": a["title"],
            "call_to_action": {"type": a.get("cta_type", "LEARN_MORE"), "value": {"link": a["link"]}},
        }
        if a.get("description"):
            link_data["description"] = a["description"]

        if a["is_video"]:
            link_data["video_id"] = a["meta_id"]
            object_story_spec = {"page_id": page_id, "video_data": link_data}
        else:
            link_data["image_hash"] = a["meta_id"]
            object_story_spec = {"page_id": page_id, "link_data": link_data}

        if ig_id:
            object_story_spec["instagram_user_id"] = ig_id

        custom_ad_name = (a.get("ad_name") or "").strip()
        creative_payload = {
            "name": (f"CR-{custom_ad_name}" if custom_ad_name else f"CR-{name}-{idx}"),
            "object_story_spec": json.dumps(object_story_spec),
            "is_multi_advertiser_ads_opted_in": False,
            "access_token": token,
        }
        if url_tags:
            creative_payload["url_tags"] = url_tags

        r = requests.post(f"{GRAPH}/{act_id}/adcreatives", data=creative_payload, timeout=60).json()
        if "error" in r:
            out["errors"].append(f"ad #{idx} creative: {r['error'].get('error_user_msg') or r['error'].get('message')}")
            continue
        creative_id = r["id"]

        ad_payload = {
            "name": (custom_ad_name if custom_ad_name else f"AD-{name}-{idx}"),
            "adset_id": out["adset_id"],
            "creative": json.dumps({"creative_id": creative_id}),
            "status": "PAUSED",
            "access_token": token,
        }
        r = requests.post(f"{GRAPH}/{act_id}/ads", data=ad_payload, timeout=60).json()
        if "error" in r:
            out["errors"].append(f"ad #{idx}: {r['error'].get('error_user_msg') or r['error'].get('message')}")
            continue
        out["ads"].append({"index": idx, "creative_id": creative_id, "ad_id": r["id"]})

    return out
