import { getSessionCookieName, getSessionCookieOptions, getBackendBaseUrl } from '$lib/server/backend';
import { WEB_SESSION_HEADER } from '$lib/constants';
import type { RequestHandler } from './$types';

function proxyHeaders(event: Parameters<RequestHandler>[0]): Headers {
  const headers = new Headers(event.request.headers);
  headers.delete('cookie');
  headers.delete('host');
  headers.delete('content-length');
  headers.delete('connection');
  headers.delete('accept-encoding');
  headers.set(WEB_SESSION_HEADER, event.cookies.get(getSessionCookieName()) || '');
  headers.set('X-Forwarded-For', event.getClientAddress());
  headers.set('X-Forwarded-Proto', event.url.protocol.replace(':', ''));
  headers.set('X-Forwarded-Host', event.url.host);
  return headers;
}

async function forward(event: Parameters<RequestHandler>[0]) {
  const targetPath = event.params.path ? `/api/web/${event.params.path}` : '/api/web';
  const url = new URL(targetPath, getBackendBaseUrl());
  url.search = event.url.search;

  const headers = proxyHeaders(event);
  const method = event.request.method.toUpperCase();
  const body = method === 'GET' || method === 'HEAD' ? undefined : await event.request.arrayBuffer();

  const backendResponse = await fetch(url, {
    method,
    headers,
    body,
    redirect: 'manual',
  });

  const responseHeaders = new Headers(backendResponse.headers);
  responseHeaders.delete('content-length');
  responseHeaders.delete('transfer-encoding');

  const text = await backendResponse.text();
  const contentType = backendResponse.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    try {
      const payload = JSON.parse(text) as {
        ok?: boolean;
        session_token?: string;
        logged_out?: boolean;
      };
      const cookieName = getSessionCookieName();
      const cookieOptions = getSessionCookieOptions();
      if (payload?.session_token && payload.ok !== false) {
        event.cookies.set(cookieName, payload.session_token, cookieOptions);
      }
      if (payload?.logged_out) {
        event.cookies.delete(cookieName, {
          path: cookieOptions.path,
          domain: cookieOptions.domain,
        });
      }
    } catch {
      // Ignore non-JSON payloads.
    }
  }

  return new Response(text, {
    status: backendResponse.status,
    headers: responseHeaders,
  });
}

export const GET: RequestHandler = forward;
export const POST: RequestHandler = forward;
export const PUT: RequestHandler = forward;
export const PATCH: RequestHandler = forward;
export const DELETE: RequestHandler = forward;
export const OPTIONS: RequestHandler = forward;
