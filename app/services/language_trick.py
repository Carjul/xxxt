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
                          real_url: str, real_label: str = "en_XX",
                          real_locales: List[int] = None,
                          default_copy: Dict[str, Dict[str, str]] = None) -> str:
    """
    Construye el asset_feed_spec con el truco de idiomas.

    real_media_id: hash (imagen) o video_id (video) del creativo REAL
    default_media_id: hash/video_id del creativo CARNADA (idealmente francés)
    is_video: True si videos, False si imágenes
    real_body/title/desc/url: copy del creativo real (idioma del target)
    real_label: etiqueta del idioma real (ej: 'en_XX')
    real_locales: lista de locale IDs del idioma real (ej: [6] para inglés US)
    default_copy: dict {fr, ru, ja, ar} con copy de carnada por idioma
    """
    real_locales = real_locales or [6]
    dc = default_copy or DEFAULT_LANG_COPY
    rl = real_label

    media_key = "videos" if is_video else "images"
    id_key = "video_id" if is_video else "hash"
    label_key = "video_label" if is_video else "image_label"
    ad_format = "SINGLE_VIDEO" if is_video else "SINGLE_IMAGE"

    def _domain(u): return urlparse(u).netloc

    spec = {
        media_key: [
            {"adlabels": [{"name": rl}], id_key: real_media_id},
            {"adlabels": [{"name": "fr_XX"}], id_key: default_media_id},
        ],
        "bodies": [
            {"adlabels": [{"name": rl}], "text": real_body},
            {"adlabels": [{"name": "fr_XX"}], "text": dc["fr"]["body"]},
            {"adlabels": [{"name": "ru_RU"}], "text": dc["ru"]["body"]},
            {"adlabels": [{"name": "ja_XX"}], "text": dc["ja"]["body"]},
            {"adlabels": [{"name": "ar_AR"}], "text": dc["ar"]["body"]},
        ],
        "titles": [
            {"adlabels": [{"name": rl}], "text": real_title},
            {"adlabels": [{"name": "fr_XX"}], "text": dc["fr"]["title"]},
            {"adlabels": [{"name": "ru_RU"}], "text": dc["ru"]["title"]},
            {"adlabels": [{"name": "ja_XX"}], "text": dc["ja"]["title"]},
            {"adlabels": [{"name": "ar_AR"}], "text": dc["ar"]["title"]},
        ],
        "descriptions": [
            {"adlabels": [{"name": rl}], "text": real_desc},
            {"adlabels": [{"name": "fr_XX"}], "text": dc["fr"]["desc"]},
            {"adlabels": [{"name": "ru_RU"}], "text": dc["ru"]["desc"]},
            {"adlabels": [{"name": "ja_XX"}], "text": dc["ja"]["desc"]},
            {"adlabels": [{"name": "ar_AR"}], "text": dc["ar"]["desc"]},
        ],
        "link_urls": [
            {"adlabels": [{"name": rl}], "website_url": real_url, "display_url": _domain(real_url)},
            {"adlabels": [{"name": "fr_XX"}], "website_url": dc["fr"]["url"], "display_url": _domain(dc["fr"]["url"])},
            {"adlabels": [{"name": "ru_RU"}], "website_url": dc["ru"]["url"], "display_url": _domain(dc["ru"]["url"])},
            {"adlabels": [{"name": "ja_XX"}], "website_url": dc["ja"]["url"], "display_url": _domain(dc["ja"]["url"])},
            {"adlabels": [{"name": "ar_AR"}], "website_url": dc["ar"]["url"], "display_url": _domain(dc["ar"]["url"])},
        ],
        "call_to_action_types": ["LEARN_MORE"],
        "ad_formats": [ad_format],
        "optimization_type": "LANGUAGE",
        "asset_customization_rules": [
            {"customization_spec": {"age_max": 65, "age_min": 13, "locales": [44, 9]},
             label_key: {"name": "fr_XX"}, "body_label": {"name": "fr_XX"},
             "description_label": {"name": "fr_XX"}, "link_url_label": {"name": "fr_XX"},
             "title_label": {"name": "fr_XX"}, "is_default": True},
            {"customization_spec": {"age_max": 65, "age_min": 13, "locales": [17]},
             label_key: {"name": "fr_XX"}, "body_label": {"name": "ru_RU"},
             "description_label": {"name": "ru_RU"}, "link_url_label": {"name": "ru_RU"},
             "title_label": {"name": "ru_RU"}, "is_default": False},
            {"customization_spec": {"age_max": 65, "age_min": 13, "locales": [11, 70]},
             label_key: {"name": "fr_XX"}, "body_label": {"name": "ja_XX"},
             "description_label": {"name": "ja_XX"}, "link_url_label": {"name": "ja_XX"},
             "title_label": {"name": "ja_XX"}, "is_default": False},
            {"customization_spec": {"age_max": 65, "age_min": 13, "locales": real_locales},
             label_key: {"name": rl}, "body_label": {"name": rl},
             "description_label": {"name": rl}, "link_url_label": {"name": rl},
             "title_label": {"name": rl}, "is_default": False},
            {"customization_spec": {"age_max": 65, "age_min": 13, "locales": [28]},
             label_key: {"name": "fr_XX"}, "body_label": {"name": "ar_AR"},
             "description_label": {"name": "ar_AR"}, "link_url_label": {"name": "ar_AR"},
             "title_label": {"name": "ar_AR"}, "is_default": False},
        ],
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


def build_targeting(country: str, age_min: int, age_max: int,
                    real_locales: List[int]) -> str:
    return json.dumps({
        "geo_locations": {"countries": [country]},
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


def create_language_trick_campaign(
    act_id: str, token: str, page_id: str, pixel_id: str,
    name: str, country: str, age_min: int, age_max: int,
    real_locales: List[int], real_label: str,
    real_media_id: str, default_media_id: str, is_video: bool,
    real_body: str, real_title: str, real_desc: str,
    real_url: str, url_tags: str,
    daily_budget_cents: int = 150,
    default_copy: Optional[Dict] = None,
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
        "is_adset_budget_sharing_enabled": is_cbo,
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
    targeting = build_targeting(country, age_min, age_max, real_locales)

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
        real_label, real_locales, default_copy,
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
