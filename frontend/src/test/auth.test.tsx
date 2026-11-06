import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { tokens } from '@/lib/tokens';
import { setSessionCookie } from './cookies';
import {
  api,
  emptyAccountDataHandlers,
  emptyAccountHandlers,
  errorBody,
  renderApp,
  useHandlers,
  USER,
} from './utils';

const PAIR = {
  access_token: 'access-1',
  token_type: 'bearer',
  expires_in: 1800,
};

describe('authentication flows', () => {
  it('sends signed-out visitors to the login page', async () => {
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('signs in, keeps the access token in memory and shows the app', async () => {
    useHandlers(
      http.post(api('/auth/login'), async ({ request }) => {
        expect(await request.json()).toEqual({
          email: 'ada@example.com',
          password: 'S3cure-passphrase-42',
        });
        return HttpResponse.json(PAIR);
      }),
      ...emptyAccountDataHandlers(),
      http.get(api('/auth/me'), ({ request }) => {
        expect(request.headers.get('authorization')).toBe('Bearer access-1');
        return HttpResponse.json(USER);
      }),
    );
    renderApp('/login');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Email'), 'ada@example.com');
    await user.type(screen.getByLabelText('Password'), 'S3cure-passphrase-42');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('button', { name: /sign out/i })).toBeInTheDocument();
    expect(tokens.getAccess()).toBe('access-1');
  });

  it('shows a clear message for wrong credentials and keeps the user on the form', async () => {
    useHandlers(
      http.post(api('/auth/login'), () =>
        errorBody('invalid_credentials', 'Invalid email or password', 401),
      ),
    );
    renderApp('/login');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Email'), 'ada@example.com');
    await user.type(screen.getByLabelText('Password'), 'wrong-password-1');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The email or password is incorrect.',
    );
    expect(tokens.getAccess()).toBeNull();
  });

  it('validates the login form before calling the server', async () => {
    renderApp('/login');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Enter your email')).toBeInTheDocument();
    expect(screen.getByText('Enter your password')).toBeInTheDocument();
  });

  it('shows rate limiting with the retry time', async () => {
    useHandlers(
      http.post(api('/auth/login'), () =>
        HttpResponse.json(
          { error: { code: 'rate_limited', message: 'Too many requests.', request_id: 'r' } },
          { status: 429, headers: { 'Retry-After': '30' } },
        ),
      ),
    );
    renderApp('/login');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Email'), 'ada@example.com');
    await user.type(screen.getByLabelText('Password'), 'whatever-123');
    await user.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Try again in 30 seconds');
  });

  it('enforces the password rules on registration', async () => {
    renderApp('/register');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Full name'), 'Ada Lovelace');
    await user.type(screen.getByLabelText('Email'), 'ada@example.com');
    await user.type(screen.getByLabelText('Password'), 'short1');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByText('Use at least 10 characters')).toBeInTheDocument();
    await user.clear(screen.getByLabelText('Password'));
    await user.type(screen.getByLabelText('Password'), 'onlyletterspassword');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByText('Include at least one digit')).toBeInTheDocument();
  });

  it('registers and then signs the new user in', async () => {
    const calls: string[] = [];
    useHandlers(
      http.post(api('/auth/register'), async ({ request }) => {
        calls.push('register');
        expect(await request.json()).toEqual({
          email: 'ada@example.com',
          password: 'S3cure-passphrase-42',
          full_name: 'Ada Lovelace',
        });
        return HttpResponse.json({ message: 'ok' }, { status: 202 });
      }),
      http.post(api('/auth/login'), () => {
        calls.push('login');
        return HttpResponse.json(PAIR);
      }),
      http.get(api('/auth/me'), () => HttpResponse.json(USER)),
      ...emptyAccountDataHandlers(),
    );
    renderApp('/register');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Full name'), 'Ada Lovelace');
    await user.type(screen.getByLabelText('Email'), 'ada@example.com');
    await user.type(screen.getByLabelText('Password'), 'S3cure-passphrase-42');
    await user.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByRole('button', { name: /sign out/i })).toBeInTheDocument();
    expect(calls).toEqual(['register', 'login']);
  });

  it('restores a session after a reload', async () => {
    useHandlers(...emptyAccountHandlers());
    renderApp('/');
    expect(await screen.findByRole('button', { name: /sign out/i })).toBeInTheDocument();
    expect(tokens.getAccess()).toBe('access-1');
  });

  it('falls back to the login page when the stored session is no longer valid', async () => {
    setSessionCookie('stale');
    useHandlers(
      http.post(api('/auth/refresh'), () =>
        errorBody('invalid_refresh_token', 'Invalid refresh token', 401),
      ),
    );
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(tokens.getAccess()).toBeNull();
  });

  it('signs out: revokes the session on the server and clears local state', async () => {
    let csrf: string | null = null;
    let bodyText = 'unset';
    useHandlers(
      ...emptyAccountHandlers(),
      http.post(api('/auth/logout'), async ({ request }) => {
        csrf = request.headers.get('x-csrf-token');
        bodyText = await request.text();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderApp('/');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: /sign out/i }));
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(csrf).toBe('csrf-1'); // the CSRF cookie is echoed in the header
    expect(bodyText).toBe(''); // the refresh token is in the HttpOnly cookie, not the body
    expect(tokens.getAccess()).toBeNull();
  });

  it('signs out locally even if the server cannot be reached', async () => {
    useHandlers(
      ...emptyAccountHandlers(),
      http.post(api('/auth/logout'), () => HttpResponse.error()),
    );
    renderApp('/');
    await userEvent.setup().click(await screen.findByRole('button', { name: /sign out/i }));
    await waitFor(() => expect(tokens.getAccess()).toBeNull());
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
  });

  it('redirects signed-in users away from the login page', async () => {
    useHandlers(...emptyAccountHandlers());
    renderApp('/login');
    expect(await screen.findByRole('button', { name: /sign out/i })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Sign in' })).not.toBeInTheDocument();
  });

  it('shows a not-found page inside the app for unknown routes', async () => {
    useHandlers(...emptyAccountHandlers());
    renderApp('/definitely/not/here');
    expect(await screen.findByText('Page not found')).toBeInTheDocument();
  });
});
