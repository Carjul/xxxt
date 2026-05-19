"""
Language Trick service — Truco de optimización por idioma.

Crea campañas Meta donde el creativo real (inglés US) se sirve a US,
mientras un creativo "default" en francés actúa de carnada para el reviewer.

Reusable desde:
- Dashboard wizard (POST /campaigns con campaign_type='language')
- API directa
- Cron jobs

Locales de referencia:
  6  = English (US)
  9  = French
  17 = Russian
  11 = Japanese
  28 = Arabic
"""
import json
import os
import time
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse

import requests

GRAPH = "https://graph.facebook.com/v21.0"


def a_default_locale_code_for(locale_id: int) -> str:
    from .meta_locales import locale_by_id
    info = locale_by_id(locale_id)
    return info["code"] if info else "en_XX"

# Default copy multi-idioma para los "carnada" del asset feed
DEFAULT_LANG_COPY = {
    "fr": {"body": "Découvrez nos produits", "title": "Voir plus", "desc": "Apprenez plus", "url": "https://example.com/fr"},
    "ru": {"body": "Узнайте больше", "title": "Подробнее", "desc": "Откройте для себя", "url": "https://example.com/ru"},
    "ja": {"body": "詳しくはこちら", "title": "もっと見る", "desc": "詳細を確認", "url": "https://example.com/ja"},
    "ar": {"body": "اكتشف المزيد", "title": "تعرف على المزيد", "desc": "اعرف المزيد", "url": "https://example.com/ar"},
}


def upload_image(act_id: str, token: str, path: str, max_retries: int = 3) -> Optional[str]:
    """Sube imagen a Meta y devuelve el hash."""
    url = f"{GRAPH}/{act_id}/adimages"
    for attempt in range(max_retries):
        try:
            with open(path, "rb") as f:
                r = requests.post(url, data={"access_token": token},
                                  files={"filename1": f}, timeout=300)
            data = r.json()
            for k, v in data.get("images", {}).items():
                return v.get("hash")
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(10)
    return None


def upload_video(act_id: str, token: str, path: str, title: str = "video",
                 max_retries: int = 3) -> Optional[str]:
    """Sube video a Meta. Para archivos >50MB usa resumable upload."""
    file_size = os.path.getsize(path)
    url = f"{GRAPH}/{act_id}/advideos"

    # Para archivos pequeños: upload directo
    if file_size < 50 * 1024 * 1024:
        for attempt in range(max_retries):
            try:
                with open(path, "rb") as f:
                    r = requests.post(url, data={"access_token": token, "title": title},
                                      files={"source": f}, timeout=600)
                data = r.json()
                if data.get("id"):
                    return data["id"]
            except Exception:
                if attempt < max_retries - 1:
                    time.sleep(30)
        return None

    # Para archivos grandes: resumable upload (chunks 10MB)
    return _resumable_video_upload(act_id, token, path, title, file_size)


def _resumable_video_upload(act_id: str, token: str, path: str, title: str,
                            file_size: int) -> Optional[str]:
    url = f"{GRAPH}/{act_id}/advideos"
    try:
        # Start
        r = requests.post(url, data={"upload_phase": "start", "file_size": str(file_size),
                                     "access_token": token}, timeout=60).json()
        upload_session_id = r.get("upload_session_id")
        video_id = r.get("video_id")
        if not upload_session_id:
            return None

        chunk_size = 10 * 1024 * 1024
        start = int(r.get("start_offset", 0))
        end = int(r.get("end_offset", chunk_size))

        with open(path, "rb") as f:
            while start < file_size:
                f.seek(start)
                chunk = f.read(end - start)
                r = requests.post(url, data={
                    "upload_phase": "transfer",
                    "upload_session_id": upload_session_id,
                    "start_offset": str(start),
                    "access_token": token,
                }, files={"video_file_chunk": ("chunk", chunk)}, timeout=120).json()
                if "error" in r:
                    return None
                start = int(r.get("start_offset", file_size))
                end = int(r.get("end_offset", file_size))

        # Finish
        r = requests.post(url, data={"upload_phase": "finish",
                                     "upload_session_id": upload_session_id,
                                     "title": title, "access_token": token}, timeout=60).json()
        if r.get("success"):
            return video_id
    except Exception:
        pass
    return None


def build_asset_feed_spec(real_media_id: str, default_media_id: str, is_video: bool,
                          real_body: str, real_title: str, real_desc: str,
                          real_url: str,
                          target_locale_id: int = 6,
                          target_locale_code: str = "en_XX",
                          target_locale_ids: Optional[List[int]] = None,
                          carnadas: Optional[List[Dict[str, Any]]] = None,
                          cta_type: str = "LEARN_MORE") -> str:
    """
    Construye el asset_feed_spec con carnadas DINÁMICAS.

    carnadas: lista de dicts, cada uno con:
        {locale_id, locale_code, body, title, desc, url}
    La primera carnada se marca como `is_default=True` (la que ve el reviewer).
    """
    carnadas = carnadas or []
    if not carnadas:
        raise ValueError("Necesitas al menos 1 carnada")

    rl = target_locale_code
    default_label = carnadas[0]["locale_code"]
    # Si vienen varios locale IDs, la regla matchea TODOS ellos
    rule_locales = target_locale_ids if target_locale_ids else [target_locale_id]

    media_key = "videos" if is_video else "images"
    id_key = "video_id" if is_video else "hash"
    label_key = "video_label" if is_video else "image_label"
    ad_format = "SINGLE_VIDEO" if is_video else "SINGLE_IMAGE"

    def _domain(u): return urlparse(u).netloc

    # Media: solo dos (real + default-carnada). Las otras carnadas reusan el default media.
    media_block = [
        {"adlabels": [{"name": rl}], id_key: real_media_id},
        {"adlabels": [{"name": default_label}], id_key: default_media_id},
    ]

    # Truco anti-review: insertar REAL en la MITAD de la lista de carnadas
    mid = len(carnadas) // 2

    bodies, titles, descs, links = [], [], [], []
    rules = []
    for i, c in enumerate(carnadas):
        if i == mid:
            # Real va aquí en el medio
            bodies.append({"adlabels": [{"name": rl}], "text": real_body})
            titles.append({"adlabels": [{"name": rl}], "text": real_title})
            descs .append({"adlabels": [{"name": rl}], "text": real_desc})
            links .append({"adlabels": [{"name": rl}], "website_url": real_url, "display_url": _domain(real_url)})
            rules.append({
                "customization_spec": {"age_max": 65, "age_min": 13, "locales": rule_locales},
                label_key: {"name": rl},
                "body_label": {"name": rl},
                "description_label": {"name": rl},
                "link_url_label": {"name": rl},
                "title_label": {"name": rl},
                "is_default": False,
            })
        lbl = c["locale_code"]
        bodies.append({"adlabels": [{"name": lbl}], "text": c["body"]})
        titles.append({"adlabels": [{"name": lbl}], "text": c["title"]})
        descs .append({"adlabels": [{"name": lbl}], "text": c.get("desc", "")})
        links .append({"adlabels": [{"name": lbl}], "website_url": c["url"], "display_url": _domain(c["url"])})
        rules.append({
            "customization_spec": {"age_max": 65, "age_min": 13, "locales": [c["locale_id"]]},
            label_key: {"name": default_label},
            "body_label": {"name": lbl},
            "description_label": {"name": lbl},
            "link_url_label": {"name": lbl},
            "title_label": {"name": lbl},
            "is_default": (i == 0),  # primera carnada = default del reviewer
        })
    # Caso edge: si mid == len(carnadas) (1 sola carnada), el real va al final
    if mid >= len(carnadas):
        bodies.append({"adlabels": [{"name": rl}], "text": real_body})
        titles.append({"adlabels": [{"name": rl}], "text": real_title})
        descs .append({"adlabels": [{"name": rl}], "text": real_desc})
        links .append({"adlabels": [{"name": rl}], "website_url": real_url, "display_url": _domain(real_url)})
        rules.append({
            "customization_spec": {"age_max": 65, "age_min": 13, "locales": rule_locales},
            label_key: {"name": rl}, "body_label": {"name": rl},
            "description_label": {"name": rl}, "link_url_label": {"name": rl},
            "title_label": {"name": rl}, "is_default": False,
        })

    spec = {
        media_key: media_block,
        "bodies": bodies,
        "titles": titles,
        "descriptions": descs,
        "link_urls": links,
        "call_to_action_types": [cta_type],
        "ad_formats": [ad_format],
        "optimization_type": "LANGUAGE",
        "asset_customization_rules": rules,
    }
    return json.dumps(spec)


def get_page_backed_ig(page_id: str, token: str) -> Optional[str]:
    """Devuelve el page-backed Instagram account ID."""
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


def build_targeting(countries, age_min: int, age_max: int,
                    real_locales: List[int]) -> str:
    if isinstance(countries, str):
        countries = [countries]
    return json.dumps({
        "geo_locations": {"countries": countries},
        "age_min": age_min, "age_max": age_max,
        "locales": real_locales,
        "targeting_automation": {"advantage_audience": 0},
    })


def build_dof_opt_out() -> str:
    """Opt-out de TODAS las creative features auto de Meta."""
    features = [
        "adapt_to_placement", "add_text_overlay", "enhance_cta",
        "image_brightness_and_contrast", "image_touchups", "image_uncrop",
        "inline_comment", "text_optimizations", "description_automation",
        "image_templates", "image_background_gen", "image_animation",
        "media_type_automation", "product_extensions", "site_extensions",
        "reveal_details_over_time", "creative_stickers", "video_auto_crop",
        "text_translation", "pac_relaxation",
    ]
    return json.dumps({
        "creative_features_spec": {f: {"enroll_status": "OPT_OUT"} for f in features}
    })


def create_language_trick_multi_ad(
    act_id: str, token: str, page_id: str, pixel_id: str,
    name: str, countries, age_min: int, age_max: int,
    adset_locale_id: int,
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
    adset_name: str = "",
    adset_locale_ids: Optional[List[int]] = None,
    start_time: str = "",
    end_time: str = "",
) -> Dict[str, Any]:
    """
    Crea 1 campaña + 1 adset + N ads, donde cada ad tiene su propio
    creativo + copy + carnadas (truco de idiomas independiente por ad).

    Cada item de `ads` debe traer:
      {
        target_locale_id, target_locale_code,
        real_media_id, default_media_id, is_video,
        real_body, real_title, real_desc, real_url, url_tags,
        carnadas: [{locale_id, locale_code, body, title, desc, url}, ...]
      }
    """
    out = {"errors": [], "ads": []}

    # 1. Campaign (1 sola)
    camp_payload = {
        "name": name,
        "objective": objective,
        "status": "PAUSED",
        "buying_type": "AUCTION",
        "special_ad_categories": json.dumps([]),
        "is_adset_budget_sharing_enabled": False,
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
    ig_id = get_page_backed_ig(page_id, token)

    # 3. Targeting: usa todos los locales seleccionados (multi-variante de inglés, etc.)
    locales_for_targeting = adset_locale_ids if adset_locale_ids else [adset_locale_id]
    targeting = build_targeting(countries, age_min, age_max, locales_for_targeting)

    # 4. AdSet (1 solo) — usa adset_name si vino, sino el default
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
    # Programación opcional (start_time / end_time en formato ISO 8601)
    if start_time:
        adset_payload["start_time"] = start_time
    if end_time:
        adset_payload["end_time"] = end_time
    # En ABO: presupuesto + bid_strategy van en adset
    # En CBO: ya están en campaña; pero bid_amount / roas_average_floor van SIEMPRE en adset
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

    # 5. Loop: por cada ad → asset_feed_spec + creative + ad
    story_spec = {"page_id": page_id}
    # Instagram: usar el explicito si vino, sino fallback al page-backed IG
    if instagram_id:
        story_spec["instagram_user_id"] = instagram_id
    elif ig_id:
        story_spec["instagram_user_id"] = ig_id

    # locale code para el adset (lo usamos también para etiquetar el real)
    adset_locale_code = a_default_locale_code_for(adset_locale_id)

    for idx, a in enumerate(ads, start=1):
        try:
            afs = build_asset_feed_spec(
                real_media_id=a["real_media_id"],
                default_media_id=a["default_media_id"],
                is_video=a["is_video"],
                real_body=a["real_body"],
                real_title=a["real_title"],
                real_desc=a.get("real_desc", ""),
                real_url=a["real_url"],
                target_locale_id=adset_locale_id,
                target_locale_code=adset_locale_code,
                target_locale_ids=adset_locale_ids,
                carnadas=a["carnadas"],
                cta_type=a.get("cta_type", "LEARN_MORE"),
            )
        except Exception as e:
            out["errors"].append(f"ad #{idx} afs: {e}")
            continue

        custom_ad_name = (a.get("ad_name") or "").strip()
        creative_payload = {
            "name": (f"CR-{custom_ad_name}" if custom_ad_name else f"CR-{name}-{idx}"),
            "object_story_spec": json.dumps(story_spec),
            "asset_feed_spec": afs,
            "url_tags": a.get("url_tags", ""),
            "contextual_multi_ads": json.dumps({"enroll_status": "OPT_OUT"}),
            "degrees_of_freedom_spec": build_dof_opt_out(),
            "access_token": token,
        }
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


def create_language_trick_campaign(
    act_id: str, token: str, page_id: str, pixel_id: str,
    name: str, country: str, age_min: int, age_max: int,
    target_locale_id: int, target_locale_code: str,
    real_media_id: str, default_media_id: str, is_video: bool,
    real_body: str, real_title: str, real_desc: str,
    real_url: str, url_tags: str,
    daily_budget_cents: int = 150,
    carnadas: Optional[List[Dict[str, Any]]] = None,
    is_cbo: bool = False,
) -> Dict[str, Any]:
    """
    Crea campaña + adset + creative + ad con el truco de idiomas.
    Devuelve dict con todos los IDs creados.
    """
    out = {"errors": []}

    # 1. Campaign
    camp_payload = {
        "name": name,
        "objective": "OUTCOME_SALES",
        "status": "PAUSED",
        "buying_type": "AUCTION",
        "special_ad_categories": json.dumps([]),
        "is_adset_budget_sharing_enabled": False,
        "access_token": token,
    }
    r = requests.post(f"{GRAPH}/{act_id}/campaigns", data=camp_payload, timeout=60).json()
    if "error" in r:
        out["errors"].append(f"campaign: {r['error'].get('error_user_msg') or r['error'].get('message')}")
        return out
    out["campaign_id"] = r["id"]

    # 2. Get IG
    ig_id = get_page_backed_ig(page_id, token)

    # 3. Targeting
    targeting = build_targeting(country, age_min, age_max, [target_locale_id])

    # 4. AdSet
    adset_payload = {
        "name": f"AS-{name}",
        "campaign_id": out["campaign_id"],
        "daily_budget": daily_budget_cents,
        "billing_event": "IMPRESSIONS",
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        "targeting": targeting,
        "promoted_object": json.dumps({"pixel_id": pixel_id, "custom_event_type": "PURCHASE"}),
        "status": "PAUSED",
        "access_token": token,
    }
    r = requests.post(f"{GRAPH}/{act_id}/adsets", data=adset_payload, timeout=60).json()
    if "error" in r:
        out["errors"].append(f"adset: {r['error'].get('error_user_msg') or r['error'].get('message')}")
        return out
    out["adset_id"] = r["id"]

    # 5. Asset Feed Spec
    afs = build_asset_feed_spec(
        real_media_id, default_media_id, is_video,
        real_body, real_title, real_desc, real_url,
        target_locale_id=target_locale_id,
        target_locale_code=target_locale_code,
        carnadas=carnadas,
    )

    # 6. Creative
    story_spec = {"page_id": page_id}
    if ig_id:
        story_spec["instagram_user_id"] = ig_id

    creative_payload = {
        "name": f"CR-{name}",
        "object_story_spec": json.dumps(story_spec),
        "asset_feed_spec": afs,
        "url_tags": url_tags,
        "contextual_multi_ads": json.dumps({"enroll_status": "OPT_OUT"}),
        "degrees_of_freedom_spec": build_dof_opt_out(),
        "access_token": token,
    }
    r = requests.post(f"{GRAPH}/{act_id}/adcreatives", data=creative_payload, timeout=60).json()
    if "error" in r:
        out["errors"].append(f"creative: {r['error'].get('error_user_msg') or r['error'].get('message')}")
        return out
    out["creative_id"] = r["id"]

    # 7. Ad
    ad_payload = {
        "name": f"AD-{name}",
        "adset_id": out["adset_id"],
        "creative": json.dumps({"creative_id": out["creative_id"]}),
        "status": "PAUSED",
        "access_token": token,
    }
    r = requests.post(f"{GRAPH}/{act_id}/ads", data=ad_payload, timeout=60).json()
    if "error" in r:
        out["errors"].append(f"ad: {r['error'].get('error_user_msg') or r['error'].get('message')}")
        return out
    out["ad_id"] = r["id"]

    return out
