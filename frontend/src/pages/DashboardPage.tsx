import { CheckCircle2, Circle } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  useGithub,
  useInterviews,
  useJobs,
  usePortfolio,
  useProfile,
  useResumes,
} from '@/api/queries';
import type { InterviewSummary, Profile } from '@/api/types';
import {
  Alert,
  Badge,
  Button,
  Card,
  PageHeader,
  ProgressBar,
  QueryBoundary,
} from '@/components/ui';
import { formatDate, titleCase } from '@/lib/format';
import { ProgressCard, STATUS_TONE, TYPE_LABEL } from './InterviewsPages';
import { profileCompleteness } from './profileForm';

/** Everything on this page comes from the backend. Counts are real; nothing is a placeholder. */
export function DashboardPage() {
  const profile = useProfile();
  return (
    <>
      <PageHeader
        title={profile.data ? `Welcome, ${profile.data.full_name.split(' ')[0]}` : 'Dashboard'}
        description="Where you stand, and what to do next."
        actions={
          <Link to="/interviews/new">
            <Button>Start an interview</Button>
          </Link>
        }
      />
      <div className="space-y-6">
        <Stats />
        <div className="grid gap-6 lg:grid-cols-2">
          <ProfileCompleteness profile={profile} />
          <NextSteps profile={profile.data} />
        </div>
        <Progress />
        <div className="grid gap-6 lg:grid-cols-2">
          <RecentInterviews />
          <RecentJobs />
        </div>
      </div>
    </>
  );
}

function Stat({
  label,
  value,
  hint,
  to,
}: {
  label: string;
  value: ReactNode;
  hint?: string;
  to: string;
}) {
  return (
    <Link
      to={to}
      className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-slate-200 hover:ring-brand-500"
    >
      <p className="text-xs font-medium text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </Link>
  );
}

function Stats() {
  const jobs = useJobs();
  const resumes = useResumes();
  const interviews = useInterviews();
  const dash = (query: { isPending: boolean; isError: boolean }, value: ReactNode) =>
    query.isPending ? '…' : query.isError ? '—' : value;
  const completed = interviews.data?.filter((i) => i.status === 'completed').length ?? 0;
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Stat label="Saved jobs" to="/jobs" value={dash(jobs, jobs.data?.length)} />
      <Stat
        label="Resumes"
        to="/resumes"
        value={dash(resumes, resumes.data?.length)}
        hint={
          resumes.data ? `${resumes.data.filter((r) => r.has_analysis).length} analysed` : undefined
        }
      />
      <Stat
        label="Interviews"
        to="/interviews"
        value={dash(interviews, interviews.data?.length)}
        hint={interviews.data ? `${completed} completed` : undefined}
      />
      <Stat
        label="In progress"
        to="/interviews"
        value={dash(
          interviews,
          interviews.data?.filter((i) => i.status === 'in_progress' || i.status === 'interrupted')
            .length,
        )}
      />
    </div>
  );
}

function ProfileCompleteness({ profile }: { profile: ReturnType<typeof useProfile> }) {
  return (
    <Card title="Profile">
      <QueryBoundary query={profile} label="Loading your profile">
        {(data) => {
          const { done, total, missing } = profileCompleteness(data);
          return (
            <div className="space-y-3">
              <div className="flex justify-between text-sm text-slate-600">
                <span>
                  {done} of {total} sections filled in
                </span>
                <span>{Math.round((done / total) * 100)}%</span>
              </div>
              <ProgressBar value={done} max={total} label="Profile completeness" />
              {missing.length > 0 ? (
                <p className="text-sm text-slate-600">Still missing: {missing.join(', ')}.</p>
              ) : (
                <p className="text-sm text-slate-600">Your profile has every section.</p>
              )}
              <Link to="/profile" className="text-sm font-medium text-brand-700 hover:underline">
                Edit profile
              </Link>
            </div>
          );
        }}
      </QueryBoundary>
    </Card>
  );
}

function NextSteps({ profile }: { profile: Profile | undefined }) {
  const resumes = useResumes();
  const github = useGithub();
  const portfolio = usePortfolio();
  const jobs = useJobs();
  const interviews = useInterviews();
  const queries = [resumes, github, portfolio, jobs, interviews];
  const loading = !profile || queries.some((q) => q.isPending);
  const failed = queries.some((q) => q.isError);

  const steps = [
    {
      done: (profile?.skills.length ?? 0) > 0,
      label: 'Add your skills and experience',
      to: '/profile',
    },
    { done: (resumes.data?.length ?? 0) > 0, label: 'Upload your CV', to: '/resumes' },
    {
      done: Boolean(github.data) || Boolean(portfolio.data),
      label: 'Connect GitHub or a portfolio',
      to: '/connections',
    },
    {
      done: (jobs.data?.length ?? 0) > 0,
      label: 'Save a job you are interested in',
      to: '/jobs/new',
    },
    {
      done: (interviews.data?.length ?? 0) > 0,
      label: 'Practise your first interview',
      to: '/interviews/new',
    },
  ];
  const remaining = steps.filter((s) => !s.done);

  return (
    <Card title="Next steps">
      {loading ? (
        <p className="text-sm text-slate-500">Checking your progress…</p>
      ) : failed ? (
        <Alert tone="warning">
          Some data could not be loaded, so next steps may be incomplete.
        </Alert>
      ) : null}
      {!loading && (
        <ul className="space-y-2">
          {steps.map((step) => (
            <li key={step.label} className="flex items-center gap-2 text-sm">
              {step.done ? (
                <CheckCircle2 className="size-4 text-green-600" aria-label="Done" />
              ) : (
                <Circle className="size-4 text-slate-300" aria-label="To do" />
              )}
              {step.done ? (
                <span className="text-slate-500 line-through">{step.label}</span>
              ) : (
                <Link to={step.to} className="font-medium text-brand-700 hover:underline">
                  {step.label}
                </Link>
              )}
            </li>
          ))}
        </ul>
      )}
      {!loading && !failed && remaining.length === 0 && (
        <p className="mt-3 text-sm text-slate-600">
          You have set everything up. Keep practising to see your scores improve.
        </p>
      )}
    </Card>
  );
}

function Progress() {
  const interviews = useInterviews();
  if (interviews.isPending || interviews.isError || interviews.data.length === 0) return null;
  return <ProgressCard items={interviews.data} />;
}

function RecentInterviews() {
  const interviews = useInterviews();
  return (
    <Card
      title="Recent interviews"
      actions={
        <Link to="/interviews" className="text-sm text-brand-700 hover:underline">
          All
        </Link>
      }
    >
      <QueryBoundary query={interviews} label="Loading interviews">
        {(items: InterviewSummary[]) =>
          items.length === 0 ? (
            <p className="text-sm text-slate-600">You have not started an interview yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {items.slice(0, 3).map((i) => (
                <li key={i.id} className="flex items-center justify-between gap-2 py-2 text-sm">
                  <Link
                    to={
                      i.status === 'completed'
                        ? `/interviews/${i.id}/report`
                        : `/interviews/${i.id}`
                    }
                    className="min-w-0 truncate font-medium text-slate-900 hover:underline"
                  >
                    {i.interview_types.map((t) => TYPE_LABEL[t]).join(' + ')} ·{' '}
                    {titleCase(i.difficulty)}
                  </Link>
                  <span className="flex shrink-0 items-center gap-2 text-xs text-slate-500">
                    {formatDate(i.created_at)}
                    <Badge tone={STATUS_TONE[i.status]}>{titleCase(i.status)}</Badge>
                  </span>
                </li>
              ))}
            </ul>
          )
        }
      </QueryBoundary>
    </Card>
  );
}

function RecentJobs() {
  const jobs = useJobs();
  return (
    <Card
      title="Saved jobs"
      actions={
        <Link to="/jobs" className="text-sm text-brand-700 hover:underline">
          All
        </Link>
      }
    >
      <QueryBoundary query={jobs} label="Loading jobs">
        {(items) =>
          items.length === 0 ? (
            <p className="text-sm text-slate-600">No jobs saved yet.</p>
          ) : (
            <ul className="divide-y divide-slate-100">
              {items.slice(0, 3).map((job) => (
                <li key={job.id} className="py-2 text-sm">
                  <Link
                    to={`/jobs/${job.id}`}
                    className="font-medium text-slate-900 hover:underline"
                  >
                    {job.title}
                  </Link>
                  <span className="text-slate-500"> · {job.company ?? 'Company not given'}</span>
                </li>
              ))}
            </ul>
          )
        }
      </QueryBoundary>
    </Card>
  );
}
