"""Wrapper para Meta Marketing API. Maneja rate limits con retry/backoff."""
import json
import time
from typing import Any, Dict, List, Optional

import requests

from .config import FB_ACCESS_TOKEN, FB_GRAPH_BASE


def get_effective_token() -> str:
    try:
        from .database import create_db_session
        from .meta_connections import get_active_token
        db = create_db_session()
        try:
            return get_active_token(db) or ""
        finally:
            db.close()
    except Exception:
        return FB_ACCESS_TOKEN or ""


class MetaApiError(Exception):
    def __init__(self, status: int, payload: dict):
        self.status = status
        self.payload = payload
        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        title = err.get("error_user_title") or err.get("message") or "Unknown error"
        detail = err.get("error_user_msg") or ""
        msg = f"{title}" + (f" — {detail}" if detail else "")
        if not msg.strip() or msg == "Unknown error":
            msg = json.dumps(payload)[:300]
        super().__init__(f"[{status}] {msg}")


def _request(method: str, path: str, *, token: Optional[str] = None, params: Optional[dict] = None,
             data: Optional[dict] = None, retries: int = 3) -> Dict[str, Any]:
    url = path if path.startswith("http") else f"{FB_GRAPH_BASE}/{path.lstrip('/')}"
    p = dict(params or {})
    p["access_token"] = token or get_effective_token()

    for attempt in range(retries):
        try:
            kwargs = {"params": p, "timeout": 60}
            if method != "GET" and data is not None:
                kwargs["data"] = data
            r = requests.request(method, url, **kwargs)
            try:
                payload = r.json()
            except ValueError:
                payload = {"error": {"message": r.text[:300]}}

            if r.status_code == 429 or (isinstance(payload.get("error"), dict)
                                        and payload["error"].get("code") in (4, 17, 32, 613)):
                wait = 2 ** attempt
                time.sleep(wait)
                continue

            if r.status_code >= 400:
                raise MetaApiError(r.status_code, payload)

            return payload
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise MetaApiError(0, {"error": {"message": str(e)}})
            time.sleep(2 ** attempt)

    raise MetaApiError(0, {"error": {"message": "exhausted retries"}})


def get(path: str, params: Optional[dict] = None, token: Optional[str] = None) -> Dict[str, Any]:
    return _request("GET", path, params=params, token=token)


def post(path: str, data: Optional[dict] = None, token: Optional[str] = None) -> Dict[str, Any]:
    return _request("POST", path, data=data, token=token)


def delete(path: str, token: Optional[str] = None) -> Dict[str, Any]:
    return _request("DELETE", path, token=token)


def list_ad_accounts(token: Optional[str] = None) -> List[dict]:
    out = []
    res = get("me/adaccounts", {"fields": "id,name,account_id,business,currency,timezone_name", "limit": 100}, token)
    out.extend(res.get("data", []))
    return out


def list_pages(token: Optional[str] = None) -> List[dict]:
    res = get("me/accounts", {"fields": "id,name,instagram_business_account", "limit": 100}, token)
    return res.get("data", [])


def list_pixels(act_id: str, token: Optional[str] = None) -> List[dict]:
    res = get(f"act_{act_id.replace('act_', '')}/adspixels", {"fields": "id,name,last_fired_time", "limit": 50}, token)
    return res.get("data", [])


def list_businesses(token: Optional[str] = None) -> List[dict]:
    res = get("me/businesses", {"fields": "id,name", "limit": 50}, token)
    return res.get("data", [])


def get_ad_account_info(act_id: str, token: Optional[str] = None) -> dict:
    return get(f"act_{act_id.replace('act_', '')}", {"fields": "id,name,business,currency,timezone_name"}, token)


def create_catalog(business_id: str, name: str, token: Optional[str] = None) -> dict:
    return post(f"{business_id}/owned_product_catalogs", {"name": name, "vertical": "commerce"}, token)


def attach_pixel_to_catalog(catalog_id: str, pixel_id: str, token: Optional[str] = None) -> dict:
    return post(f"{catalog_id}/external_event_sources", {"external_event_sources": json.dumps([pixel_id])}, token)


def create_feed(catalog_id: str, name: str, csv_url: str, token: Optional[str] = None) -> dict:
    schedule = {"interval": "DAILY", "url": csv_url, "hour": 4}
    return post(f"{catalog_id}/product_feeds",
                {"name": name, "schedule": json.dumps(schedule)}, token)


def create_product_set(catalog_id: str, name: str, retailer_ids: List[str], token: Optional[str] = None) -> dict:
    flt = {"retailer_id": {"is_any": retailer_ids}}
    return post(f"{catalog_id}/product_sets", {"name": name, "filter": json.dumps(flt)}, token)


def update_product_set(fb_set_id: str, name: str, retailer_ids: List[str], token: Optional[str] = None) -> dict:
    flt = {"retailer_id": {"is_any": retailer_ids}}
    return post(fb_set_id, {"name": name, "filter": json.dumps(flt)}, token)


def update_product_availability(catalog_id: str, retailer_id: str, availability: str,
                                token: Optional[str] = None) -> dict:
    """Marca un producto como in_stock/out_of_stock vía batch upsert."""
    return post(f"{catalog_id}/items_batch", {
        "item_type": "PRODUCT_ITEM",
        "requests": json.dumps([{
            "method": "UPDATE",
            "data": {
                "id": retailer_id,
                "availability": availability,
            }
        }])
    }, token)


def create_campaign(act_id: str, payload: dict, token: Optional[str] = None) -> dict:
    return post(f"act_{act_id.replace('act_', '')}/campaigns", payload, token)


def create_adset(act_id: str, payload: dict, token: Optional[str] = None) -> dict:
    return post(f"act_{act_id.replace('act_', '')}/adsets", payload, token)


def create_adcreative(act_id: str, payload: dict, token: Optional[str] = None) -> dict:
    return post(f"act_{act_id.replace('act_', '')}/adcreatives", payload, token)


def create_ad(act_id: str, payload: dict, token: Optional[str] = None) -> dict:
    return post(f"act_{act_id.replace('act_', '')}/ads", payload, token)


def get_ad(ad_id: str, fields: str = "id,name,effective_status,status", token: Optional[str] = None) -> dict:
    return get(ad_id, {"fields": fields}, token)


def get_campaign_insights(campaign_id: str, token: Optional[str] = None,
                          date_preset: str = "today") -> dict:
    """Devuelve spend + conversions del día actual."""
    res = get(f"{campaign_id}/insights",
              {"fields": "spend,actions", "date_preset": date_preset, "limit": 1}, token)
    data = res.get("data", [{}])
    return data[0] if data else {}


def parse_purchases(insights: dict) -> int:
    """Extrae cantidad de conversiones (purchases) de la respuesta de insights."""
    actions = insights.get("actions", []) or []
    for a in actions:
        if a.get("action_type") in ("offsite_conversion.fb_pixel_Purchase", "purchase"):
            try:
                return int(float(a.get("value", "0")))
            except ValueError:
                return 0
    return 0


def get_page_from_existing_ad(act_id: str, token: Optional[str] = None) -> Optional[str]:
    """Busca un page_id en ads existentes de la cuenta."""
    try:
        res = get(f"act_{act_id.replace('act_', '')}/ads",
                  {"fields": "creative{object_story_spec}", "limit": 1}, token)
        ads = res.get("data", [])
        if ads:
            spec = ads[0].get("creative", {}).get("object_story_spec", {})
            return spec.get("page_id")
    except MetaApiError:
        pass
    return None
