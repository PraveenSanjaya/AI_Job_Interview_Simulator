import { zodResolver } from '@hookform/resolvers/zod';
import { ExternalLink, Github, Globe } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { integrationApi } from '@/api/endpoints';
import { keys, useApiMutation, useGithub, usePortfolio } from '@/api/queries';
import type { GitHubSource, PortfolioSource } from '@/api/types';
import { IntegrationAnalysisCard } from '@/components/IntegrationAnalysisCard';
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  PageHeader,
  QueryBoundary,
  TextField,
} from '@/components/ui';
import { describeError } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';

export function ConnectionsPage() {
  return (
    <>
      <PageHeader
        title="Connections"
        description="Connect your public GitHub profile and portfolio website so job matches and interview questions can use real evidence. Only public pages are read. Connecting never changes your profile."
      />
      <div className="space-y-6">
        <GithubCard />
        <PortfolioCard />
        <IntegrationAnalysisCard />
      </div>
    </>
  );
}

function ConnectForm({
  label,
  placeholder,
  button,
  schema,
  field,
  onSubmit,
  hint,
}: {
  label: string;
  placeholder: string;
  button: string;
  schema: z.ZodString;
  field: string;
  onSubmit: (value: string) => Promise<void>;
  hint?: string;
}) {
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Record<string, string>>({ resolver: zodResolver(z.object({ [field]: schema })) });
  return (
    <form
      onSubmit={(e) => void handleSubmit((v) => onSubmit(v[field] ?? ''))(e)}
      noValidate
      className="flex flex-col gap-3 sm:flex-row sm:items-end"
    >
      <div className="flex-1">
        <TextField
          label={label}
          placeholder={placeholder}
          hint={hint}
          error={errors[field]?.message as string | undefined}
          {...register(field)}
        />
      </div>
      <Button type="submit" loading={isSubmitting}>
        {button}
      </Button>
    </form>
  );
}

function SourceCard({
  icon,
  title,
  connected,
  fetchedAt,
  children,
  actions,
}: {
  icon: ReactNode;
  title: string;
  connected: boolean;
  fetchedAt?: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          {icon}
          {title}
          <Badge tone={connected ? 'success' : 'neutral'}>
            {connected ? 'Connected' : 'Not connected'}
          </Badge>
        </span>
      }
      actions={actions}
    >
      {fetchedAt && (
        <p className="mb-3 text-xs text-slate-500">Last read {formatDateTime(fetchedAt)}</p>
      )}
      {children}
    </Card>
  );
}

// ------------------------------------------------------------------ GitHub

function GithubCard() {
  const query = useGithub();
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const connect = useApiMutation((u: string) => integrationApi.connectGithub(u), [keys.github]);
  const disconnect = useApiMutation(() => integrationApi.disconnectGithub(), [keys.github]);

  async function onConnect(username: string) {
    setError(null);
    try {
      await connect.mutateAsync(username);
    } catch (e) {
      setError(describeError(e));
    }
  }

  return (
    <QueryBoundary query={query} label="Loading GitHub connection">
      {(source) => (
        <SourceCard
          icon={<Github className="size-4" aria-hidden />}
          title="GitHub"
          connected={source !== null}
          fetchedAt={source?.fetched_at}
          actions={
            source && (
              <Button variant="secondary" onClick={() => setConfirm(true)}>
                Disconnect
              </Button>
            )
          }
        >
          {error && (
            <Alert tone="error" className="mb-3">
              {error}
            </Alert>
          )}
          {source ? (
            <GithubSummary source={source} />
          ) : (
            <p className="mb-3 text-sm text-slate-600">No GitHub profile connected yet.</p>
          )}
          <div className={source ? 'mt-4 border-t border-slate-100 pt-4' : ''}>
            <ConnectForm
              label={source ? 'Refresh or switch account' : 'GitHub username'}
              placeholder="octocat"
              button={source ? 'Refresh GitHub' : 'Connect GitHub'}
              field="username"
              schema={z.string().trim().min(1, 'Enter a GitHub username')}
              onSubmit={onConnect}
              hint="A username, @username or profile link. No GitHub login or permissions are needed."
            />
          </div>
          <ConfirmDialog
            open={confirm}
            title="Disconnect GitHub?"
            message="The stored GitHub data is deleted, together with any analyses built from it. Your profile and your repositories are not affected."
            confirmLabel="Disconnect"
            loading={disconnect.isPending}
            onCancel={() => setConfirm(false)}
            onConfirm={() => void disconnect.mutateAsync(undefined).then(() => setConfirm(false))}
          />
        </SourceCard>
      )}
    </QueryBoundary>
  );
}

function GithubSummary({ source }: { source: GitHubSource }) {
  const s = source.snapshot;
  const languages = Object.entries(s.language_distribution).sort((a, b) => b[1] - a[1]);
  const own = s.repositories.filter((r) => !r.is_fork).slice(0, 6);
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-700">
        <a
          href={s.profile_url}
          target="_blank"
          rel="noreferrer noopener"
          className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline"
        >
          {s.login} <ExternalLink className="size-3" aria-hidden />
        </a>
        {s.bio && <span className="text-slate-600"> · {s.bio}</span>}
      </p>
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {[
          ['Public repositories', s.public_repos_total],
          ['Read', s.repos_listed],
          ['Followers', s.followers],
          ['Active in the last year', s.activity.own_repos_pushed_last_365_days],
        ].map(([label, value]) => (
          <div key={label as string} className="rounded-lg bg-slate-50 p-3">
            <dt className="text-xs text-slate-500">{label}</dt>
            <dd className="text-lg font-semibold text-slate-900">{value}</dd>
          </div>
        ))}
      </dl>
      {languages.length > 0 && (
        <div>
          <p className="mb-1 text-xs font-medium text-slate-500">
            Languages (repositories per language label)
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {languages.map(([name, count]) => (
              <li key={name}>
                <Badge tone="brand">
                  {name} · {count}
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
      {own.length > 0 && (
        <ul className="divide-y divide-slate-100 text-sm">
          {own.map((repo) => (
            <li key={repo.name} className="py-2">
              <a
                href={repo.url}
                target="_blank"
                rel="noreferrer noopener"
                className="font-medium text-slate-900 hover:underline"
              >
                {repo.name}
              </a>
              {repo.primary_language && (
                <span className="ml-2 text-xs text-slate-500">{repo.primary_language}</span>
              )}
              {repo.description && <p className="text-slate-600">{repo.description}</p>}
            </li>
          ))}
        </ul>
      )}
      <p className="text-xs text-slate-500">{s.notice}</p>
    </div>
  );
}

// --------------------------------------------------------------- portfolio

function PortfolioCard() {
  const query = usePortfolio();
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const connect = useApiMutation(
    (u: string) => integrationApi.connectPortfolio(u),
    [keys.portfolio],
  );
  const disconnect = useApiMutation(() => integrationApi.disconnectPortfolio(), [keys.portfolio]);

  async function onConnect(url: string) {
    setError(null);
    try {
      await connect.mutateAsync(url);
    } catch (e) {
      setError(describeError(e));
    }
  }

  return (
    <QueryBoundary query={query} label="Loading portfolio connection">
      {(source) => (
        <SourceCard
          icon={<Globe className="size-4" aria-hidden />}
          title="Portfolio website"
          connected={source !== null}
          fetchedAt={source?.fetched_at}
          actions={
            source && (
              <Button variant="secondary" onClick={() => setConfirm(true)}>
                Disconnect
              </Button>
            )
          }
        >
          {error && (
            <Alert tone="error" className="mb-3">
              {error}
            </Alert>
          )}
          {source ? (
            <PortfolioSummary source={source} />
          ) : (
            <p className="mb-3 text-sm text-slate-600">No portfolio connected yet.</p>
          )}
          <div className={source ? 'mt-4 border-t border-slate-100 pt-4' : ''}>
            <ConnectForm
              label={source ? 'Refresh or change address' : 'Website address'}
              placeholder="https://yourname.dev"
              button={source ? 'Refresh website' : 'Connect website'}
              field="url"
              schema={z
                .string()
                .trim()
                .min(1, 'Enter your website address')
                .regex(/^https?:\/\/\S+$/i, 'Start with http:// or https://')}
              onSubmit={onConnect}
              hint="Public pages only. Internal and private addresses are refused, and no JavaScript is run."
            />
          </div>
          <ConfirmDialog
            open={confirm}
            title="Disconnect your portfolio?"
            message="The stored page text is deleted, together with any analyses built from it. Your website is not affected."
            confirmLabel="Disconnect"
            loading={disconnect.isPending}
            onCancel={() => setConfirm(false)}
            onConfirm={() => void disconnect.mutateAsync(undefined).then(() => setConfirm(false))}
          />
        </SourceCard>
      )}
    </QueryBoundary>
  );
}

function PortfolioSummary({ source }: { source: PortfolioSource }) {
  const s = source.snapshot;
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-700">
        {s.host} · {s.pages.length} page(s) read
      </p>
      <ul className="divide-y divide-slate-100 text-sm">
        {s.pages.map((page) => (
          <li key={page.url} className="py-2">
            <a
              href={page.url}
              target="_blank"
              rel="noreferrer noopener"
              className="font-medium text-slate-900 hover:underline"
            >
              {page.title ?? page.url}
            </a>
            {page.description && <p className="text-slate-600">{page.description}</p>}
            {page.text_truncated && (
              <p className="text-xs text-slate-500">Long page: only the first part was kept.</p>
            )}
          </li>
        ))}
      </ul>
      {s.skipped_pages.length > 0 && (
        <details className="text-xs text-slate-500">
          <summary className="cursor-pointer">{s.skipped_pages.length} page(s) skipped</summary>
          <ul className="mt-1 list-inside list-disc">
            {s.skipped_pages.map((p) => (
              <li key={p.url}>
                {p.url}: {p.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="text-xs text-slate-500">{s.notice}</p>
    </div>
  );
}
