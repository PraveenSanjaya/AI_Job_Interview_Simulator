import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { tokens } from '@/lib/tokens';
import { api, errorBody, renderApp, signedInHandlers, useHandlers } from './utils';

async function fillForm(password: string, word: string) {
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText('Your password'), password);
  await user.type(screen.getByLabelText(/Type DELETE to confirm/), word);
  return user;
}

describe('account deletion', () => {
  it('keeps the button disabled until the password and the confirmation word are given', async () => {
    useHandlers(...signedInHandlers());
    renderApp('/account');
    const user = userEvent.setup();
    const button = await screen.findByRole('button', { name: 'Delete my account permanently' });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText('Your password'), 'S3cure-passphrase-42');
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText(/Type DELETE to confirm/), 'delete');
    expect(button).toBeDisabled(); // the word is case-sensitive
    await user.clear(screen.getByLabelText(/Type DELETE to confirm/));
    await user.type(screen.getByLabelText(/Type DELETE to confirm/), 'DELETE');
    expect(button).toBeEnabled();
  });

  it('explains what is deleted', async () => {
    useHandlers(...signedInHandlers());
    renderApp('/account');
    expect(await screen.findByText('This cannot be undone')).toBeInTheDocument();
    expect(screen.getByText(/uploaded resumes and their files/)).toBeInTheDocument();
  });

  it('sends the password, signs out and tells the user the data was removed', async () => {
    let sent: unknown;
    useHandlers(
      ...signedInHandlers(),
      http.post(api('/auth/delete-account'), async ({ request }) => {
        sent = await request.json();
        return HttpResponse.json({ deleted: true, stored_files_removed: true });
      }),
    );
    renderApp('/account');
    const user = await fillForm('S3cure-passphrase-42', 'DELETE');
    await user.click(screen.getByRole('button', { name: 'Delete my account permanently' }));
    expect(await screen.findByText('Your account was deleted')).toBeInTheDocument();
    expect(sent).toEqual({ password: 'S3cure-passphrase-42' });
    expect(
      screen.getByText(/All of your data and uploaded files were removed/),
    ).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(tokens.getAccess()).toBeNull();
  });

  it('reports honestly when some stored files could not be removed', async () => {
    useHandlers(
      ...signedInHandlers(),
      http.post(api('/auth/delete-account'), () =>
        HttpResponse.json({ deleted: true, stored_files_removed: false }),
      ),
    );
    renderApp('/account');
    const user = await fillForm('S3cure-passphrase-42', 'DELETE');
    await user.click(screen.getByRole('button', { name: 'Delete my account permanently' }));
    expect(await screen.findByText(/could not be deleted yet/)).toBeInTheDocument();
  });

  it('stays signed in and says nothing was deleted after a wrong password', async () => {
    useHandlers(
      ...signedInHandlers(),
      http.post(api('/auth/delete-account'), () =>
        errorBody('incorrect_password', 'The password is incorrect', 403),
      ),
    );
    renderApp('/account');
    const user = await fillForm('wrong-password-1', 'DELETE');
    await user.click(screen.getByRole('button', { name: 'Delete my account permanently' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Nothing was deleted');
    expect(screen.getByRole('heading', { name: 'Account' })).toBeInTheDocument();
    expect(tokens.getAccess()).not.toBeNull();
  });
});
