from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Dict, Literal, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import Settings
from db.dal import user_dal, web_auth_dal
from db.models import User, WebAuthChallenge, WebSession

WEB_AUTH_EMAIL_PURPOSE = "email_auth"
WEB_AUTH_WEB_LOGIN_PURPOSE = "web_login"
WEB_AUTH_TELEGRAM_LINK_PURPOSE = "telegram_link"

_EMAIL_CODE_LENGTH = 6
_TELEGRAM_CODE_LENGTH = 8
_MAX_EMAIL_CODE_ATTEMPTS = 5


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _generate_numeric_code(length: int) -> str:
    upper = 10**length
    return f"{secrets.randbelow(upper):0{length}d}"


def _hash_code(*, pepper: str, purpose: str, code: str, subject: Optional[str] = None) -> str:
    payload = f"{pepper}:{purpose}:{subject or ''}:{code}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class BrevoMailer:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.BREVO_SMTP_HOST
            and self.settings.BREVO_SMTP_PORT
            and self.settings.BREVO_SMTP_USERNAME
            and self.settings.BREVO_SMTP_PASSWORD
            and (self.settings.BREVO_FROM_EMAIL or self.settings.BREVO_SMTP_USERNAME)
        )

    async def send_message(
        self,
        *,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: Optional[str] = None,
    ) -> None:
        if not self.configured:
            raise RuntimeError("Brevo SMTP is not configured.")
        await asyncio.to_thread(
            self._send_message_sync,
            to_email,
            subject,
            text_body,
            html_body or text_body,
        )

    def _send_message_sync(
        self,
        to_email: str,
        subject: str,
        text_body: str,
        html_body: str,
    ) -> None:
        msg = EmailMessage()
        from_email = self.settings.BREVO_FROM_EMAIL or self.settings.BREVO_SMTP_USERNAME
        from_name = self.settings.BREVO_FROM_NAME or "Remnawave"
        msg["From"] = f"{from_name} <{from_email}>"
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(text_body)
        if html_body:
            msg.add_alternative(html_body, subtype="html")

        context = ssl.create_default_context()
        host = self.settings.BREVO_SMTP_HOST
        port = int(self.settings.BREVO_SMTP_PORT or 587)

        if self.settings.BREVO_SMTP_USE_SSL:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as smtp:
                smtp.login(self.settings.BREVO_SMTP_USERNAME, self.settings.BREVO_SMTP_PASSWORD)
                smtp.send_message(msg)
            return

        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.ehlo()
            if self.settings.BREVO_SMTP_USE_TLS:
                smtp.starttls(context=context)
                smtp.ehlo()
            smtp.login(self.settings.BREVO_SMTP_USERNAME, self.settings.BREVO_SMTP_PASSWORD)
            smtp.send_message(msg)


@dataclass(slots=True)
class WebAuthResult:
    user: User
    session: Optional[WebSession] = None
    raw_token: Optional[str] = None
    link_code: Optional[str] = None
    link_url: Optional[str] = None
    web_url: Optional[str] = None


class WebAuthService:
    def __init__(self, settings: Settings, bot_username: Optional[str] = None):
        self.settings = settings
        self.bot_username = bot_username
        self.mailer = BrevoMailer(settings)
        self._pepper = settings.BOT_TOKEN

    @property
    def email_auth_ttl(self) -> timedelta:
        return timedelta(minutes=max(1, int(self.settings.WEB_AUTH_CODE_TTL_MINUTES)))

    @property
    def web_session_ttl(self) -> timedelta:
        return timedelta(days=max(1, int(self.settings.WEB_SESSION_TTL_DAYS)))

    @property
    def telegram_code_ttl(self) -> timedelta:
        return timedelta(minutes=max(1, int(self.settings.WEB_TELEGRAM_LINK_CODE_TTL_MINUTES)))

    @property
    def resend_cooldown(self) -> timedelta:
        return timedelta(seconds=max(0, int(self.settings.WEB_AUTH_CODE_RESEND_COOLDOWN_SECONDS)))

    def _generate_email_code(self) -> str:
        return _generate_numeric_code(_EMAIL_CODE_LENGTH)

    def _generate_telegram_code(self) -> str:
        return _generate_numeric_code(_TELEGRAM_CODE_LENGTH)

    def _hash_email_code(self, email: str, code: str) -> str:
        return _hash_code(pepper=self._pepper, purpose=WEB_AUTH_EMAIL_PURPOSE, code=code, subject=email)

    def _hash_telegram_code(self, purpose: str, code: str) -> str:
        return _hash_code(pepper=self._pepper, purpose=purpose, code=code)

    @staticmethod
    def _is_ttl_expired(expires_at: Optional[datetime]) -> bool:
        return bool(expires_at and expires_at <= datetime.now(timezone.utc))

    async def _ensure_user_language(
        self,
        session: AsyncSession,
        user: User,
        language_code: Optional[str],
    ) -> User:
        normalized_lang = (language_code or "").strip().lower() or None
        if normalized_lang and not user.language_code:
            user.language_code = normalized_lang
            await session.flush()
            await session.refresh(user)
        return user

    async def _create_web_session(
        self,
        session: AsyncSession,
        *,
        user: User,
        auth_method: Literal["email", "telegram"] = "email",
        request_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Tuple[WebSession, str]:
        raw_token = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(timezone.utc) + self.web_session_ttl
        web_session = await web_auth_dal.create_web_session(
            session,
            user_id=user.user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            auth_method=auth_method,
            request_ip=request_ip,
            user_agent=user_agent,
        )
        return web_session, raw_token

    def _build_email_template(
        self,
        *,
        language_code: str,
        code: str,
        purpose: str,
        title: str,
        intro: str,
        cta: Optional[str] = None,
    ) -> tuple[str, str, str]:
        minutes = int(self.settings.WEB_AUTH_CODE_TTL_MINUTES)
        app_url = (self.settings.WEB_APP_URL or "").rstrip("/")
        subject = title

        if language_code.startswith("ru"):
            text_lines = [
                intro,
                "",
                f"Код: {code}",
                f"Действует: {minutes} мин.",
            ]
            if cta:
                text_lines.extend(["", cta])
            if app_url:
                text_lines.extend(["", f"Открыть портал: {app_url}"])
            text_body = "\n".join(text_lines)
            html_parts = [
                f"<p>{intro}</p>",
                f"<p><b>Код:</b> <code>{code}</code></p>",
                f"<p><b>Действует:</b> {minutes} мин.</p>",
            ]
            if cta:
                html_parts.append(f"<p>{cta}</p>")
            if app_url:
                html_parts.append(f'<p><a href="{app_url}">Открыть портал</a></p>')
            html_body = "".join(html_parts)
            return subject, text_body, html_body

        text_lines = [
            intro,
            "",
            f"Code: {code}",
            f"Valid for: {minutes} min.",
        ]
        if cta:
            text_lines.extend(["", cta])
        if app_url:
            text_lines.extend(["", f"Open portal: {app_url}"])
        text_body = "\n".join(text_lines)
        html_parts = [
            f"<p>{intro}</p>",
            f"<p><b>Code:</b> <code>{code}</code></p>",
            f"<p><b>Valid for:</b> {minutes} min.</p>",
        ]
        if cta:
            html_parts.append(f"<p>{cta}</p>")
        if app_url:
            html_parts.append(f'<p><a href="{app_url}">Open portal</a></p>')
        html_body = "".join(html_parts)
        return subject, text_body, html_body

    async def request_email_code(
        self,
        session: AsyncSession,
        *,
        email: str,
        target_user_id: Optional[int] = None,
        language_code: Optional[str] = None,
        request_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        purpose: str = WEB_AUTH_EMAIL_PURPOSE,
    ) -> Dict[str, Any]:
        if not self.mailer.configured:
            raise RuntimeError("Brevo SMTP is not configured.")

        normalized_email = _normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        if purpose == "email_link":
            if target_user_id is None:
                raise ValueError("Authenticated user is required to link an email.")
            user = await user_dal.get_user_by_id(session, target_user_id)
            if not user:
                raise LookupError("Target user not found.")
            if user.is_banned:
                raise PermissionError("User is banned.")
            if user.email and _normalize_email(user.email) == normalized_email:
                return {
                    "challenge_id": None,
                    "expires_at": None,
                    "cooldown_remaining": 0,
                    "resend_limited": False,
                    "already_linked": True,
                }
            existing_owner = await user_dal.get_user_by_email(session, normalized_email)
            if existing_owner and existing_owner.user_id != user.user_id:
                raise LookupError("Email is already linked to another account.")
            user = await self._ensure_user_language(session, user, language_code)
        else:
            user = await user_dal.get_user_by_email(session, normalized_email)
            if user:
                if user.is_banned:
                    raise PermissionError("User is banned.")
                user = await self._ensure_user_language(session, user, language_code)
            else:
                user, _ = await user_dal.create_user(
                    session,
                    {
                        "email": normalized_email,
                        "language_code": (language_code or self.settings.DEFAULT_LANGUAGE),
                    },
                )
        await session.commit()

        now = datetime.now(timezone.utc)
        existing = await web_auth_dal.get_active_web_auth_challenge(
            session,
            email=normalized_email,
            purpose=purpose,
        )
        if existing and existing.last_sent_at and now - existing.last_sent_at < self.resend_cooldown:
            cooldown_remaining = int(
                max(0, (self.resend_cooldown - (now - existing.last_sent_at)).total_seconds())
            )
            return {
                "challenge_id": existing.challenge_id,
                "expires_at": existing.expires_at,
                "cooldown_remaining": cooldown_remaining,
                "resend_limited": True,
            }

        await web_auth_dal.invalidate_active_web_auth_challenges(
            session,
            email=normalized_email,
            purpose=purpose,
        )

        code = self._generate_email_code()
        challenge = await web_auth_dal.create_web_auth_challenge(
            session,
            {
                "email": normalized_email,
                "purpose": purpose,
                "code_hash": self._hash_email_code(normalized_email, code),
                "user_id": user.user_id,
                "request_ip": request_ip,
                "user_agent": user_agent,
                "attempts": 0,
                "expires_at": now + self.email_auth_ttl,
            },
        )
        await session.commit()

        lang = (user.language_code or language_code or self.settings.DEFAULT_LANGUAGE).strip().lower()
        if purpose == WEB_AUTH_EMAIL_PURPOSE:
            title = "Код входа в веб-панель" if lang.startswith("ru") else "Web portal login code"
            intro = (
                "Используйте этот код для входа в веб-панель."
                if lang.startswith("ru")
                else "Use this code to sign in to the web portal."
            )
        elif purpose == "email_link":
            title = "Код привязки email" if lang.startswith("ru") else "Email linking code"
            intro = (
                "Используйте этот код, чтобы привязать email к аккаунту."
                if lang.startswith("ru")
                else "Use this code to attach this email address to your account."
            )
        else:
            title = "Код подтверждения" if lang.startswith("ru") else "Verification code"
            intro = (
                "Используйте этот код для подтверждения действия."
                if lang.startswith("ru")
                else "Use this code to confirm the action."
            )

        subject, text_body, html_body = self._build_email_template(
            language_code=lang,
            code=code,
            purpose=purpose,
            title=title,
            intro=intro,
        )
        await self.mailer.send_message(
            to_email=normalized_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

        return {
            "challenge_id": challenge.challenge_id,
            "expires_at": challenge.expires_at,
            "resend_limited": False,
        }

    async def verify_email_code(
        self,
        session: AsyncSession,
        *,
        email: str,
        code: str,
        language_code: Optional[str] = None,
        request_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        purpose: str = WEB_AUTH_EMAIL_PURPOSE,
    ) -> Dict[str, Any]:
        normalized_email = _normalize_email(email)
        if not normalized_email:
            raise ValueError("Email is required.")

        challenge = await web_auth_dal.get_active_web_auth_challenge(
            session,
            email=normalized_email,
            purpose=purpose,
        )
        if not challenge:
            raise LookupError("Code is invalid or expired.")

        if self._is_ttl_expired(challenge.expires_at):
            challenge.consumed_at = datetime.now(timezone.utc)
            await session.commit()
            raise LookupError("Code is invalid or expired.")

        expected_hash = self._hash_email_code(normalized_email, code.strip())
        if not hmac.compare_digest(expected_hash, challenge.code_hash):
            challenge = await web_auth_dal.increment_web_auth_challenge_attempts(
                session,
                challenge.challenge_id,
            )
            if challenge and (challenge.attempts or 0) >= _MAX_EMAIL_CODE_ATTEMPTS:
                challenge.consumed_at = datetime.now(timezone.utc)
            await session.commit()
            raise PermissionError("Invalid code.")

        challenge.consumed_at = datetime.now(timezone.utc)

        user = challenge.user or await user_dal.get_user_by_email(session, normalized_email)
        if not user:
            user, _ = await user_dal.create_user(
                session,
                {
                    "email": normalized_email,
                    "language_code": (language_code or self.settings.DEFAULT_LANGUAGE),
                },
            )
        if user.is_banned:
            await session.rollback()
            raise PermissionError("User is banned.")
        if purpose == "email_link":
            existing_owner = await user_dal.get_user_by_email(session, normalized_email)
            if existing_owner and existing_owner.user_id != user.user_id:
                await session.rollback()
                raise LookupError("Email is already linked to another account.")

            user.email = normalized_email
            user.email_verified_at = datetime.now(timezone.utc)
            await self._ensure_user_language(session, user, language_code)
            await session.commit()
            return {
                "user": user,
                "web_session": None,
                "raw_token": None,
                "email_linked": True,
            }

        user.email_verified_at = datetime.now(timezone.utc)
        await self._ensure_user_language(session, user, language_code)

        web_session, raw_token = await self._create_web_session(
            session,
            user=user,
            auth_method="email",
            request_ip=request_ip,
            user_agent=user_agent,
        )
        await session.commit()

        return {
            "user": user,
            "web_session": web_session,
            "raw_token": raw_token,
        }

    async def request_telegram_code(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        purpose: Literal["web_login", "telegram_link"],
        language_code: Optional[str] = None,
        request_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        user = await user_dal.get_user_by_id(session, user_id)
        if not user:
            user, _ = await user_dal.create_user(
                session,
                {
                    "user_id": user_id,
                    "telegram_user_id": user_id,
                    "language_code": language_code or self.settings.DEFAULT_LANGUAGE,
                },
            )
        if user.is_banned:
            raise PermissionError("User is banned.")
        if purpose == "telegram_link" and user.telegram_user_id is not None:
            return {
                "user": user,
                "code": None,
                "expires_at": None,
                "web_url": None,
                "link_url": None,
                "already_linked": True,
            }

        code = self._generate_telegram_code()
        code_hash = self._hash_telegram_code(purpose, code)
        expires_at = datetime.now(timezone.utc) + self.telegram_code_ttl
        await user_dal.set_user_telegram_link_code(
            session,
            user.user_id,
            code_hash,
            expires_at,
            purpose,
        )
        await session.commit()

        web_url = None
        link_url = None
        if purpose == "web_login" and self.settings.WEB_APP_URL:
            web_url = f"{self.settings.WEB_APP_URL.rstrip('/')}/?telegram_code={code}"
        if purpose == "telegram_link" and self.bot_username:
            link_url = f"https://t.me/{self.bot_username}?start=link_{code}"

        return {
            "user": user,
            "code": code,
            "expires_at": expires_at,
            "web_url": web_url,
            "link_url": link_url,
        }

    async def consume_telegram_code(
        self,
        session: AsyncSession,
        *,
        code: str,
        purpose: Literal["web_login", "telegram_link"],
        telegram_user_id: Optional[int] = None,
        request_ip: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        code_hash = self._hash_telegram_code(purpose, code.strip())
        user = await user_dal.get_user_by_telegram_link_code_hash(
            session,
            code_hash,
            purpose=purpose,
        )
        if not user or self._is_ttl_expired(user.telegram_link_code_expires_at):
            raise LookupError("Code is invalid or expired.")

        if purpose == "telegram_link":
            if telegram_user_id is None:
                raise ValueError("Telegram user id is required for link codes.")
            linked_user = await user_dal.link_user_to_telegram_account(
                session,
                user.user_id,
                telegram_user_id,
            )
            if not linked_user:
                await session.rollback()
                raise RuntimeError("Failed to link Telegram account.")
            await session.commit()
            return {
                "user": linked_user,
                "linked": True,
                "web_session": None,
                "raw_token": None,
            }

        web_session, raw_token = await self._create_web_session(
            session,
            user=user,
            auth_method="telegram",
            request_ip=request_ip,
            user_agent=user_agent,
        )
        await user_dal.set_user_telegram_link_code(session, user.user_id, None, None, None)
        await session.commit()
        return {
            "user": user,
            "linked": False,
            "web_session": web_session,
            "raw_token": raw_token,
        }

    async def authenticate_web_session(
        self,
        session: AsyncSession,
        *,
        raw_token: str,
    ) -> Optional[WebSession]:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        web_session = await web_auth_dal.get_web_session_by_token_hash(session, token_hash)
        if not web_session:
            return None
        if web_session.user and web_session.user.is_banned:
            await web_auth_dal.revoke_web_session_by_token_hash(session, token_hash)
            await session.commit()
            return None
        await web_auth_dal.touch_web_session(session, web_session.session_id)
        await session.commit()
        return web_session

    async def revoke_web_session(
        self,
        session: AsyncSession,
        *,
        raw_token: str,
    ) -> bool:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        result = await web_auth_dal.revoke_web_session_by_token_hash(session, token_hash)
        await session.commit()
        return result

    async def revoke_all_user_sessions(
        self,
        session: AsyncSession,
        *,
        user_id: int,
    ) -> int:
        result = await web_auth_dal.revoke_all_user_web_sessions(session, user_id)
        await session.commit()
        return result
