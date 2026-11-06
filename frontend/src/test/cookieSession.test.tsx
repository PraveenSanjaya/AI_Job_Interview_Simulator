import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { refreshSession } from '@/lib/http';
import { tokens } from '@/lib/tokens';
import { clearSessionCookie, setSessionCookie } from './cookies';
import {
  api,
  emptyAccountDataHandlers,
  emptyAccountHandlers,
  renderApp,
  useHandlers,
  USER,
} from './utils';

const ISSUED = { access_token: 'access-1', token_type: 'bearer', expires_in: 1800 };

/** Everything either browser storage holds, as one string. */
function storageDump(): string {
  const dump: Record<string, string | null> = {};
  for (const store of [window.localStorage, window.sessionStorage]) {
    for (let i = 0; i < store.length; i += 1) {
      const key = store.key(i) as string;
      dump[key] = store.getItem(key);
    }
  }
  return JSON.stringify(dump);
}

function otherTab() {
  const channel = new BroadcastChannel('ajis-auth');
  return {
    send: (event: string) => channel.postMessage({ event, from: 'another-tab' }),
    close: () => channel.close(),
  };
}

describe('refresh token handling', () => {
  it('keeps every token out of localStorage and sessionStorage after signing in', async () => {
    useHandlers(
      http.post(api('/auth/login'), () => HttpResponse.json(ISSUED)),
      http.get(api('/auth/me'), () => HttpResponse.json(USER)),
      ...emptyAccountDataHandlers(),
    );
    renderApp('/login');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Email'), 'ada@example.com');
    await user.type(screen.getByLabelText('Password'), 'S3cure-passphrase-42');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('button', { name: /sign out/i })).toBeInTheDocument();
    expect(tokens.getAccess()).toBe('access-1'); // in memory
    expect(storageDump()).not.toMatch(/refresh|access-1/i);
  });

  it('removes a refresh token left in localStorage by an older version, and nothing else', async () => {
    window.localStorage.setItem('ajis.refresh_token', 'legacy-secret');
    window.localStorage.setItem('ajis.theme', 'dark');
    let refreshCalls = 0;
    useHandlers(
      http.post(api('/auth/refresh'), () => {
        refreshCalls += 1;
        return HttpResponse.json(ISSUED);
      }),
    );
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(window.localStorage.getItem('ajis.refresh_token')).toBeNull();
    expect(window.localStorage.getItem('ajis.theme')).toBe('dark'); // unrelated setting kept
    expect(refreshCalls).toBe(0); // the old token is never sent to the server
  });

  it('does not call the server on load when there is no session cookie', async () => {
    let refreshCalls = 0;
    useHandlers(
      http.post(api('/auth/refresh'), () => {
        refreshCalls += 1;
        return HttpResponse.json(ISSUED);
      }),
    );
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(refreshCalls).toBe(0);
  });

  it('restores the session after a reload from the cookie alone', async () => {
    setSessionCookie();
    useHandlers(
      http.post(api('/auth/refresh'), () => HttpResponse.json(ISSUED)),
      http.get(api('/auth/me'), ({ request }) => {
        expect(request.headers.get('authorization')).toBe('Bearer access-1');
        return HttpResponse.json(USER);
      }),
      ...emptyAccountDataHandlers(),
    );
    renderApp('/');
    expect(await screen.findByRole('button', { name: /sign out/i })).toBeInTheDocument();
    expect(storageDump()).not.toMatch(/access-1/);
  });

  it('sends protected routes to the sign-in page when signed out', async () => {
    renderApp('/jobs');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });
});

describe('refresh request', () => {
  it('has no body, echoes the CSRF cookie in the header and never sends a bearer token', async () => {
    setSessionCookie('csrf-xyz');
    tokens.set('stale-access');
    let seen: { csrf: string | null; body: string; auth: string | null } | null = null;
    useHandlers(
      http.post(api('/auth/refresh'), async ({ request }) => {
        seen = {
          csrf: request.headers.get('x-csrf-token'),
          body: await request.text(),
          auth: request.headers.get('authorization'),
        };
        return HttpResponse.json(ISSUED);
      }),
    );
    expect(await refreshSession()).toBe('access-1');
    expect(seen).toEqual({ csrf: 'csrf-xyz', body: '', auth: null });
  });

  it('shares one request between concurrent callers in a tab', async () => {
    setSessionCookie();
    let calls = 0;
    useHandlers(
      http.post(api('/auth/refresh'), async () => {
        calls += 1;
        await new Promise((resolve) => setTimeout(resolve, 20));
        return HttpResponse.json(ISSUED);
      }),
    );
    const results = await Promise.all([refreshSession(), refreshSession(), refreshSession()]);
    expect(results).toEqual(['access-1', 'access-1', 'access-1']);
    expect(calls).toBe(1);
  });

  it('is serialised across tabs with Web Locks when the browser has them', async () => {
    setSessionCookie();
    const request = vi.fn((_name: string, task: () => Promise<unknown>) => task());
    Object.defineProperty(navigator, 'locks', { value: { request }, configurable: true });
    try {
      useHandlers(http.post(api('/auth/refresh'), () => HttpResponse.json(ISSUED)));
      await refreshSession();
      expect(request).toHaveBeenCalledOnce();
      expect(request.mock.calls[0]?.[0]).toBe('ajis-refresh');
    } finally {
      Reflect.deleteProperty(navigator, 'locks');
    }
  });

  it('falls back to a short lease in localStorage without Web Locks', async () => {
    setSessionCookie();
    let leaseDuringRequest: string | null = null;
    useHandlers(
      http.post(api('/auth/refresh'), () => {
        leaseDuringRequest = window.localStorage.getItem('ajis.refresh_lease');
        return HttpResponse.json(ISSUED);
      }),
    );
    await refreshSession();
    expect(leaseDuringRequest).not.toBeNull();
    expect(leaseDuringRequest).not.toMatch(/access|refresh-token|csrf/i); // no secrets in it
    expect(window.localStorage.getItem('ajis.refresh_lease')).toBeNull(); // released
  });

  it('waits for another tab that holds the lease', async () => {
    setSessionCookie();
    window.localStorage.setItem(
      'ajis.refresh_lease',
      JSON.stringify({ owner: 'another-tab', until: Date.now() + 250 }),
    );
    const started = Date.now();
    let requestedAt = 0;
    useHandlers(
      http.post(api('/auth/refresh'), () => {
        requestedAt = Date.now();
        return HttpResponse.json(ISSUED);
      }),
    );
    await refreshSession();
    expect(requestedAt - started).toBeGreaterThanOrEqual(200);
  });

  it('ends in a signed-out state, with no retry loop, when the refresh is refused', async () => {
    setSessionCookie();
    let calls = 0;
    useHandlers(
      http.post(api('/auth/refresh'), () => {
        calls += 1;
        return HttpResponse.json(
          { error: { code: 'invalid_refresh_token', message: 'Revoked', request_id: 'r' } },
          { status: 401 },
        );
      }),
    );
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(tokens.getAccess()).toBeNull();
    expect(calls).toBe(1);
  });
});

describe('cross-tab behaviour', () => {
  it('signs this tab out when another tab signs out', async () => {
    useHandlers(...emptyAccountHandlers());
    renderApp('/');
    expect(await screen.findByRole('button', { name: /sign out/i })).toBeInTheDocument();
    const tab = otherTab();
    try {
      tab.send('logout');
      expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
      expect(tokens.getAccess()).toBeNull();
    } finally {
      tab.close();
    }
  });

  it('picks up the session when another tab signs in', async () => {
    useHandlers(...emptyAccountHandlers());
    clearSessionCookie();
    renderApp('/login');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    setSessionCookie(); // the other tab's sign-in set the shared cookies
    const tab = otherTab();
    try {
      tab.send('login');
      expect(await screen.findByRole('button', { name: /sign out/i })).toBeInTheDocument();
    } finally {
      tab.close();
    }
  });

  it('broadcasts only the event name when signing out, never a token', async () => {
    useHandlers(
      ...emptyAccountHandlers(),
      http.post(api('/auth/logout'), () => new HttpResponse(null, { status: 204 })),
    );
    const heard: unknown[] = [];
    const listener = new BroadcastChannel('ajis-auth');
    listener.onmessage = (message) => heard.push(message.data);
    try {
      renderApp('/');
      await userEvent.setup().click(await screen.findByRole('button', { name: /sign out/i }));
      await waitFor(() => expect(heard).toHaveLength(1));
      expect(heard[0]).toEqual({ event: 'logout', from: expect.any(String) });
      expect(JSON.stringify(heard)).not.toMatch(/access-1|token/i);
    } finally {
      listener.close();
    }
  });

  it('ignores malformed messages on the channel', async () => {
    useHandlers(...emptyAccountHandlers());
    renderApp('/');
    expect(await screen.findByRole('button', { name: /sign out/i })).toBeInTheDocument();
    const tab = otherTab();
    try {
      tab.send('something-else');
      await new Promise((resolve) => setTimeout(resolve, 50));
      expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
    } finally {
      tab.close();
    }
  });
});
