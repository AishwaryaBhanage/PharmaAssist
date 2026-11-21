import { API_BASE, refreshSession } from '@/api/client';
import { getAccessToken } from '@/api/token';

/**
 * Same-origin API links that the browser fetches without our Authorization header: a source page
 * opened in a new tab, a figure crop in an <img>. The API accepts the access token as
 * `?access_token=` on those two routes only, so it is appended at the moment of use (never stored
 * in the DOM, never for third-party URLs).
 */
export function isApiLink(href: string): boolean {
  return href.startsWith(`${API_BASE}/`);
}

export function authorizedHref(href: string, token: string | null = getAccessToken()): string {
  if (!isApiLink(href) || !token) return href;
  return `${href}${href.includes('?') ? '&' : '?'}access_token=${encodeURIComponent(token)}`;
}

function expiresWithin(token: string, seconds: number): boolean {
  try {
    const part = token.split('.')[1] ?? '';
    const payload = JSON.parse(atob(part.replace(/-/g, '+').replace(/_/g, '/'))) as {
      exp?: number;
    };
    return typeof payload.exp !== 'number' || payload.exp * 1000 - Date.now() < seconds * 1000;
  } catch {
    return true;
  }
}

/**
 * Open an API link in a new tab with a token good for at least a minute (refreshing first when it
 * is not). The tab is opened synchronously, inside the click, so popup blockers allow it, and is
 * pointed at the URL once the token is known.
 */
export async function openAuthorized(href: string): Promise<void> {
  if (!isApiLink(href)) {
    window.open(href, '_blank', 'noopener,noreferrer');
    return;
  }
  const tab = window.open('', '_blank');
  if (tab) tab.opener = null;
  let token = getAccessToken();
  if (!token || expiresWithin(token, 60)) {
    token = (await refreshSession())?.access_token ?? token;
  }
  const target = authorizedHref(href, token);
  if (tab) tab.location.replace(target);
  else window.open(target, '_blank');
}
