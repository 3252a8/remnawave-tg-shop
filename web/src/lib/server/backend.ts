import { env } from '$env/dynamic/private';
import type { Cookies, RequestEvent } from '@sveltejs/kit';

import { WEB_SESSION_HEADER } from '$lib/constants';

const DEFAULT_BACKEND_URL = 'http://remnawave-tg-shop:8080';

export class BackendError extends Error {
  status: number;
  payload: unknown;

  constructor(status: number, message: string, payload: unknown) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

export function getBackendBaseUrl(): string {
  return (env.WEB_API_URL || DEFAULT_BACKEND_URL).replace(/\/+$/, '');
}

export function getSessionCookieName(): string {
  return env.WEB_SESSION_COOKIE_NAME || 'remnawave_web_session';
}

function sessionCookieSecure(): boolean {
  const raw = (env.WEB_SESSION_COOKIE_SECURE || '').trim().toLowerCase();
  if (raw === 'false' || raw === '0') return false;
  return true;
}

function sessionCookieSameSite(): 'lax' | 'strict' | 'none' {
  const raw = (env.WEB_SESSION_COOKIE_SAMESITE || 'lax').trim().toLowerCase();
  if (raw === 'strict' || raw === 'none') return raw;
  return 'lax';
}

function sessionCookiePath(): string {
  return env.WEB_SESSION_COOKIE_PATH || '/';
}

function sessionCookieDomain(): string | undefined {
  const value = (env.WEB_SESSION_COOKIE_DOMAIN || '').trim();
  return value || undefined;
}

export function getSessionCookieOptions() {
  const maxAge = Number(env.WEB_SESSION_TTL_DAYS || '30') * 24 * 60 * 60;
  return {
    httpOnly: true,
    secure: sessionCookieSecure(),
    sameSite: sessionCookieSameSite(),
    path: sessionCookiePath(),
    domain: sessionCookieDomain(),
    maxAge: Number.isFinite(maxAge) && maxAge > 0 ? Math.floor(maxAge) : undefined,
  };
}

export function readSessionToken(cookies: Cookies): string | null {
  return cookies.get(getSessionCookieName()) || null;
}

export function writeSessionToken(cookies: Cookies, token: string): void {
  cookies.set(getSessionCookieName(), token, getSessionCookieOptions());
}

export function clearSessionToken(cookies: Cookies): void {
  cookies.delete(getSessionCookieName(), { path: sessionCookiePath(), domain: sessionCookieDomain() });
}

async function parseResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    const message =
      typeof payload === 'object' && payload && 'error' in payload
        ? String((payload as { error?: { message?: string } }).error?.message || `Backend error (${response.status})`)
        : `Backend error (${response.status})`;
    throw new BackendError(response.status, message, payload);
  }
  return payload as T;
}

export async function backendRequest<T>(
  event: RequestEvent,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const url = new URL(path, getBackendBaseUrl());
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const token = readSessionToken(event.cookies);
  if (token && !headers.has(WEB_SESSION_HEADER)) {
    headers.set(WEB_SESSION_HEADER, token);
  }
  const response = await fetch(url, { ...init, headers });
  return await parseResponse<T>(response);
}

export function backendGet<T>(event: RequestEvent, path: string): Promise<T> {
  return backendRequest<T>(event, path, { method: 'GET' });
}

export function backendAction<T>(event: RequestEvent, action: string, payload: Record<string, unknown>): Promise<T> {
  return backendRequest<T>(event, '/api/web/action', {
    method: 'POST',
    body: JSON.stringify({ action, ...payload }),
  });
}
