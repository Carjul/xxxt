from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import meta_api
from ..database import MongoSession, get_db
from ..meta_connections import (
    get_effective_defaults,
    get_active_connection,
    get_active_token,
    list_connections,
    set_active_connection,
    test_connection_token,
    upsert_env_connection,
)
from ..models import AppSettings, MetaConnection

router = APIRouter()


def _get_settings(db: MongoSession) -> AppSettings:
    s = db.query(AppSettings).first()
    if not s:
        s = AppSettings()
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _build_setup_context(request: Request, db: MongoSession, *, error: str | None = None):
    upsert_env_connection(db)
    settings = _get_settings(db)
    connections = list_connections(db)
    active_connection = get_active_connection(db)
    defaults = get_effective_defaults(db)
    token = get_active_token(db)

    accounts, pages, businesses, pixels = [], [], [], []
    errors = [error] if error else []

    if token:
        try:
            accounts = meta_api.list_ad_accounts(token=token)
        except Exception as exc:
            errors.append(f"Ad accounts: {exc}")
        try:
            pages = meta_api.list_pages(token=token)
        except Exception as exc:
            errors.append(f"Paginas: {exc}")
        try:
            businesses = meta_api.list_businesses(token=token)
        except Exception as exc:
            errors.append(f"Business Managers: {exc}")
        if defaults["ad_account_id"]:
            try:
                pixels = meta_api.list_pixels(defaults["ad_account_id"], token=token)
            except Exception as exc:
                errors.append(f"Pixeles: {exc}")

    selected_business_id = defaults["business_id"]
    if selected_business_id and not any(b.get("id") == selected_business_id for b in businesses):
        fallback_name = None
        if active_connection and active_connection.business_id == selected_business_id:
            fallback_name = active_connection.business_name
        businesses = businesses + [{
            "id": selected_business_id,
            "name": fallback_name or "BM guardado",
        }]

    return {
        "request": request,
        "settings": settings,
        "connections": connections,
        "active_connection": active_connection,
        "defaults": defaults,
        "accounts": accounts,
        "pages": pages,
        "businesses": businesses,
        "pixels": pixels,
        "error": " | ".join(x for x in errors if x) or None,
        "token_set": bool(token),
    }


@router.get("/setup")
def setup_page(request: Request, db: MongoSession = Depends(get_db)):
    return request.app.state.templates.TemplateResponse(request, "setup.html", _build_setup_context(request, db))


@router.post("/setup/meta-connections")
def create_meta_connection(
    request: Request,
    db: MongoSession = Depends(get_db),
    name: str = Form(...),
    token: str = Form(...),
    business_id: str = Form(""),
    activate_now: str = Form("yes"),
):
    token = token.strip()
    name = name.strip()
    if not token or not name:
        context = _build_setup_context(request, db, error="Nombre y token son obligatorios")
        return request.app.state.templates.TemplateResponse(request, "setup.html", context, status_code=400)

    try:
        result = test_connection_token(token)
    except Exception as exc:
        context = _build_setup_context(request, db, error=f"Token invalido: {exc}")
        return request.app.state.templates.TemplateResponse(request, "setup.html", context, status_code=400)

    business_name = None
    selected_business_id = business_id or None
    for business in result["businesses"]:
        if business.get("id") == selected_business_id:
            business_name = business.get("name")
            break
    if not selected_business_id and len(result["businesses"]) == 1:
        selected_business_id = result["businesses"][0].get("id")
        business_name = result["businesses"][0].get("name")

    connection = MetaConnection(
        name=name,
        token=token,
        token_last4=token[-4:],
        business_id=selected_business_id,
        business_name=business_name,
        is_active=False,
        is_valid=True,
        last_error=None,
        last_tested_at=datetime.utcnow(),
    )
    db.add(connection)
    db.commit()

    if activate_now == "yes":
        set_active_connection(db, connection.id)

    return RedirectResponse("/setup?connection_saved=1", status_code=303)


@router.post("/setup/meta-connections/{connection_id}/activate")
def activate_meta_connection(connection_id: int, db: MongoSession = Depends(get_db)):
    connection = set_active_connection(db, connection_id)
    if not connection:
        raise HTTPException(404)
    return RedirectResponse("/setup?connection_active=1", status_code=303)


@router.post("/setup/meta-connections/{connection_id}/test")
def test_meta_connection(connection_id: int, db: MongoSession = Depends(get_db)):
    connection = db.query(MetaConnection).filter(MetaConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(404)
    try:
        result = test_connection_token(connection.token)
        connection.is_valid = True
        connection.last_error = None
        connection.last_tested_at = datetime.utcnow()
        if connection.business_id:
            for business in result["businesses"]:
                if business.get("id") == connection.business_id:
                    connection.business_name = business.get("name")
                    break
        db.commit()
        return RedirectResponse("/setup?token_ok=1", status_code=303)
    except Exception as exc:
        connection.is_valid = False
        connection.last_error = str(exc)
        connection.last_tested_at = datetime.utcnow()
        db.commit()
        return RedirectResponse("/setup?token_ok=0", status_code=303)


@router.post("/setup/meta-connections/{connection_id}/delete")
def delete_meta_connection(connection_id: int, db: MongoSession = Depends(get_db)):
    connection = db.query(MetaConnection).filter(MetaConnection.id == connection_id).first()
    if not connection:
        raise HTTPException(404)
    was_active = bool(connection.is_active)
    db.delete(connection)
    db.commit()
    if was_active:
        remaining = list_connections(db)
        if len(remaining) == 1:
            set_active_connection(db, remaining[0].id)
    return RedirectResponse("/setup?connection_deleted=1", status_code=303)


@router.post("/setup")
def setup_save(
    db: MongoSession = Depends(get_db),
    business_id: str = Form(""),
    ad_account_id: str = Form(""),
    page_id: str = Form(""),
    pixel_id: str = Form(""),
    telegram_bot_token: str = Form(""),
    telegram_chat_id: str = Form(""),
    slack_webhook_url: str = Form(""),
    notify_on_approval: str = Form(""),
    notify_on_conversion: str = Form(""),
):
    s = _get_settings(db)
    s.telegram_bot_token = telegram_bot_token or None
    s.telegram_chat_id = telegram_chat_id or None
    s.slack_webhook_url = slack_webhook_url or None
    s.notify_on_approval = notify_on_approval == "yes"
    s.notify_on_conversion = notify_on_conversion == "yes"

    active_connection = get_active_connection(db)
    if active_connection:
        active_connection.business_id = business_id or None
        active_connection.default_ad_account_id = ad_account_id or None
        active_connection.default_page_id = page_id or None
        active_connection.default_pixel_id = pixel_id or None
        active_connection.business_name = None
        if business_id:
            try:
                businesses = meta_api.list_businesses(token=active_connection.token)
                for business in businesses:
                    if business.get("id") == business_id:
                        active_connection.business_name = business.get("name")
                        break
            except Exception:
                pass
    else:
        s.default_business_id = business_id or None
        s.default_ad_account_id = ad_account_id or None
        s.default_page_id = page_id or None
        s.default_pixel_id = pixel_id or None

    db.commit()
    return RedirectResponse("/setup?saved=1", status_code=303)


@router.post("/setup/test-notification")
def test_notification():
    from .. import notifier

    res = notifier.send_test("Test desde FB Catalog Dashboard — si ves esto, las notificaciones funcionan.")
    return RedirectResponse(f"/setup?test_telegram={int(res['telegram'])}&test_slack={int(res['slack'])}", status_code=303)
