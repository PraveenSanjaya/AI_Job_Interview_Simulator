import { useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '@/auth/AuthContext';
import { Alert, Button, Card, PageHeader, TextField } from '@/components/ui';
import { describeError } from '@/lib/errors';

const CONFIRM_WORD = 'DELETE';

export function AccountPage() {
  const { user, deleteAccount } = useAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState('');
  const [typed, setTyped] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const ready = password.length > 0 && typed === CONFIRM_WORD;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!ready) return;
    setError(null);
    setBusy(true);
    try {
      const filesRemoved = await deleteAccount(password);
      navigate('/login', {
        replace: true,
        state: { accountDeleted: true, filesPending: !filesRemoved },
      });
    } catch (e) {
      setError(describeError(e));
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader title="Account" description="Manage the account you use to sign in." />
      <div className="space-y-6">
        <Card title="Signed in as">
          <p className="text-sm text-slate-700">{user?.email}</p>
        </Card>

        <Card title="Delete account">
          <form onSubmit={(e) => void submit(e)} className="max-w-xl space-y-4" noValidate>
            <Alert tone="warning" title="This cannot be undone">
              <p>
                Deleting your account permanently removes your profile, uploaded resumes and their
                files, GitHub and portfolio connections and analyses, jobs and match reports, mock
                interviews with their answers, feedback and reports, and all of your sign-ins.
                Nothing is kept, and nobody else&apos;s data is affected. You can register again
                later with the same email, but you will start with an empty account.
              </p>
            </Alert>
            {error && <Alert tone="error">{error}</Alert>}
            <TextField
              label="Your password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              hint="Needed to confirm that it is really you."
            />
            <TextField
              label={`Type ${CONFIRM_WORD} to confirm`}
              autoComplete="off"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
            />
            <Button type="submit" variant="danger" disabled={!ready} loading={busy}>
              Delete my account permanently
            </Button>
          </form>
        </Card>
      </div>
    </>
  );
}
