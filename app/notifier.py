"""Envía notificaciones a Telegram y Slack."""
import logging
import requests
from typing import Optional

from .database import SessionLocal
from .models import AppSettings

log = logging.getLogger("notifier")


def _get_settings() -> Optional[AppSettings]:
    db = SessionLocal()
    try:
        return db.query(AppSettings).first()
    finally:
        db.close()


def send_telegram(message: str, token: Optional[str] = None, chat_id: Optional[str] = None) -> bool:
    s = _get_settings()
    token = token or (s.telegram_bot_token if s else None)
    chat_id = chat_id or (s.telegram_chat_id if s else None)
    if not token or not chat_id:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=15,
        )
        r.raise_for_status()
        return True
    except Exception as e:
        log.exception(f"telegram fail: {e}")
        return False


def send_slack(message: str, webhook_url: Optional[str] = None) -> bool:
    s = _get_settings()
    webhook_url = webhook_url or (s.slack_webhook_url if s else None)
    if not webhook_url:
        return False
    try:
        r = requests.post(webhook_url, json={"text": message}, timeout=15)
        r.raise_for_status()
        return True
    except Exception as e:
        log.exception(f"slack fail: {e}")
        return False


def notify(message: str) -> dict:
    """Envía a Telegram y Slack si están configurados."""
    return {
        "telegram": send_telegram(message),
        "slack": send_slack(message),
    }


def notify_approval(campaign_name: str, ad_id: str, ad_account: str) -> dict:
    msg = (
        f"<b>✓ Anuncio aprobado</b>\n"
        f"Campaña: <code>{campaign_name}</code>\n"
        f"Ad ID: <code>{ad_id}</code>\n"
        f"Cuenta: <code>act_{ad_account}</code>"
    )
    return notify(msg)


def notify_conversion(campaign_name: str, new_conversions: int, total_conversions: int, spend: float) -> dict:
    msg = (
        f"<b>$ Conversión nueva</b>\n"
        f"Campaña: <code>{campaign_name}</code>\n"
        f"Nuevas: <b>+{new_conversions}</b> (total {total_conversions})\n"
        f"Gasto: ${spend:.2f}"
    )
    return notify(msg)


def send_test(message: str = "Test desde FB Catalog Dashboard") -> dict:
    return notify(message)
