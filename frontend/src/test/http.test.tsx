import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http as mswHttp, HttpResponse } from 'msw';
import { useState } from 'react';
import { render } from '@testing-library/react';
import { ApiError, describeError, toApiError } from '@/lib/errors';
import { http, setSessionExpiredHandler } from '@/lib/http';
import { tokens } from '@/lib/tokens';
import { ConfirmDialog } from '@/components/ui';
import { api, errorBody, useHandlers } from './utils';

describe('HTTP client', () => {
  it('sends the bearer token', async () => {
    tokens.set('abc', 'r1');
    useHandlers(
      mswHttp.get(api('/ping'), ({ request }) =>
        HttpResponse.json({ auth: request.headers.get('authorization') }),
      ),
    );
    expect((await http.get('/ping')).data).toEqual({ auth: 'Bearer abc' });
  });

  it('refreshes an expired access token once and retries the request', async () => {
    tokens.set('expired', 'r1');
    let refreshes = 0;
    useHandlers(
      mswHttp.get(api('/data'), ({ request }) =>
        request.headers.get('authorization') === 'Bearer fresh'
          ? HttpResponse.json({ ok: true })
          : errorBody('unauthorized', 'Expired', 401),
      ),
      mswHttp.post(api('/auth/refresh'), () => {
        refreshes += 1;
        return HttpResponse.json({
          access_token: 'fresh',
          refresh_token: 'r2',
          token_type: 'bearer',
          expires_in: 1800,
        });
      }),
    );
    const [a, b] = await Promise.all([http.get('/data'), http.get('/data')]);
    expect(a.data).toEqual({ ok: true });
    expect(b.data).toEqual({ ok: true });
    expect(refreshes).toBe(1); // single-flight: refresh tokens are single-use
    expect(tokens.getRefresh()).toBe('r2');
  });

  it('ends the session when the refresh fails', async () => {
    tokens.set('expired', 'r1');
    const expired = vi.fn();
    setSessionExpiredHandler(expired);
    useHandlers(
      mswHttp.get(api('/data'), () => errorBody('unauthorized', 'Expired', 401)),
      mswHttp.post(api('/auth/refresh'), () => errorBody('invalid_refresh_token', 'Revoked', 401)),
    );
    await expect(http.get('/data')).rejects.toMatchObject({ status: 401 });
    expect(expired).toHaveBeenCalledOnce();
    expect(tokens.getRefresh()).toBeNull();
    setSessionExpiredHandler(() => undefined);
  });

  it('does not try to refresh failed sign-ins', async () => {
    let refreshes = 0;
    useHandlers(
      mswHttp.post(api('/auth/login'), () => errorBody('invalid_credentials', 'No', 401)),
      mswHttp.post(api('/auth/refresh'), () => {
        refreshes += 1;
        return HttpResponse.json({});
      }),
    );
    tokens.set('a', 'r');
    await expect(http.post('/auth/login', {})).rejects.toMatchObject({
      code: 'invalid_credentials',
    });
    expect(refreshes).toBe(0);
  });
});

describe('error handling', () => {
  it('normalises backend errors', async () => {
    useHandlers(
      mswHttp.get(api('/x'), () =>
        errorBody('validation_error', 'Request validation failed', 422, {
          details: [{ location: ['body', 'email'], message: 'bad address', type: 'x' }],
        }),
      ),
    );
    const error = (await http.get('/x').catch((e: unknown) => e)) as ApiError;
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(422);
    expect(error.requestId).toBe('req-1');
    expect(describeError(error)).toBe('email: bad address');
  });

  it('reports network failures in plain language', async () => {
    useHandlers(mswHttp.get(api('/x'), () => HttpResponse.error()));
    const error = (await http.get('/x').catch((e: unknown) => e)) as ApiError;
    expect(error.code).toBe('network_error');
    expect(describeError(error)).toContain('Cannot reach the server');
  });

  it('maps known codes to friendly text and falls back to the server message', () => {
    expect(
      describeError(new ApiError({ status: 403, code: 'ai_consent_required', message: 'x' })),
    ).toContain('consent');
    expect(
      describeError(
        new ApiError({ status: 409, code: 'something_else', message: 'Specific message' }),
      ),
    ).toBe('Specific message');
    expect(toApiError(new Error('boom')).code).toBe('unknown_error');
  });
});

describe('ConfirmDialog', () => {
  function Harness({ onConfirm }: { onConfirm: () => void }) {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>Delete thing</button>
        <ConfirmDialog
          open={open}
          title="Delete the thing?"
          message="This cannot be undone."
          onConfirm={onConfirm}
          onCancel={() => setOpen(false)}
        />
      </>
    );
  }

  it('asks before acting and can be cancelled with Escape', async () => {
    const onConfirm = vi.fn();
    render(<Harness onConfirm={onConfirm} />);
    const user = userEvent.setup();
    await user.click(screen.getByText('Delete thing'));
    expect(screen.getByRole('alertdialog', { name: 'Delete the thing?' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('runs the action only on confirmation', async () => {
    const onConfirm = vi.fn();
    render(<Harness onConfirm={onConfirm} />);
    const user = userEvent.setup();
    await user.click(screen.getByText('Delete thing'));
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });
});
