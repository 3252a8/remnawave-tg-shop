import logging
import secrets
import string
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy import update, delete, func, and_, or_, desc, text
from sqlalchemy.orm import aliased
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ..models import (
    User,
    Subscription,
    Payment,
    PromoCodeActivation,
    MessageLog,
    UserBilling,
    UserPaymentMethod,
    AdAttribution,
)

REFERRAL_CODE_ALPHABET = string.ascii_uppercase + string.digits
REFERRAL_CODE_LENGTH = 9
MAX_REFERRAL_CODE_ATTEMPTS = 25


def _normalize_email(email: Optional[str]) -> Optional[str]:
    if not email:
        return None
    normalized = email.strip().lower()
    return normalized or None


def _generate_referral_code_candidate() -> str:
    return "".join(
        secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(REFERRAL_CODE_LENGTH)
    )


async def _referral_code_exists(session: AsyncSession, code: str) -> bool:
    stmt = select(User.user_id).where(User.referral_code == code)
    result = await session.execute(stmt)
    return result.scalar_one_or_none() is not None


async def generate_unique_referral_code(session: AsyncSession) -> str:
    """
    Generate a unique referral code consisting of uppercase alphanumeric characters.
    Retries until a free code is found or raises RuntimeError after exceeding attempts.
    """
    for _ in range(MAX_REFERRAL_CODE_ATTEMPTS):
        candidate = _generate_referral_code_candidate()
        if not await _referral_code_exists(session, candidate):
            return candidate
    raise RuntimeError("Failed to generate a unique referral code after several attempts.")


async def ensure_referral_code(session: AsyncSession, user: User) -> str:
    """
    Ensure the provided user has a referral code, generating and persisting it if missing.
    Returns the existing or newly generated code.
    """
    if user.referral_code:
        normalized = user.referral_code.strip().upper()
        if normalized != user.referral_code:
            user.referral_code = normalized
            await session.flush()
            await session.refresh(user)
        return user.referral_code

    user.referral_code = await generate_unique_referral_code(session)
    await session.flush()
    await session.refresh(user)
    return user.referral_code


async def get_user_by_id(session: AsyncSession, user_id: int) -> Optional[User]:
    telegram_user = await get_user_by_telegram_id(session, user_id)
    if telegram_user:
        return telegram_user

    stmt = select(User).where(User.user_id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_telegram_id(
    session: AsyncSession, telegram_user_id: int
) -> Optional[User]:
    stmt = select(User).where(User.telegram_user_id == telegram_user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_email(
    session: AsyncSession, email: str
) -> Optional[User]:
    normalized = _normalize_email(email)
    if not normalized:
        return None
    stmt = select(User).where(func.lower(User.email) == normalized)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_telegram_link_code_hash(
    session: AsyncSession,
    code_hash: str,
    purpose: Optional[str] = None,
) -> Optional[User]:
    stmt = select(User).where(User.telegram_link_code_hash == code_hash)
    if purpose is not None:
        stmt = stmt.where(User.telegram_link_code_purpose == purpose)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_telegram_chat_id(
    session: AsyncSession,
    user_id: int,
) -> Optional[int]:
    user = await get_user_by_id(session, user_id)
    if not user:
        return None
    if user.telegram_user_id is not None and user.telegram_user_id > 0:
        return int(user.telegram_user_id)
    if user.user_id > 0 and user.telegram_user_id == user.user_id:
        return int(user.user_id)
    return None


async def reserve_web_user_id(session: AsyncSession) -> int:
    """Reserve a negative user_id for email-first accounts."""
    result = await session.execute(text("SELECT nextval('web_user_id_seq')"))
    value = result.scalar_one()
    return int(value)


async def get_user_by_username(session: AsyncSession, username: str) -> Optional[User]:
    clean_username = username.lstrip("@").lower()
    stmt = select(User).where(func.lower(User.username) == clean_username)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_panel_uuid(
    session: AsyncSession, panel_uuid: str
) -> Optional[User]:
    stmt = select(User).where(User.panel_user_uuid == panel_uuid)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


## Removed unused generic get_user helper to keep DAL explicit and simple


async def create_user(session: AsyncSession, user_data: Dict[str, Any]) -> Tuple[User, bool]:
    """Create a user if not exists in a race-safe way.

    Returns a tuple of (user, created_flag).
    """
    payload = dict(user_data)

    if "registration_date" not in payload:
        payload["registration_date"] = datetime.now(timezone.utc)

    payload["email"] = _normalize_email(payload.get("email"))

    if not payload.get("referral_code"):
        payload["referral_code"] = await generate_unique_referral_code(session)
    else:
        payload["referral_code"] = payload["referral_code"].strip().upper()

    explicit_user_id = payload.get("user_id")
    telegram_user_id = payload.get("telegram_user_id")

    if telegram_user_id is None and explicit_user_id is not None:
        telegram_user_id = explicit_user_id
        payload["telegram_user_id"] = explicit_user_id

    existing_user: Optional[User] = None
    if payload.get("email"):
        existing_user = await get_user_by_email(session, payload["email"])
    if not existing_user and telegram_user_id is not None:
        existing_user = await get_user_by_telegram_id(session, int(telegram_user_id))
    if not existing_user and explicit_user_id is not None:
        existing_user = await session.get(User, int(explicit_user_id))

    if existing_user:
        update_payload = {}
        for key, value in payload.items():
            if key in {"user_id", "registration_date", "referral_code"}:
                continue
            if value is None:
                continue
            if key == "email":
                normalized_email = _normalize_email(value)
                if normalized_email and (
                    existing_user.email is None
                    or _normalize_email(existing_user.email) == normalized_email
                ):
                    update_payload[key] = normalized_email
                continue
            if key == "telegram_user_id":
                if existing_user.telegram_user_id is None or existing_user.telegram_user_id == value:
                    update_payload[key] = value
                continue
            if getattr(existing_user, key, None) != value:
                update_payload[key] = value

        if update_payload:
            for key, value in update_payload.items():
                setattr(existing_user, key, value)

        if (
            payload.get("email")
            and existing_user.email is None
            and _normalize_email(payload["email"])
        ):
            existing_user.email = _normalize_email(payload["email"])
        if telegram_user_id is not None and existing_user.telegram_user_id is None:
            existing_user.telegram_user_id = int(telegram_user_id)
        if explicit_user_id is not None and existing_user.user_id != explicit_user_id:
            # Keep the canonical user id intact; this branch only applies when
            # a matching row already exists under a different identity.
            pass

        await session.flush()
        await session.refresh(existing_user)
        logging.info(
            "User %s already exists in DAL. Proceeding without creation.",
            existing_user.user_id,
        )
        return existing_user, False

    if explicit_user_id is None:
        payload["user_id"] = await reserve_web_user_id(session)
    else:
        payload["user_id"] = int(explicit_user_id)

    if payload.get("telegram_user_id") is None and payload["user_id"] > 0:
        payload["telegram_user_id"] = payload["user_id"]

    if payload.get("email") is not None:
        payload["email"] = _normalize_email(payload["email"])

    try:
        new_user = User(**payload)
        session.add(new_user)
        await session.flush()
        await session.refresh(new_user)
        logging.info(
            "New user %s created in DAL. Referred by: %s.",
            new_user.user_id,
            new_user.referred_by_id or "N/A",
        )
        return new_user, True
    except Exception as exc:
        logging.warning(
            "create_user failed for payload %s, retrying with lookup: %s",
            {k: v for k, v in payload.items() if k not in {"referral_code"}},
            exc,
        )
        await session.rollback()
        retry_user = None
        if payload.get("email"):
            retry_user = await get_user_by_email(session, payload["email"])
        if not retry_user and payload.get("telegram_user_id") is not None:
            retry_user = await get_user_by_telegram_id(
                session, int(payload["telegram_user_id"])
            )
        if not retry_user and payload.get("user_id") is not None:
            retry_user = await get_user_by_id(session, int(payload["user_id"]))
        if retry_user:
            return retry_user, False
        raise


async def get_user_by_referral_code(session: AsyncSession, referral_code: str) -> Optional[User]:
    normalized = referral_code.strip().upper()
    if not normalized:
        return None
    stmt = select(User).where(User.referral_code == normalized)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_user(
    session: AsyncSession, user_id: int, update_data: Dict[str, Any]
) -> Optional[User]:
    user = await get_user_by_id(session, user_id)
    if user:
        for key, value in update_data.items():
            if key == "email":
                value = _normalize_email(value)
            setattr(user, key, value)
        await session.flush()
        await session.refresh(user)
    return user


async def update_user_language(
    session: AsyncSession, user_id: int, lang_code: str
) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    stmt = update(User).where(User.user_id == user.user_id).values(language_code=lang_code)
    result = await session.execute(stmt)
    return result.rowcount > 0


async def set_user_email(
    session: AsyncSession,
    user_id: int,
    email: Optional[str],
) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    normalized = _normalize_email(email)
    user.email = normalized
    if normalized:
        user.email_verified_at = user.email_verified_at or datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(user)
    return True


async def set_user_telegram_link_code(
    session: AsyncSession,
    user_id: int,
    code_hash: Optional[str],
    expires_at: Optional[datetime],
    purpose: Optional[str] = None,
) -> bool:
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    user.telegram_link_code_hash = code_hash
    user.telegram_link_code_purpose = purpose
    user.telegram_link_code_expires_at = expires_at
    await session.flush()
    await session.refresh(user)
    return True


async def link_user_to_telegram_account(
    session: AsyncSession,
    user_id: int,
    telegram_user_id: int,
) -> Optional[User]:
    user = await get_user_by_id(session, user_id)
    if not user:
        return None

    other = await get_user_by_telegram_id(session, telegram_user_id)
    if other and other.user_id != user.user_id:
        merged = await merge_users(session, source_user_id=other.user_id, target_user_id=user.user_id)
        if merged:
            merged.telegram_link_code_hash = None
            merged.telegram_link_code_purpose = None
            merged.telegram_link_code_expires_at = None
            merged.telegram_linked_at = datetime.now(timezone.utc)
            await session.flush()
            await session.refresh(merged)
        return merged

    user.telegram_user_id = telegram_user_id
    user.telegram_linked_at = datetime.now(timezone.utc)
    if not user.email_verified_at and user.email:
        user.email_verified_at = datetime.now(timezone.utc)
    user.telegram_link_code_hash = None
    user.telegram_link_code_purpose = None
    user.telegram_link_code_expires_at = None
    await session.flush()
    await session.refresh(user)
    return user


async def merge_users(
    session: AsyncSession,
    *,
    source_user_id: int,
    target_user_id: int,
) -> Optional[User]:
    """Merge source user into target user and delete the source row.

    The target user becomes canonical. This is used when a Telegram-linked
    account already exists and the browser-side email account should become the
    primary record.
    """

    source = await get_user_by_id(session, source_user_id)
    target = await get_user_by_id(session, target_user_id)
    if not source or not target:
        return None
    if source.user_id == target.user_id:
        return target

    if source.panel_user_uuid and target.panel_user_uuid and source.panel_user_uuid != target.panel_user_uuid:
        raise ValueError("Cannot merge users with different panel_user_uuid values.")

    if not target.panel_user_uuid and source.panel_user_uuid:
        target.panel_user_uuid = source.panel_user_uuid
    if not target.referral_code and source.referral_code:
        target.referral_code = source.referral_code
    if target.referred_by_id is None and source.referred_by_id is not None:
        target.referred_by_id = source.referred_by_id
    if not target.email and source.email:
        target.email = source.email
    if not target.email_verified_at and source.email_verified_at:
        target.email_verified_at = source.email_verified_at
    if not target.telegram_user_id and source.telegram_user_id:
        target.telegram_user_id = source.telegram_user_id
    if not target.telegram_linked_at and source.telegram_linked_at:
        target.telegram_linked_at = source.telegram_linked_at
    if not target.telegram_link_code_hash and source.telegram_link_code_hash:
        target.telegram_link_code_hash = source.telegram_link_code_hash
    if not target.telegram_link_code_purpose and source.telegram_link_code_purpose:
        target.telegram_link_code_purpose = source.telegram_link_code_purpose
    if not target.telegram_link_code_expires_at and source.telegram_link_code_expires_at:
        target.telegram_link_code_expires_at = source.telegram_link_code_expires_at
    if not target.language_code and source.language_code:
        target.language_code = source.language_code
    if not target.username and source.username:
        target.username = source.username
    if not target.first_name and source.first_name:
        target.first_name = source.first_name
    if not target.last_name and source.last_name:
        target.last_name = source.last_name
    if target.lifetime_used_traffic_bytes is None and source.lifetime_used_traffic_bytes is not None:
        target.lifetime_used_traffic_bytes = source.lifetime_used_traffic_bytes
    if target.channel_subscription_verified is None and source.channel_subscription_verified is not None:
        target.channel_subscription_verified = source.channel_subscription_verified
    if target.channel_subscription_checked_at is None and source.channel_subscription_checked_at is not None:
        target.channel_subscription_checked_at = source.channel_subscription_checked_at
    if target.channel_subscription_verified_for is None and source.channel_subscription_verified_for is not None:
        target.channel_subscription_verified_for = source.channel_subscription_verified_for

    await session.execute(
        update(Subscription).where(Subscription.user_id == source.user_id).values(user_id=target.user_id)
    )
    await session.execute(
        update(Payment).where(Payment.user_id == source.user_id).values(user_id=target.user_id)
    )
    await session.execute(
        update(PromoCodeActivation).where(PromoCodeActivation.user_id == source.user_id).values(user_id=target.user_id)
    )
    await session.execute(
        update(MessageLog).where(MessageLog.user_id == source.user_id).values(user_id=target.user_id)
    )
    await session.execute(
        update(MessageLog).where(MessageLog.target_user_id == source.user_id).values(target_user_id=target.user_id)
    )
    await session.execute(
        update(UserBilling).where(UserBilling.user_id == source.user_id).values(user_id=target.user_id)
    )
    await session.execute(
        update(UserPaymentMethod).where(UserPaymentMethod.user_id == source.user_id).values(user_id=target.user_id)
    )
    await session.execute(
        update(AdAttribution).where(AdAttribution.user_id == source.user_id).values(user_id=target.user_id)
    )
    await session.execute(
        update(User).where(User.referred_by_id == source.user_id).values(referred_by_id=target.user_id)
    )

    await session.delete(source)
    await session.flush()
    await session.refresh(target)
    return target


async def get_banned_users(session: AsyncSession) -> List[User]:
    """Get all banned users"""
    stmt = (
        select(User)
        .where(User.is_banned == True)
        .order_by(User.registration_date.desc())
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_all_users_paginated(
    session: AsyncSession, *, page: int = 0, page_size: int = 15
) -> List[User]:
    """Return a slice of users ordered by newest registration first."""
    safe_page = max(page, 0)
    safe_page_size = max(page_size, 1)

    stmt = (
        select(User)
        .order_by(User.registration_date.desc())
        .offset(safe_page * safe_page_size)
        .limit(safe_page_size)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_all_users(session: AsyncSession) -> int:
    """Count total number of users."""
    result = await session.execute(select(func.count(User.user_id)))
    return result.scalar_one()


async def get_all_active_user_ids_for_broadcast(session: AsyncSession) -> List[int]:
    stmt = select(User.user_id).where(User.is_banned == False)
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_all_users_with_panel_uuid(session: AsyncSession) -> List[User]:
    stmt = select(User).where(User.panel_user_uuid.is_not(None))
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_enhanced_user_statistics(session: AsyncSession) -> Dict[str, Any]:
    """Get comprehensive user statistics including active users, trial users, etc."""
    from datetime import datetime, timezone
    
    # Use timezone-aware UTC to avoid naive/aware comparison issues in SQL queries
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Total users
    total_users_stmt = select(func.count(User.user_id))
    total_users = (await session.execute(total_users_stmt)).scalar() or 0
    
    # Banned users
    banned_users_stmt = select(func.count(User.user_id)).where(User.is_banned == True)
    banned_users = (await session.execute(banned_users_stmt)).scalar() or 0
    
    # Active users today (proxy: registered today)
    active_today_stmt = select(func.count(User.user_id)).where(User.registration_date >= today_start)
    active_today = (await session.execute(active_today_stmt)).scalar() or 0
    
    # Users with active paid subscriptions (non-trial providers only)
    paid_subs_stmt = (
        select(func.count(func.distinct(Subscription.user_id)))
        .join(User, Subscription.user_id == User.user_id)
        .where(
            and_(
                Subscription.is_active == True,
                Subscription.end_date > now,
                Subscription.provider.is_not(None)  # Not trial
            )
        )
    )
    paid_subs_users = (await session.execute(paid_subs_stmt)).scalar() or 0
    
    # Users on trial period
    trial_subs_stmt = (
        select(func.count(func.distinct(Subscription.user_id)))
        .join(User, Subscription.user_id == User.user_id)
        .where(
            and_(
                Subscription.is_active == True,
                Subscription.end_date > now,
                Subscription.provider.is_(None)  # Trial subscriptions
            )
        )
    )
    trial_users = (await session.execute(trial_subs_stmt)).scalar() or 0
    
    # Inactive users (no active subscription)
    inactive_users = total_users - paid_subs_users - trial_users - banned_users
    
    # Users attracted via referral
    referral_users_stmt = select(func.count(User.user_id)).where(User.referred_by_id.is_not(None))
    referral_users = (await session.execute(referral_users_stmt)).scalar() or 0
    
    return {
        "total_users": total_users,
        "banned_users": banned_users,
        "active_today": active_today,
        "paid_subscriptions": paid_subs_users,
        "trial_users": trial_users,
        "inactive_users": max(0, inactive_users),
        "referral_users": referral_users
    }


async def get_user_ids_with_active_subscription(session: AsyncSession) -> List[int]:
    """Return non-banned user IDs who have an active subscription (paid or trial)."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    stmt = (
        select(func.distinct(Subscription.user_id))
        .join(User, Subscription.user_id == User.user_id)
        .where(
            and_(
                User.is_banned == False,
                Subscription.is_active == True,
                Subscription.end_date > now,
            )
        )
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_user_ids_without_active_subscription(session: AsyncSession) -> List[int]:
    """Return non-banned user IDs who do NOT have any active subscription."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    # Subquery for users with active subscription
    active_subs_subq = (
        select(Subscription.user_id)
        .where(
            and_(
                Subscription.is_active == True,
                Subscription.end_date > now,
            )
        )
    ).scalar_subquery()

    stmt = (
        select(User.user_id)
        .where(
            and_(
                User.is_banned == False,
                ~User.user_id.in_(active_subs_subq),
            )
        )
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def delete_user_and_relations(session: AsyncSession, user_id: int) -> bool:
    """Completely remove a user and all dependent records from the database.

    This helper ensures we do not leave dangling foreign keys or orphaned data.
    """
    user = await get_user_by_id(session, user_id)
    if not user:
        return False
    actual_user_id = user.user_id

    # Ensure referral pointers do not block deletion
    await session.execute(update(User).where(User.referred_by_id == actual_user_id).values(referred_by_id=None))

    # Clean up dependent tables that do not cascade automatically
    await session.execute(
        delete(MessageLog).where(
            or_(MessageLog.user_id == actual_user_id, MessageLog.target_user_id == actual_user_id)
        )
    )
    await session.execute(delete(Payment).where(Payment.user_id == actual_user_id))
    await session.execute(
        delete(Subscription).where(Subscription.user_id == actual_user_id)
    )
    await session.execute(
        delete(PromoCodeActivation).where(PromoCodeActivation.user_id == actual_user_id)
    )
    await session.execute(
        delete(UserPaymentMethod).where(UserPaymentMethod.user_id == actual_user_id)
    )
    await session.execute(delete(UserBilling).where(UserBilling.user_id == actual_user_id))
    await session.execute(delete(AdAttribution).where(AdAttribution.user_id == actual_user_id))

    await session.delete(user)
    await session.flush()
    return True


async def get_top_users_by_traffic_used(
    session: AsyncSession,
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Return top users by total used traffic across all subscriptions."""
    safe_limit = max(1, limit)

    total_traffic_used = func.coalesce(func.sum(Subscription.traffic_used_bytes), 0)

    stmt = (
        select(
            User.user_id,
            User.username,
            User.first_name,
            total_traffic_used.label("traffic_used_bytes"),
        )
        .join(Subscription, Subscription.user_id == User.user_id, isouter=True)
        .group_by(User.user_id, User.username, User.first_name)
        .having(total_traffic_used > 0)
        .order_by(desc("traffic_used_bytes"), User.user_id.asc())
        .limit(safe_limit)
    )

    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result]


async def get_top_users_by_lifetime_traffic_used(
    session: AsyncSession,
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Return top users by lifetime used traffic from panel data."""
    safe_limit = max(1, limit)
    lifetime_used = func.coalesce(User.lifetime_used_traffic_bytes, 0)

    stmt = (
        select(
            User.user_id,
            User.username,
            User.first_name,
            lifetime_used.label("lifetime_used_traffic_bytes"),
        )
        .where(lifetime_used > 0)
        .order_by(desc("lifetime_used_traffic_bytes"), User.user_id.asc())
        .limit(safe_limit)
    )

    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result]


async def get_top_users_by_referrals_count(
    session: AsyncSession,
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Return top users by number of invited users."""
    safe_limit = max(1, limit)
    referred_user = aliased(User)

    invited_count = func.count(referred_user.user_id)

    stmt = (
        select(
            User.user_id,
            User.username,
            User.first_name,
            invited_count.label("invited_count"),
        )
        .join(referred_user, referred_user.referred_by_id == User.user_id, isouter=True)
        .group_by(User.user_id, User.username, User.first_name)
        .having(invited_count > 0)
        .order_by(desc("invited_count"), User.user_id.asc())
        .limit(safe_limit)
    )

    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result]


async def get_top_users_by_referral_revenue(
    session: AsyncSession,
    *,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Return top users by total revenue brought by all invited users."""
    safe_limit = max(1, limit)
    referred_user = aliased(User)

    referral_revenue = func.coalesce(func.sum(Payment.amount), 0.0)

    stmt = (
        select(
            User.user_id,
            User.username,
            User.first_name,
            referral_revenue.label("referral_revenue"),
        )
        .join(referred_user, referred_user.referred_by_id == User.user_id, isouter=True)
        .join(
            Payment,
            and_(
                Payment.user_id == referred_user.user_id,
                Payment.status == "succeeded",
            ),
            isouter=True,
        )
        .group_by(User.user_id, User.username, User.first_name)
        .having(referral_revenue > 0)
        .order_by(desc("referral_revenue"), User.user_id.asc())
        .limit(safe_limit)
    )

    result = await session.execute(stmt)
    return [dict(row._mapping) for row in result]
