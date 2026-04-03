import type { PortalActionResponse } from '$lib/types';

export class PortalError extends Error {
  status: number;
  payload: unknown;

  constructor(status: number, message: string, payload: unknown) {
    super(message);
    this.status = status;
    this.payload = payload;
  }
}

function extractMessage(payload: unknown, fallback: string): string {
  if (payload && typeof payload === 'object') {
    const error = (payload as { error?: { message?: string } }).error;
    if (error?.message) {
      return String(error.message);
    }
  }
  return fallback;
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
    throw new PortalError(response.status, extractMessage(payload, `Portal error (${response.status})`), payload);
  }

  return payload as T;
}

export async function portalRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(path, {
    ...init,
    headers,
    credentials: 'include',
  });

  return await parseResponse<T>(response);
}

export async function portalAction<T = PortalActionResponse>(
  action: string,
  payload: Record<string, unknown> = {},
): Promise<T> {
  return await portalRequest<T>('/api/web/action', {
    method: 'POST',
    body: JSON.stringify({ action, ...payload }),
  });
}

export async function portalGet<T>(path: string): Promise<T> {
  return await portalRequest<T>(path, { method: 'GET' });
}
