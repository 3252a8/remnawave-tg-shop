from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.web_auth_service import WEB_AUTH_EMAIL_PURPOSE, WEB_AUTH_TELEGRAM_LINK_PURPOSE
from db.dal import payment_dal, subscription_dal, user_billing_dal, user_dal
from db.models import Payment, Subscription, User, UserPaymentMethod


WEB_SESSION_HEADER = "X-Web-Session-Token"


def _json_error(status: int, code: str, message: str, **extra: Any) -> web.Response:
    payload: Dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if extra:
        payload["error"].update(extra)
    return web.json_response(payload, status=status)


def _json_ok(data: Optional[Dict[str, Any]] = None, *, status: int = 200) -> web.Response:
    payload: Dict[str, Any] = {"ok": True}
    if data:
        payload.update(data)
    return web.json_response(payload, status=status)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_language(language_code: Optional[str], fallback: str) -> str:
    normalized = (language_code or "").strip().lower()
    return normalized or fallback


def _format_dt(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _format_date(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.strftime("%Y-%m-%d")


def _format_human_amount(value: Optional[float]) -> str:
    if value is None:
        return "0"
    value_f = float(value)
    return str(int(value_f)) if value_f.is_integer() else f"{value_f:g}"


def _format_bytes(value: Optional[int]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value) / (1024**3), 2)


def _device_token(hwid: Optional[str]) -> Optional[str]:
    if not hwid:
        return None
    return hashlib.sha256(str(hwid).encode("utf-8")).hexdigest()[:32]


def _payment_provider_label(provider: Optional[str]) -> str:
    mapping = {
        "yookassa": "YooKassa",
        "freekassa": "FreeKassa",
        "platega": "Platega",
        "severpay": "SeverPay",
        "cryptopay": "CryptoPay",
        "telegram_stars": "Stars",
        "stars": "Stars",
    }
    return mapping.get((provider or "").lower(), provider or "unknown")


def _serialize_user(user: User) -> Dict[str, Any]:
    display_name = " ".join(part for part in [user.first_name, user.last_name] if part).strip()
    return {
        "id": user.user_id,
        "email": user.email,
        "email_verified_at": _format_dt(user.email_verified_at),
        "telegram_user_id": user.telegram_user_id,
        "telegram_linked_at": _format_dt(user.telegram_linked_at),
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "display_name": display_name or user.username or user.email or f"User {user.user_id}",
        "language_code": user.language_code,
        "registration_date": _format_dt(user.registration_date),
        "is_banned": bool(user.is_banned),
        "panel_user_uuid": user.panel_user_uuid,
        "referral_code": user.referral_code,
        "referred_by_id": user.referred_by_id,
        "lifetime_used_traffic_bytes": user.lifetime_used_traffic_bytes,
        "lifetime_used_traffic_gb": _format_bytes(user.lifetime_used_traffic_bytes),
        "channel_subscription_verified": user.channel_subscription_verified,
    }


def _serialize_payment_method(method: UserPaymentMethod) -> Dict[str, Any]:
    return {
        "id": method.method_id,
        "user_id": method.user_id,
        "provider": method.provider,
        "provider_payment_method_id": method.provider_payment_method_id,
        "card_last4": method.card_last4,
        "card_network": method.card_network,
        "is_default": bool(method.is_default),
        "created_at": _format_dt(method.created_at),
        "updated_at": _format_dt(method.updated_at),
    }


def _serialize_payment(payment: Payment) -> Dict[str, Any]:
    return {
        "id": payment.payment_id,
        "user_id": payment.user_id,
        "provider": payment.provider,
        "provider_label": _payment_provider_label(payment.provider),
        "provider_payment_id": payment.provider_payment_id,
        "yookassa_payment_id": payment.yookassa_payment_id,
        "amount": float(payment.amount),
        "amount_display": f"{float(payment.amount):.2f}",
        "currency": payment.currency,
        "status": payment.status,
        "description": payment.description,
        "subscription_duration_months": payment.subscription_duration_months,
        "created_at": _format_dt(payment.created_at),
        "created_at_short": _format_date(payment.created_at),
        "updated_at": _format_dt(payment.updated_at),
    }


def _serialize_subscription(sub: Optional[Subscription], details: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not sub and not details:
        return None
    data = dict(details or {})
    if sub:
        data.update(
            {
                "subscription_id": sub.subscription_id,
                "panel_user_uuid": sub.panel_user_uuid,
                "panel_subscription_uuid": sub.panel_subscription_uuid,
                "start_date": _format_dt(sub.start_date),
                "end_date": _format_dt(sub.end_date),
                "duration_months": sub.duration_months,
                "is_active": bool(sub.is_active),
                "status_from_panel": sub.status_from_panel,
                "traffic_limit_bytes": sub.traffic_limit_bytes,
                "traffic_limit_gb": _format_bytes(sub.traffic_limit_bytes),
                "traffic_used_bytes": sub.traffic_used_bytes,
                "traffic_used_gb": _format_bytes(sub.traffic_used_bytes),
                "provider": sub.provider,
                "skip_notifications": bool(sub.skip_notifications),
                "auto_renew_enabled": bool(sub.auto_renew_enabled),
                "last_notification_sent": _format_dt(sub.last_notification_sent),
            }
        )
    if "end_date" in data and isinstance(data["end_date"], datetime):
        data["end_date"] = _format_dt(data["end_date"])
    if "config_link" not in data and details and details.get("config_link"):
        data["config_link"] = details["config_link"]
    if "connect_button_url" not in data and details and details.get("connect_button_url"):
        data["connect_button_url"] = details["connect_button_url"]
    if "max_devices" not in data and details and details.get("max_devices") is not None:
        data["max_devices"] = details["max_devices"]
    return data


def _serialize_device(device: Dict[str, Any], *, index: int) -> Dict[str, Any]:
    hwid = device.get("hwid")
    created_at = device.get("createdAt")
    created_short = None
    if created_at:
        try:
            created_short = _format_date(datetime.fromisoformat(created_at))
        except Exception:
            created_short = str(created_at)
    return {
        "index": index,
        "hwid_token": _device_token(hwid),
        "hwid_masked": f"{str(hwid)[:8]}...{str(hwid)[-6:]}" if hwid else None,
        "device_model": device.get("deviceModel"),
        "platform": device.get("platform"),
        "os_version": device.get("osVersion"),
        "user_agent": device.get("userAgent"),
        "created_at": created_at,
        "created_at_short": created_short,
        "hwid": hwid,
    }


def _build_public_config(
    settings,
    *,
    email_auth_enabled: bool,
    bot_username: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "web_app_url": settings.WEB_APP_URL,
        "bot_username": bot_username,
        "default_language": settings.DEFAULT_LANGUAGE,
        "support_link": settings.SUPPORT_LINK,
        "privacy_policy_url": settings.PRIVACY_POLICY_URL,
        "terms_of_service_url": settings.TERMS_OF_SERVICE_URL,
        "user_agreement_url": settings.USER_AGREEMENT_URL,
        "email_auth_enabled": bool(email_auth_enabled),
        "trial_enabled": bool(settings.TRIAL_ENABLED),
        "traffic_sale_mode": bool(settings.traffic_sale_mode),
        "my_devices_enabled": bool(settings.MY_DEVICES_SECTION_ENABLED),
        "yookassa_enabled": bool(settings.YOOKASSA_ENABLED),
        "yookassa_autopayments_enabled": bool(settings.yookassa_autopayments_active),
        "cryptopay_enabled": bool(settings.CRYPTOPAY_ENABLED),
        "freekassa_enabled": bool(settings.FREEKASSA_ENABLED),
        "platega_enabled": bool(settings.PLATEGA_ENABLED),
        "severpay_enabled": bool(settings.SEVERPAY_ENABLED),
        "stars_enabled": bool(settings.STARS_ENABLED),
        "payment_methods_order": settings.payment_methods_order,
    }


def _build_plan_catalog(settings) -> Dict[str, Any]:
    traffic_mode = bool(settings.traffic_sale_mode)
    cash_map = settings.traffic_packages if traffic_mode else settings.subscription_options
    stars_map = settings.stars_traffic_packages if traffic_mode else settings.stars_subscription_options
    units_label = "GB" if traffic_mode else "months"
    plans = []
    for unit in sorted(set(cash_map.keys()) | set(stars_map.keys())):
        plans.append(
            {
                "units": unit,
                "units_display": _format_human_amount(unit),
                "unit_label": units_label,
                "cash_price": cash_map.get(unit),
                "stars_price": stars_map.get(unit),
                "cash_currency": settings.DEFAULT_CURRENCY_SYMBOL,
                "stars_currency": "⭐",
                "cash_enabled": cash_map.get(unit) is not None,
                "stars_enabled": stars_map.get(unit) is not None and settings.STARS_ENABLED,
            }
        )
    return {"traffic_mode": traffic_mode, "units_label": units_label, "plans": plans}


def _build_provider_catalog(settings, *, stars_available: bool) -> list[Dict[str, Any]]:
    order = settings.payment_methods_order
    provider_defs = {
        "yookassa": {"label": "YooKassa", "enabled": bool(settings.YOOKASSA_ENABLED), "supports_saved_cards": bool(settings.yookassa_autopayments_active)},
        "freekassa": {"label": "FreeKassa", "enabled": bool(settings.FREEKASSA_ENABLED)},
        "platega": {"label": "Platega", "enabled": bool(settings.PLATEGA_ENABLED)},
        "severpay": {"label": "SeverPay", "enabled": bool(settings.SEVERPAY_ENABLED)},
        "cryptopay": {"label": "CryptoPay", "enabled": bool(settings.CRYPTOPAY_ENABLED)},
        "stars": {"label": "Telegram Stars", "enabled": bool(settings.STARS_ENABLED and stars_available), "requires_telegram": True},
    }
    providers: list[Dict[str, Any]] = []
    for key in order:
        if key in provider_defs:
            providers.append({"key": key, **provider_defs[key]})
    for key, spec in provider_defs.items():
        if key not in order:
            providers.append({"key": key, **spec})
    return providers


async def _extract_request_data(request: web.Request) -> Dict[str, Any]:
    try:
        data = await request.json()
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    try:
        post_data = await request.post()
        return {str(k): v for k, v in post_data.items()}
    except Exception:
        return {}


def _extract_session_token(request: web.Request) -> Optional[str]:
    header_token = request.headers.get(WEB_SESSION_HEADER)
    if header_token:
        return header_token.strip()
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    cookie_token = request.cookies.get("web_session")
    if cookie_token:
        return cookie_token.strip()
    return None


def _extract_client_ip(request: web.Request) -> Optional[str]:
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    if forwarded_for:
        first_ip = forwarded_for.split(",")[0].strip()
        if first_ip:
            return first_ip
    forwarded = request.headers.get("X-Real-IP", "").strip()
    if forwarded:
        return forwarded
    return request.remote


async def _get_authenticated_user(request: web.Request, session: AsyncSession) -> Tuple[Optional[User], Optional[Any]]:
    token = _extract_session_token(request)
    if not token:
        return None, None
    web_auth_service = request.app["web_auth_service"]
    web_session = await web_auth_service.authenticate_web_session(session, raw_token=token)
    if not web_session or not web_session.user:
        return None, None
    if web_session.user.is_banned:
        await web_auth_service.revoke_web_session(session, raw_token=token)
        return None, None
    return web_session.user, web_session


async def _get_user_subscription_payload(request: web.Request, session: AsyncSession, user: User) -> Dict[str, Any]:
    settings = request.app["settings"]
    subscription_service = request.app["subscription_service"]
    panel_service = request.app["panel_service"]

    active_sub = await subscription_dal.get_active_subscription_by_user_id(session, user.user_id)
    active_details = await subscription_service.get_active_subscription_details(session, user.user_id)
    subscription = _serialize_subscription(active_sub, active_details) if active_sub or active_details else None
    if subscription and subscription.get("end_date"):
        try:
            end_dt = datetime.fromisoformat(subscription["end_date"])
            subscription["days_left"] = max(0, int(round((end_dt - datetime.now(timezone.utc)).total_seconds() / 86400)))
        except Exception:
            subscription["days_left"] = None

    payments_stmt = select(Payment).where(Payment.user_id == user.user_id, Payment.status == "succeeded").order_by(Payment.created_at.desc()).limit(30)
    payments_result = await session.execute(payments_stmt)
    payments = payments_result.scalars().all()

    referral_service = request.app["referral_service"]
    referral_stats = await referral_service.get_referral_stats(session, user.user_id)
    referral_link = await referral_service.generate_referral_link(session, request.app.get("bot_username") or "", user.user_id)
    has_had_any_subscription = await subscription_service.has_had_any_subscription(session, user.user_id)
    trial_available = bool(settings.TRIAL_ENABLED and not has_had_any_subscription)

    devices: list[Dict[str, Any]] = []
    if settings.MY_DEVICES_SECTION_ENABLED and subscription and subscription.get("user_id"):
        try:
            response = await panel_service.get_user_devices(subscription["user_id"])
            raw_devices: list[Dict[str, Any]] = []
            if isinstance(response, dict):
                maybe_list = response.get("devices")
                if isinstance(maybe_list, list):
                    raw_devices = maybe_list
            elif isinstance(response, list):
                raw_devices = response
            for idx, device in enumerate(raw_devices, start=1):
                devices.append(_serialize_device(device, index=idx))
        except Exception as exc:
            logging.error("Failed to load portal device list for user %s: %s", user.user_id, exc)

    plan_catalog = _build_plan_catalog(settings)
    provider_catalog = _build_provider_catalog(settings, stars_available=bool(any(plan.get("stars_enabled") for plan in plan_catalog["plans"])))
    payment_methods = await user_billing_dal.list_user_payment_methods(session, user.user_id)

    return {
        "user": _serialize_user(user),
        "subscription": subscription,
        "payment_methods": [_serialize_payment_method(method) for method in payment_methods],
        "payments": [_serialize_payment(payment) for payment in payments],
        "referral": {
            "stats": referral_stats,
            "link": referral_link,
            "bonus_inviter": settings.referral_bonus_inviter,
            "bonus_referee": settings.referral_bonus_referee,
            "welcome_bonus_days": settings.REFERRAL_WELCOME_BONUS_DAYS,
            "one_bonus_per_referee": bool(settings.REFERRAL_ONE_BONUS_PER_REFEREE),
        },
        "trial": {
            "enabled": bool(settings.TRIAL_ENABLED),
            "available": trial_available,
            "duration_days": settings.TRIAL_DURATION_DAYS,
            "traffic_limit_gb": settings.TRIAL_TRAFFIC_LIMIT_GB,
        },
        "devices": {
            "enabled": bool(settings.MY_DEVICES_SECTION_ENABLED),
            "items": devices,
            "count": len(devices),
            "max_devices": subscription.get("max_devices") if subscription else settings.USER_HWID_DEVICE_LIMIT,
        },
        "plans": {**plan_catalog, "providers": provider_catalog},
        "feature_flags": {
            "yookassa_autopayments_active": bool(settings.yookassa_autopayments_active),
            "my_devices_enabled": bool(settings.MY_DEVICES_SECTION_ENABLED),
            "trial_enabled": bool(settings.TRIAL_ENABLED),
            "traffic_sale_mode": bool(settings.traffic_sale_mode),
            "stars_enabled": bool(settings.STARS_ENABLED),
        },
        "links": {
            "support": settings.SUPPORT_LINK,
            "privacy_policy": settings.PRIVACY_POLICY_URL,
            "terms_of_service": settings.TERMS_OF_SERVICE_URL,
            "user_agreement": settings.USER_AGREEMENT_URL,
            "web_app": settings.WEB_APP_URL,
        },
    }


async def _request_email_code(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    settings = request.app["settings"]
    web_auth_service = request.app["web_auth_service"]
    email = str(payload.get("email") or "").strip()
    purpose = str(payload.get("purpose") or WEB_AUTH_EMAIL_PURPOSE).strip() or WEB_AUTH_EMAIL_PURPOSE
    language_code = _normalize_language(payload.get("language_code"), settings.DEFAULT_LANGUAGE)
    target_user_id = payload.get("target_user_id")

    auth_user, _ = await _get_authenticated_user(request, session)
    if purpose == "email_link":
        if not auth_user:
            return _json_error(401, "unauthorized", "Authentication is required to link an email.")
        target_user_id = auth_user.user_id

    try:
        result = await web_auth_service.request_email_code(
            session,
            email=email,
            target_user_id=int(target_user_id) if target_user_id is not None else None,
            language_code=language_code,
            request_ip=_extract_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
            purpose=purpose,
        )
    except PermissionError as exc:
        return _json_error(403, "forbidden", str(exc))
    except LookupError as exc:
        return _json_error(404, "not_found", str(exc))
    except Exception as exc:
        logging.error("Failed to request email code for %s: %s", email, exc, exc_info=True)
        return _json_error(500, "email_code_failed", "Failed to request the email code.")

    return _json_ok(
        {
            "purpose": purpose,
            "email": email,
            "challenge_id": result.get("challenge_id"),
            "expires_at": _format_dt(result.get("expires_at")) if isinstance(result.get("expires_at"), datetime) else None,
            "cooldown_remaining": result.get("cooldown_remaining", 0),
            "resend_limited": bool(result.get("resend_limited")),
            "already_linked": bool(result.get("already_linked")),
        }
    )


async def _verify_email_code(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    settings = request.app["settings"]
    web_auth_service = request.app["web_auth_service"]
    email = str(payload.get("email") or "").strip()
    code = str(payload.get("code") or "").strip()
    purpose = str(payload.get("purpose") or WEB_AUTH_EMAIL_PURPOSE).strip() or WEB_AUTH_EMAIL_PURPOSE
    language_code = _normalize_language(payload.get("language_code"), settings.DEFAULT_LANGUAGE)

    auth_user, _ = await _get_authenticated_user(request, session)
    if purpose == "email_link" and not auth_user:
        return _json_error(401, "unauthorized", "Authentication is required to link an email.")

    try:
        result = await web_auth_service.verify_email_code(
            session,
            email=email,
            code=code,
            language_code=language_code,
            request_ip=_extract_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
            purpose=purpose,
        )
    except PermissionError as exc:
        return _json_error(403, "invalid_code", str(exc))
    except LookupError as exc:
        return _json_error(404, "not_found", str(exc))
    except Exception as exc:
        logging.error("Failed to verify email code for %s: %s", email, exc, exc_info=True)
        return _json_error(500, "email_verify_failed", "Failed to verify the email code.")

    user = result.get("user")
    if not user:
        return _json_error(500, "email_verify_failed", "Failed to finalize the email verification.")
    if purpose == "email_link":
        return _json_ok({"purpose": purpose, "email_linked": True, "user": _serialize_user(user)})

    raw_token = result.get("raw_token")
    if not raw_token:
        return _json_error(500, "session_missing", "Web session token was not created.")
    return _json_ok(
        {
            "purpose": purpose,
            "session_token": raw_token,
            "user": _serialize_user(user),
            "session_expires_at": _format_dt(result["web_session"].expires_at) if result.get("web_session") else None,
        }
    )


async def _verify_telegram_code(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    settings = request.app["settings"]
    web_auth_service = request.app["web_auth_service"]
    code = str(payload.get("code") or "").strip()
    purpose = str(payload.get("purpose") or "web_login").strip() or "web_login"
    language_code = _normalize_language(payload.get("language_code"), settings.DEFAULT_LANGUAGE)
    telegram_user_id = payload.get("telegram_user_id")

    try:
        result = await web_auth_service.consume_telegram_code(
            session,
            code=code,
            purpose=purpose,  # type: ignore[arg-type]
            telegram_user_id=int(telegram_user_id) if telegram_user_id is not None else None,
            request_ip=_extract_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
        )
    except PermissionError as exc:
        return _json_error(403, "forbidden", str(exc))
    except LookupError as exc:
        return _json_error(404, "not_found", str(exc))
    except Exception as exc:
        logging.error("Failed to verify Telegram code: %s", exc, exc_info=True)
        return _json_error(500, "telegram_verify_failed", "Failed to verify the Telegram code.")

    if result.get("linked"):
        return _json_ok({"purpose": purpose, "linked": True, "user": _serialize_user(result["user"])})

    raw_token = result.get("raw_token")
    if not raw_token:
        return _json_error(500, "session_missing", "Web session token was not created.")
    return _json_ok(
        {
            "purpose": purpose,
            "session_token": raw_token,
            "user": _serialize_user(result["user"]),
            "session_expires_at": _format_dt(result["web_session"].expires_at) if result.get("web_session") else None,
            "language_code": language_code,
        }
    )


async def _request_telegram_link(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    settings = request.app["settings"]
    web_auth_service = request.app["web_auth_service"]
    user, _ = await _get_authenticated_user(request, session)
    if not user:
        return _json_error(401, "unauthorized", "Authentication is required to link Telegram.")

    try:
        result = await web_auth_service.request_telegram_code(
            session,
            user_id=user.user_id,
            purpose=WEB_AUTH_TELEGRAM_LINK_PURPOSE,  # type: ignore[arg-type]
            language_code=_normalize_language(payload.get("language_code"), user.language_code or settings.DEFAULT_LANGUAGE),
            request_ip=_extract_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
        )
    except PermissionError as exc:
        return _json_error(403, "forbidden", str(exc))
    except Exception as exc:
        logging.error("Failed to request Telegram link code for user %s: %s", user.user_id, exc, exc_info=True)
        return _json_error(500, "telegram_link_failed", "Failed to request the Telegram linking code.")

    if result.get("already_linked"):
        return _json_ok({"already_linked": True, "user": _serialize_user(result["user"])})
    return _json_ok(
        {
            "already_linked": False,
            "code": result.get("code"),
            "link_url": result.get("link_url"),
            "expires_at": _format_dt(result.get("expires_at")) if isinstance(result.get("expires_at"), datetime) else None,
            "user": _serialize_user(result["user"]),
        }
    )


async def _set_language(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    user, _ = await _get_authenticated_user(request, session)
    if not user:
        return _json_error(401, "unauthorized", "Authentication is required.")
    lang_code = str(payload.get("language_code") or "").strip().lower()
    if lang_code not in {"ru", "en"}:
        return _json_error(400, "invalid_language", "Unsupported language code.")
    await user_dal.update_user_language(session, user.user_id, lang_code)
    await session.commit()
    updated = await user_dal.get_user_by_id(session, user.user_id)
    return _json_ok({"user": _serialize_user(updated or user)})


async def _apply_promo(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    user, _ = await _get_authenticated_user(request, session)
    if not user:
        return _json_error(401, "unauthorized", "Authentication is required.")
    promo_code = str(payload.get("code") or "").strip()
    if not promo_code:
        return _json_error(400, "invalid_promo", "Promo code is required.")
    promo_code_service = request.app["promo_code_service"]
    settings = request.app["settings"]
    lang = _normalize_language(payload.get("language_code"), user.language_code or settings.DEFAULT_LANGUAGE)
    try:
        success, result = await promo_code_service.apply_promo_code(session, user.user_id, promo_code, lang)
        if not success:
            await session.rollback()
            return _json_error(400, "promo_failed", str(result))
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logging.error("Failed to apply promo code for user %s: %s", user.user_id, exc, exc_info=True)
        return _json_error(500, "promo_failed", "Failed to apply the promo code.")
    active = await request.app["subscription_service"].get_active_subscription_details(session, user.user_id)
    return _json_ok({"applied": True, "message": "Promo code applied successfully.", "subscription": active})


async def _activate_trial(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    user, _ = await _get_authenticated_user(request, session)
    if not user:
        return _json_error(401, "unauthorized", "Authentication is required.")
    subscription_service = request.app["subscription_service"]
    try:
        result = await subscription_service.activate_trial_subscription(session, user.user_id)
        if not result or not result.get("activated"):
            await session.rollback()
            return _json_error(400, "trial_failed", result.get("message_key", "trial_activation_failed") if isinstance(result, dict) else "trial_activation_failed")
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logging.error("Failed to activate trial for user %s: %s", user.user_id, exc, exc_info=True)
        return _json_error(500, "trial_failed", "Failed to activate the trial.")
    return _json_ok({"activated": True, "result": result})


async def _toggle_autorenew(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    user, _ = await _get_authenticated_user(request, session)
    if not user:
        return _json_error(401, "unauthorized", "Authentication is required.")
    enabled = bool(payload.get("enabled"))
    active_sub = await subscription_dal.get_active_subscription_by_user_id(session, user.user_id)
    if not active_sub:
        return _json_error(400, "subscription_missing", "No active subscription found.")
    if active_sub.provider != "yookassa":
        return _json_error(400, "provider_unsupported", "Auto-renew is available only for YooKassa subscriptions.")
    if enabled and not await user_billing_dal.user_has_saved_payment_method(session, user.user_id):
        return _json_error(400, "card_missing", "Link a payment card before enabling auto-renew.")
    await subscription_dal.update_subscription(session, active_sub.subscription_id, {"auto_renew_enabled": enabled})
    await session.commit()
    return _json_ok({"updated": True, "enabled": enabled})


async def _payment_methods_bind(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    user, _ = await _get_authenticated_user(request, session)
    if not user:
        return _json_error(401, "unauthorized", "Authentication is required.")
    settings = request.app["settings"]
    if not settings.yookassa_autopayments_active:
        return _json_error(400, "service_disabled", "YooKassa auto-payments are disabled.")
    yookassa_service = request.app["yookassa_service"]
    receipt_email = user.email or settings.YOOKASSA_DEFAULT_RECEIPT_EMAIL
    try:
        response = await yookassa_service.create_payment(
            amount=1.00,
            currency="RUB",
            description="Bind card",
            metadata={"user_id": str(user.user_id), "bind_only": "1"},
            receipt_email=receipt_email,
            save_payment_method=True,
            capture=False,
            bind_only=True,
        )
    except Exception as exc:
        logging.error("Failed to create YooKassa bind payment for user %s: %s", user.user_id, exc, exc_info=True)
        return _json_error(500, "bind_failed", "Failed to create the binding payment.")
    if not response or not response.get("confirmation_url"):
        return _json_error(502, "bind_failed", "Payment provider did not return a confirmation URL.")
    return _json_ok({"url": response["confirmation_url"], "payment": response, "message": "Open the payment link to bind the card."})


async def _payment_methods_set_default(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    user, _ = await _get_authenticated_user(request, session)
    if not user:
        return _json_error(401, "unauthorized", "Authentication is required.")
    method_id = payload.get("method_id")
    if method_id is None:
        return _json_error(400, "invalid_method", "Payment method id is required.")
    try:
        ok = await user_billing_dal.set_user_default_payment_method(session, user.user_id, int(method_id))
        if not ok:
            return _json_error(404, "method_not_found", "Payment method not found.")
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logging.error("Failed to set default payment method for user %s: %s", user.user_id, exc, exc_info=True)
        return _json_error(500, "method_update_failed", "Failed to update the payment method.")
    return _json_ok({"updated": True})


async def _payment_methods_delete(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    user, _ = await _get_authenticated_user(request, session)
    if not user:
        return _json_error(401, "unauthorized", "Authentication is required.")
    method_id = payload.get("method_id")
    provider_method_id = str(payload.get("provider_payment_method_id") or "").strip()
    if method_id is None and not provider_method_id:
        return _json_error(400, "invalid_method", "Payment method id is required.")
    try:
        deleted = False
        if method_id is not None:
            deleted = await user_billing_dal.delete_user_payment_method(session, user.user_id, int(method_id))
        elif provider_method_id:
            deleted = await user_billing_dal.delete_user_payment_method_by_provider_id(session, user.user_id, provider_method_id)
        if not deleted:
            return _json_error(404, "method_not_found", "Payment method not found.")
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logging.error("Failed to delete payment method for user %s: %s", user.user_id, exc, exc_info=True)
        return _json_error(500, "method_delete_failed", "Failed to delete the payment method.")
    return _json_ok({"deleted": True})


async def _disconnect_device(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    user, _ = await _get_authenticated_user(request, session)
    if not user:
        return _json_error(401, "unauthorized", "Authentication is required.")
    settings = request.app["settings"]
    if not settings.MY_DEVICES_SECTION_ENABLED:
        return _json_error(400, "devices_disabled", "Device management is disabled.")
    hwid_token = str(payload.get("hwid_token") or "").strip()
    if not hwid_token:
        return _json_error(400, "invalid_device", "Device token is required.")
    subscription_service = request.app["subscription_service"]
    panel_service = request.app["panel_service"]
    active = await subscription_service.get_active_subscription_details(session, user.user_id)
    if not active or not active.get("user_id"):
        return _json_error(400, "subscription_missing", "No active subscription found.")
    devices = await panel_service.get_user_devices(active["user_id"])
    raw_devices: list[Dict[str, Any]] = []
    if isinstance(devices, dict):
        maybe_list = devices.get("devices")
        if isinstance(maybe_list, list):
            raw_devices = maybe_list
    elif isinstance(devices, list):
        raw_devices = devices
    matched_hwid = None
    for device in raw_devices:
        if _device_token(device.get("hwid")) == hwid_token:
            matched_hwid = device.get("hwid")
            break
    if not matched_hwid:
        return _json_error(404, "device_not_found", "Device not found.")
    success = await panel_service.disconnect_device(active["user_id"], matched_hwid)
    if not success:
        return _json_error(500, "device_disconnect_failed", "Failed to disconnect the device.")
    await session.commit()
    return _json_ok({"disconnected": True})


async def _purchase_create(request: web.Request, session: AsyncSession, payload: Dict[str, Any]) -> web.Response:
    user, _ = await _get_authenticated_user(request, session)
    if not user:
        return _json_error(401, "unauthorized", "Authentication is required.")
    settings = request.app["settings"]
    provider = str(payload.get("provider") or "").strip().lower()
    units_raw = payload.get("units")
    sale_mode = "traffic" if settings.traffic_sale_mode else "subscription"
    if not provider:
        return _json_error(400, "invalid_provider", "Payment provider is required.")
    try:
        units = float(units_raw)
    except (TypeError, ValueError):
        return _json_error(400, "invalid_plan", "Plan units are invalid.")
    if sale_mode == "traffic":
        cash_price = settings.traffic_packages.get(units)
        stars_price = settings.stars_traffic_packages.get(units)
    else:
        cash_price = settings.subscription_options.get(int(units))
        stars_price = settings.stars_subscription_options.get(int(units))
    if provider == "stars":
        price = stars_price
        currency = "⭐"
    else:
        price = cash_price
        currency = settings.DEFAULT_CURRENCY_SYMBOL
    if price is None:
        return _json_error(400, "plan_unavailable", "Selected plan is not available for the chosen provider.")
    description = (
        f"Traffic package {_format_human_amount(units)} GB"
        if sale_mode == "traffic"
        else f"Subscription payment for {_format_human_amount(units)} months"
    )

    if provider == "yookassa":
        payment_payload = {
            "user_id": user.user_id,
            "amount": float(price),
            "currency": settings.DEFAULT_CURRENCY_SYMBOL,
            "status": "pending_yookassa",
            "description": description,
            "subscription_duration_months": int(units),
            "provider": "yookassa",
        }
        try:
            payment_record = await payment_dal.create_payment_record(session, payment_payload)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logging.error("Failed to create YooKassa payment record for user %s: %s", user.user_id, exc, exc_info=True)
            return _json_error(500, "payment_record_failed", "Failed to create the payment record.")
        yookassa_service = request.app["yookassa_service"]
        receipt_email = user.email or settings.YOOKASSA_DEFAULT_RECEIPT_EMAIL
        payment_method_id = payload.get("payment_method_id")
        payment_method_provider_id = str(payload.get("payment_method_provider_id") or "").strip() or None
        if payment_method_id is not None:
            try:
                resolved_id = int(payment_method_id)
                saved_methods = await user_billing_dal.list_user_payment_methods(session, user.user_id, provider="yookassa")
                selected_method = next((m for m in saved_methods if m.method_id == resolved_id), None)
                if selected_method:
                    payment_method_provider_id = selected_method.provider_payment_method_id
            except Exception:
                pass
        try:
            response = await yookassa_service.create_payment(
                amount=float(price),
                currency="RUB",
                description=description,
                metadata={
                    "user_id": str(user.user_id),
                    "subscription_months": str(int(units)),
                    "payment_db_id": str(payment_record.payment_id),
                    "sale_mode": sale_mode,
                },
                receipt_email=receipt_email,
                save_payment_method=bool(payload.get("save_payment_method") or settings.YOOKASSA_AUTOPAYMENTS_REQUIRE_CARD_BINDING),
                payment_method_id=payment_method_provider_id,
                capture=not bool(payment_method_provider_id),
            )
        except Exception as exc:
            logging.error("Failed to create YooKassa payment for user %s: %s", user.user_id, exc, exc_info=True)
            await payment_dal.update_payment_status_by_db_id(session, payment_record.payment_id, "failed_creation")
            await session.commit()
            return _json_error(500, "payment_gateway_failed", "Failed to create the payment.")
        if not response:
            await payment_dal.update_payment_status_by_db_id(session, payment_record.payment_id, "failed_creation")
            await session.commit()
            return _json_error(502, "payment_gateway_failed", "Payment provider did not return a response.")
        await payment_dal.update_payment_status_by_db_id(
            session,
            payment_record.payment_id,
            response.get("status", payment_record.status),
            yk_payment_id=response.get("id"),
        )
        await session.commit()
        if response.get("confirmation_url"):
            return _json_ok({"provider": provider, "kind": "redirect", "url": response["confirmation_url"], "payment": _serialize_payment((await payment_dal.get_payment_by_db_id(session, payment_record.payment_id)) or payment_record), "message": "Open the payment link to continue."})
        return _json_ok({"provider": provider, "kind": "charge_initiated", "payment": _serialize_payment((await payment_dal.get_payment_by_db_id(session, payment_record.payment_id)) or payment_record), "message": "Charge request initiated. Wait for confirmation."})

    if provider == "freekassa":
        payment_payload = {
            "user_id": user.user_id,
            "amount": float(price),
            "currency": settings.DEFAULT_CURRENCY_SYMBOL,
            "status": "pending_freekassa",
            "description": description,
            "subscription_duration_months": int(units),
            "provider": "freekassa",
        }
        try:
            payment_record = await payment_dal.create_payment_record(session, payment_payload)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logging.error("Failed to create FreeKassa payment record for user %s: %s", user.user_id, exc, exc_info=True)
            return _json_error(500, "payment_record_failed", "Failed to create the payment record.")
        freekassa_service = request.app["freekassa_service"]
        success, response_data = await freekassa_service.create_order(
            payment_db_id=payment_record.payment_id,
            user_id=user.user_id,
            months=units,
            amount=float(price),
            currency=settings.DEFAULT_CURRENCY_SYMBOL,
            email=user.email,
            payment_method_id=freekassa_service.payment_method_id,
            ip_address=freekassa_service.server_ip,
            extra_params={"us_method": freekassa_service.payment_method_id},
        )
        if not success:
            await payment_dal.update_payment_status_by_db_id(session, payment_record.payment_id, "failed_creation")
            await session.commit()
            return _json_error(502, "payment_gateway_failed", "FreeKassa did not create a payment link.")
        link = response_data.get("location") or response_data.get("url") or response_data.get("payment_url")
        provider_identifier = response_data.get("orderHash") or response_data.get("orderId") or response_data.get("id")
        if provider_identifier:
            await payment_dal.update_provider_payment_and_status(session, payment_record.payment_id, str(provider_identifier), payment_record.status)
            await session.commit()
        return _json_ok({"provider": provider, "kind": "redirect", "url": link, "payment": _serialize_payment((await payment_dal.get_payment_by_db_id(session, payment_record.payment_id)) or payment_record), "message": "Open the payment link to continue.", "raw_response": response_data})

    if provider == "platega":
        payment_payload = {
            "user_id": user.user_id,
            "amount": float(price),
            "currency": settings.DEFAULT_CURRENCY_SYMBOL,
            "status": "pending_platega",
            "description": description,
            "subscription_duration_months": int(units),
            "provider": "platega",
        }
        try:
            payment_record = await payment_dal.create_payment_record(session, payment_payload)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logging.error("Failed to create Platega payment record for user %s: %s", user.user_id, exc, exc_info=True)
            return _json_error(500, "payment_record_failed", "Failed to create the payment record.")
        platega_service = request.app["platega_service"]
        success, response_data = await platega_service.create_transaction(
            payment_db_id=payment_record.payment_id,
            user_id=user.user_id,
            months=units,
            amount=float(price),
            currency=settings.DEFAULT_CURRENCY_SYMBOL,
            description=description,
            payload=None,
        )
        if not success:
            await payment_dal.update_payment_status_by_db_id(session, payment_record.payment_id, "failed_creation")
            await session.commit()
            return _json_error(502, "payment_gateway_failed", "Platega did not create a payment link.")
        link = response_data.get("redirect") or response_data.get("url") or response_data.get("paymentUrl")
        provider_identifier = response_data.get("transactionId") or response_data.get("id")
        if provider_identifier:
            await payment_dal.update_provider_payment_and_status(session, payment_record.payment_id, str(provider_identifier), payment_record.status)
            await session.commit()
        return _json_ok({"provider": provider, "kind": "redirect", "url": link, "payment": _serialize_payment((await payment_dal.get_payment_by_db_id(session, payment_record.payment_id)) or payment_record), "message": "Open the payment link to continue.", "raw_response": response_data})

    if provider == "severpay":
        payment_payload = {
            "user_id": user.user_id,
            "amount": float(price),
            "currency": settings.DEFAULT_CURRENCY_SYMBOL,
            "status": "pending_severpay",
            "description": description,
            "subscription_duration_months": int(units),
            "provider": "severpay",
        }
        try:
            payment_record = await payment_dal.create_payment_record(session, payment_payload)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logging.error("Failed to create SeverPay payment record for user %s: %s", user.user_id, exc, exc_info=True)
            return _json_error(500, "payment_record_failed", "Failed to create the payment record.")
        severpay_service = request.app["severpay_service"]
        success, response_data = await severpay_service.create_payment(
            payment_db_id=payment_record.payment_id,
            user_id=user.user_id,
            months=units,
            amount=float(price),
            currency=settings.DEFAULT_CURRENCY_SYMBOL,
            description=description,
            email=user.email,
        )
        if not success:
            await payment_dal.update_payment_status_by_db_id(session, payment_record.payment_id, "failed_creation")
            await session.commit()
            return _json_error(502, "payment_gateway_failed", "SeverPay did not create a payment link.")
        link = response_data.get("url") or response_data.get("payment_url") or response_data.get("paymentUrl")
        provider_identifier = response_data.get("id") or response_data.get("uid")
        if provider_identifier:
            await payment_dal.update_provider_payment_and_status(session, payment_record.payment_id, str(provider_identifier), payment_record.status)
            await session.commit()
        return _json_ok({"provider": provider, "kind": "redirect", "url": link, "payment": _serialize_payment((await payment_dal.get_payment_by_db_id(session, payment_record.payment_id)) or payment_record), "message": "Open the payment link to continue.", "raw_response": response_data})

    if provider == "cryptopay":
        cryptopay_service = request.app["cryptopay_service"]
        invoice_url = await cryptopay_service.create_invoice(session=session, user_id=user.user_id, months=units, amount=float(price), description=description, sale_mode=sale_mode)
        if not invoice_url:
            return _json_error(502, "payment_gateway_failed", "CryptoPay did not create an invoice.")
        return _json_ok({"provider": provider, "kind": "redirect", "url": invoice_url, "message": "Open the CryptoPay invoice to continue."})

    if provider == "stars":
        if not user.telegram_user_id:
            return _json_error(400, "telegram_required", "Telegram must be linked before using Stars.")
        stars_service = request.app["stars_service"]
        payment_db_id = await stars_service.create_invoice(session=session, user_id=user.user_id, months=units, stars_price=int(price), description=description, sale_mode=sale_mode)
        if not payment_db_id:
            return _json_error(502, "payment_gateway_failed", "Stars invoice could not be created.")
        return _json_ok({"provider": provider, "kind": "telegram_invoice", "payment_db_id": payment_db_id, "message": "The invoice was sent to Telegram. Open Telegram to complete the payment."})

    return _json_error(400, "invalid_provider", "Unsupported payment provider.")


async def action_route(request: web.Request) -> web.Response:
    payload = await _extract_request_data(request)
    action = str(payload.get("action") or "").strip()
    if not action:
        return _json_error(400, "missing_action", "Action is required.")

    async_session_factory = request.app["async_session_factory"]
    async with async_session_factory() as session:
        if action == "auth.email.request":
            return await _request_email_code(request, session, payload)
        if action == "auth.email.verify":
            return await _verify_email_code(request, session, payload)
        if action == "auth.telegram.verify":
            return await _verify_telegram_code(request, session, payload)
        if action == "auth.telegram.request-link":
            return await _request_telegram_link(request, session, payload)
        if action == "auth.logout":
            user, _ = await _get_authenticated_user(request, session)
            if not user:
                return _json_error(401, "unauthorized", "Authentication is required.")
            token = _extract_session_token(request)
            if token:
                await request.app["web_auth_service"].revoke_web_session(session, raw_token=token)
            return _json_ok({"logged_out": True})
        if action == "profile.language.set":
            return await _set_language(request, session, payload)
        if action == "promo.apply":
            return await _apply_promo(request, session, payload)
        if action == "trial.activate":
            return await _activate_trial(request, session, payload)
        if action == "subscription.autorenew.set":
            return await _toggle_autorenew(request, session, payload)
        if action == "payment-methods.bind":
            return await _payment_methods_bind(request, session, payload)
        if action == "payment-methods.set-default":
            return await _payment_methods_set_default(request, session, payload)
        if action == "payment-methods.delete":
            return await _payment_methods_delete(request, session, payload)
        if action == "devices.disconnect":
            return await _disconnect_device(request, session, payload)
        if action == "purchase.create":
            return await _purchase_create(request, session, payload)

    return _json_error(400, "unknown_action", "Unknown action.")


async def bootstrap_route(request: web.Request) -> web.Response:
    settings = request.app["settings"]
    async_session_factory = request.app["async_session_factory"]
    async with async_session_factory() as session:
        user, web_session = await _get_authenticated_user(request, session)
        if not user or not web_session:
            return _json_ok(
                {
                    "authenticated": False,
                    "public": _build_public_config(
                        settings,
                        email_auth_enabled=request.app["web_auth_service"].mailer.configured,
                        bot_username=request.app.get("bot_username"),
                    ),
                    "server_time": _now_iso(),
                }
            )
        return _json_ok(
            {
                "authenticated": True,
                "public": _build_public_config(
                    settings,
                    email_auth_enabled=request.app["web_auth_service"].mailer.configured,
                    bot_username=request.app.get("bot_username"),
                ),
                "server_time": _now_iso(),
                "session": {
                    "expires_at": _format_dt(web_session.expires_at),
                    "auth_method": web_session.auth_method,
                    "last_seen_at": _format_dt(web_session.last_seen_at),
                },
                "user": _serialize_user(user),
            }
        )


async def dashboard_route(request: web.Request) -> web.Response:
    settings = request.app["settings"]
    async_session_factory = request.app["async_session_factory"]
    async with async_session_factory() as session:
        user, web_session = await _get_authenticated_user(request, session)
        if not user or not web_session:
            return _json_error(401, "unauthorized", "Authentication is required.")
        if user.is_banned:
            return _json_error(403, "user_banned", "Your account is banned.")
        dashboard = await _get_user_subscription_payload(request, session, user)
        return _json_ok(
            {
                "authenticated": True,
                "public": _build_public_config(
                    settings,
                    email_auth_enabled=request.app["web_auth_service"].mailer.configured,
                    bot_username=request.app.get("bot_username"),
                ),
                "server_time": _now_iso(),
                "session": {
                    "expires_at": _format_dt(web_session.expires_at),
                    "auth_method": web_session.auth_method,
                    "last_seen_at": _format_dt(web_session.last_seen_at),
                },
                "dashboard": dashboard,
            }
        )


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/web/bootstrap", bootstrap_route)
    app.router.add_get("/api/web/dashboard", dashboard_route)
    app.router.add_post("/api/web/action", action_route)
