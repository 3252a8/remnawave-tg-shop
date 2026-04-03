import logging
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, or_

from ..models import MessageLog, User


async def _resolve_user_account_id(session: AsyncSession, user_id: int) -> int:
    from .user_dal import get_user_by_id

    user = await get_user_by_id(session, user_id)
    return user.user_id if user else user_id


async def create_message_log(session: AsyncSession,
                             log_data: dict) -> Optional[MessageLog]:

    try:
        log_entry = await create_message_log_no_commit(session, log_data)
        await session.commit()
        await session.refresh(log_entry)
        return log_entry
    except Exception as e:
        await session.rollback()
        logging.error(f"Failed to create and commit message log: {e}",
                      exc_info=True)
        return None


async def get_all_message_logs(session: AsyncSession, limit: int,
                               offset: int) -> List[MessageLog]:
    stmt = select(MessageLog).order_by(
        MessageLog.timestamp.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_all_message_logs(session: AsyncSession) -> int:
    stmt = select(func.count()).select_from(MessageLog)
    result = await session.execute(stmt)
    return result.scalar_one()


async def get_user_message_logs(session: AsyncSession, user_id_to_search: int,
                                limit: int, offset: int) -> List[MessageLog]:
    user_id_to_search = await _resolve_user_account_id(session, user_id_to_search)
    stmt = (select(MessageLog).where(
        or_(MessageLog.user_id == user_id_to_search,
            MessageLog.target_user_id == user_id_to_search)).order_by(
                MessageLog.timestamp.desc()).limit(limit).offset(offset))
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_user_message_logs(session: AsyncSession,
                                  user_id_to_search: int) -> int:
    user_id_to_search = await _resolve_user_account_id(session, user_id_to_search)
    stmt = (select(func.count()).select_from(MessageLog).where(
        or_(MessageLog.user_id == user_id_to_search,
            MessageLog.target_user_id == user_id_to_search)))
    result = await session.execute(stmt)
    return result.scalar_one()


async def create_message_log_no_commit(session: AsyncSession,
                                       log_data: dict) -> MessageLog:

    if log_data.get("target_user_id"):
        from .user_dal import get_user_by_id
        target_user = await get_user_by_id(session, log_data["target_user_id"])
        if not target_user:
            logging.warning(
                f"Target user {log_data['target_user_id']} not found for message log. Setting to NULL."
            )
            log_data["target_user_id"] = None
        else:
            log_data["target_user_id"] = target_user.user_id

    if log_data.get("user_id"):
        resolved_user_id = await _resolve_user_account_id(session, log_data["user_id"])
        log_data["user_id"] = resolved_user_id

    new_log = MessageLog(**log_data)
    session.add(new_log)

    logging.debug(
        f"Message log added to session: user {log_data.get('user_id')}, event {log_data.get('event_type')}"
    )
    return new_log
