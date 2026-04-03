from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Dict, Any

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import WebAuthChallenge, WebSession


async def get_web_auth_challenge(
    session: AsyncSession,
    challenge_id: int,
) -> Optional[WebAuthChallenge]:
    stmt = select(WebAuthChallenge).options(selectinload(WebAuthChallenge.user)).where(
        WebAuthChallenge.challenge_id == challenge_id
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_active_web_auth_challenge(
    session: AsyncSession,
    *,
    email: str,
    purpose: str,
) -> Optional[WebAuthChallenge]:
    now = datetime.now(timezone.utc)
    stmt = (
        select(WebAuthChallenge)
        .options(selectinload(WebAuthChallenge.user))
        .where(
            WebAuthChallenge.email == email.strip().lower(),
            WebAuthChallenge.purpose == purpose,
            WebAuthChallenge.consumed_at.is_(None),
            WebAuthChallenge.expires_at > now,
        )
        .order_by(WebAuthChallenge.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def invalidate_active_web_auth_challenges(
    session: AsyncSession,
    *,
    email: str,
    purpose: str,
) -> int:
    now = datetime.now(timezone.utc)
    stmt = (
        update(WebAuthChallenge)
        .where(
            WebAuthChallenge.email == email.strip().lower(),
            WebAuthChallenge.purpose == purpose,
            WebAuthChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    result = await session.execute(stmt)
    return result.rowcount or 0


async def create_web_auth_challenge(
    session: AsyncSession,
    challenge_data: Dict[str, Any],
) -> WebAuthChallenge:
    challenge = WebAuthChallenge(**challenge_data)
    session.add(challenge)
    await session.flush()
    await session.refresh(challenge)
    return challenge


async def mark_web_auth_challenge_consumed(
    session: AsyncSession,
    challenge_id: int,
) -> bool:
    challenge = await get_web_auth_challenge(session, challenge_id)
    if not challenge:
        return False
    challenge.consumed_at = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(challenge)
    return True


async def increment_web_auth_challenge_attempts(
    session: AsyncSession,
    challenge_id: int,
) -> Optional[WebAuthChallenge]:
    challenge = await get_web_auth_challenge(session, challenge_id)
    if not challenge:
        return None
    challenge.attempts = (challenge.attempts or 0) + 1
    await session.flush()
    await session.refresh(challenge)
    return challenge


async def create_web_session(
    session: AsyncSession,
    *,
    user_id: int,
    token_hash: str,
    expires_at: datetime,
    auth_method: str = "email",
    request_ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> WebSession:
    web_session = WebSession(
        user_id=user_id,
        token_hash=token_hash,
        auth_method=auth_method,
        request_ip=request_ip,
        user_agent=user_agent,
        expires_at=expires_at,
    )
    session.add(web_session)
    await session.flush()
    await session.refresh(web_session)
    return web_session


async def get_web_session_by_token_hash(
    session: AsyncSession,
    token_hash: str,
) -> Optional[WebSession]:
    now = datetime.now(timezone.utc)
    stmt = (
        select(WebSession)
        .options(selectinload(WebSession.user))
        .where(
            WebSession.token_hash == token_hash,
            WebSession.revoked_at.is_(None),
            WebSession.expires_at > now,
        )
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def touch_web_session(
    session: AsyncSession,
    session_id: int,
) -> Optional[WebSession]:
    web_session = await session.get(WebSession, session_id)
    if not web_session:
        return None
    web_session.last_seen_at = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(web_session)
    return web_session


async def revoke_web_session_by_token_hash(
    session: AsyncSession,
    token_hash: str,
) -> bool:
    stmt = select(WebSession).where(
        WebSession.token_hash == token_hash,
        WebSession.revoked_at.is_(None),
    ).limit(1)
    result = await session.execute(stmt)
    web_session = result.scalar_one_or_none()
    if not web_session:
        return False
    web_session.revoked_at = datetime.now(timezone.utc)
    await session.flush()
    await session.refresh(web_session)
    return True


async def revoke_all_user_web_sessions(
    session: AsyncSession,
    user_id: int,
) -> int:
    now = datetime.now(timezone.utc)
    stmt = (
        update(WebSession)
        .where(WebSession.user_id == user_id, WebSession.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    result = await session.execute(stmt)
    return result.rowcount or 0
