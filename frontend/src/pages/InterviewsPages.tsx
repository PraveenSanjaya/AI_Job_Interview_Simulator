import { useQueries } from '@tanstack/react-query';
import { MessagesSquare, Plus } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { interviewApi } from '@/api/endpoints';
import { keys, useApiMutation, useInterviews, useJobs } from '@/api/queries';
import type {
  InterviewCreate,
  InterviewDifficulty,
  InterviewStatus,
  InterviewSummary,
  InterviewType,
} from '@/api/types';
import { ScoreTrendChart } from '@/components/charts';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  PageHeader,
  QueryBoundary,
  SelectField,
  TextField,
} from '@/components/ui';
import { describeError } from '@/lib/errors';
import { formatDate, titleCase } from '@/lib/format';

export const TYPE_LABEL: Record<InterviewType, string> = {
  hr: 'HR',
  behavioral: 'Behavioral',
  technical: 'Technical',
  programming: 'Programming and problem solving',
  project: 'Project-based',
  system_design: 'System design',
  job_specific: 'Job-specific',
};
const TYPE_HELP: Record<InterviewType, string> = {
  hr: 'Motivation, strengths and working style',
  behavioral: 'Past situations, answered in STAR form',
  technical: 'Concepts and practical knowledge',
  programming: 'Algorithms and coding approach',
  project: 'Your own projects and design decisions',
  system_design: 'Designing systems and trade-offs',
  job_specific: 'Built from the selected job (needs a job)',
};
export const STATUS_TONE: Record<
  InterviewStatus,
  'neutral' | 'brand' | 'success' | 'warning' | 'danger'
> = {
  created: 'neutral',
  in_progress: 'brand',
  completed: 'success',
  cancelled: 'neutral',
  interrupted: 'warning',
  expired: 'neutral',
};

// ------------------------------------------------------------------- history

export function InterviewsPage() {
  const interviews = useInterviews();
  return (
    <>
      <PageHeader
        title="Interviews"
        description="Practise with text interviews, review your reports and watch your progress over time."
        actions={
          <Link to="/interviews/new">
            <Button>
              <Plus className="size-4" aria-hidden /> New interview
            </Button>
          </Link>
        }
      />
      <QueryBoundary query={interviews} label="Loading your interviews">
        {(items) =>
          items.length === 0 ? (
            <EmptyState
              icon={<MessagesSquare className="size-5" aria-hidden />}
              title="No interviews yet"
              description="Choose a type and difficulty, optionally pick a job, and start practising. Your reports and progress will appear here."
              action={
                <Link to="/interviews/new">
                  <Button>Start your first interview</Button>
                </Link>
              }
            />
          ) : (
            <div className="space-y-6">
              <ProgressCard items={items} />
              <HistoryList items={items} />
            </div>
          )
        }
      </QueryBoundary>
    </>
  );
}

/** Scores come only from stored reports of completed interviews; nothing is estimated. */
function ProgressCard({ items }: { items: InterviewSummary[] }) {
  const completed = items.filter((i) => i.status === 'completed').slice(0, 12);
  const reports = useQueries({
    queries: completed.map((i) => ({
      queryKey: keys.report(i.id),
      queryFn: () => interviewApi.report(i.id),
    })),
  });
  const loading = reports.some((r) => r.isPending);
  const points = completed
    .map((interview, index) => ({
      label: formatDate(interview.completed_at ?? interview.created_at),
      score: reports[index]?.data?.overall_score ?? null,
    }))
    .filter((p): p is { label: string; score: number } => p.score !== null)
    .reverse();
  const average =
    points.length > 0
      ? Math.round(points.reduce((sum, p) => sum + p.score, 0) / points.length)
      : null;

  return (
    <Card title="Your progress">
      <dl className="mb-4 grid grid-cols-3 gap-3">
        {[
          ['Interviews', items.length],
          ['Completed', items.filter((i) => i.status === 'completed').length],
          ['Average score', average === null ? '—' : average],
        ].map(([label, value]) => (
          <div key={label as string} className="rounded-lg bg-slate-50 p-3">
            <dt className="text-xs text-slate-500">{label}</dt>
            <dd className="text-xl font-semibold text-slate-900">{value}</dd>
          </div>
        ))}
      </dl>
      {loading ? (
        <p className="text-sm text-slate-500">Loading scores…</p>
      ) : points.length === 0 ? (
        <p className="text-sm text-slate-600">
          No scored interviews yet. Scores appear after you complete an interview that was evaluated
          by AI.
        </p>
      ) : (
        <ScoreTrendChart
          points={points}
          caption="Overall score of each completed interview, oldest first"
        />
      )}
    </Card>
  );
}

function HistoryList({ items }: { items: InterviewSummary[] }) {
  return (
    <Card title="All interviews">
      <ul className="divide-y divide-slate-100">
        {items.map((i) => (
          <li
            key={i.id}
            className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
          >
            <div className="min-w-0">
              <p className="font-medium text-slate-900">
                {i.interview_types.map((t) => TYPE_LABEL[t]).join(' + ')}
              </p>
              <p className="text-sm text-slate-500">
                {titleCase(i.difficulty)}
                {i.job_title && ` · ${i.job_title}`} · {formatDate(i.created_at)}
                {i.mode === 'question_bank' && ' · question bank'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              <Badge tone={STATUS_TONE[i.status]}>{titleCase(i.status)}</Badge>
              {i.status === 'completed' ? (
                <Link
                  to={`/interviews/${i.id}/report`}
                  className="text-sm font-medium text-brand-700 hover:underline"
                >
                  View report
                </Link>
              ) : i.status === 'created' ||
                i.status === 'in_progress' ||
                i.status === 'interrupted' ? (
                <Link
                  to={`/interviews/${i.id}`}
                  className="text-sm font-medium text-brand-700 hover:underline"
                >
                  {i.status === 'created' ? 'Start' : 'Continue'}
                </Link>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

// ----------------------------------------------------------------------- new

const ALL_TYPES = Object.keys(TYPE_LABEL) as InterviewType[];

export function NewInterviewPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const jobs = useJobs();
  const [types, setTypes] = useState<InterviewType[]>(['technical']);
  const [difficulty, setDifficulty] = useState<InterviewDifficulty>('intermediate');
  const [count, setCount] = useState('10');
  const [jobId, setJobId] = useState(params.get('job') ?? '');
  const [followups, setFollowups] = useState('2');
  const [useAi, setUseAi] = useState(true);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const create = useApiMutation(
    (body: InterviewCreate) => interviewApi.create(body),
    [keys.interviews],
  );

  const toggle = (type: InterviewType) =>
    setTypes((current) =>
      current.includes(type) ? current.filter((t) => t !== type) : [...current, type],
    );

  const n = Number(count);
  const problems: string[] = [];
  if (types.length === 0) problems.push('Choose at least one interview type.');
  if (types.includes('job_specific') && !jobId)
    problems.push('Job-specific interviews need a job. Pick one below.');
  if (!Number.isInteger(n) || n < 1 || n > 30) problems.push('Choose between 1 and 30 questions.');
  else if (n < types.length) problems.push('Use at least one question per interview type.');

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (problems.length > 0) return;
    setError(null);
    try {
      const interview = await create.mutateAsync({
        interview_types: ALL_TYPES.filter((t) => types.includes(t)),
        difficulty,
        question_count: n,
        job_id: jobId || null,
        max_followups: Number(followups),
        use_ai: useAi,
        allow_external_ai: useAi && consent,
      });
      navigate(`/interviews/${interview.id}`);
    } catch (e) {
      setError(describeError(e));
    }
  }

  return (
    <>
      <PageHeader
        title="New interview"
        description="Questions are prepared when you start. You can combine types, for example Technical + HR."
      />
      <form onSubmit={(e) => void submit(e)} noValidate className="space-y-6">
        <Card title="Interview type">
          <fieldset>
            <legend className="sr-only">Interview types</legend>
            <div className="grid gap-3 sm:grid-cols-2">
              {ALL_TYPES.map((type) => (
                <Checkbox
                  key={type}
                  checked={types.includes(type)}
                  onChange={() => toggle(type)}
                  label={TYPE_LABEL[type]}
                  hint={TYPE_HELP[type]}
                />
              ))}
            </div>
          </fieldset>
        </Card>

        <Card title="Settings">
          <div className="grid gap-4 sm:grid-cols-2">
            <SelectField
              label="Difficulty"
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value as InterviewDifficulty)}
            >
              <option value="beginner">Beginner</option>
              <option value="intermediate">Intermediate</option>
              <option value="advanced">Advanced</option>
            </SelectField>
            <TextField
              label="Number of questions"
              type="number"
              min={1}
              max={30}
              value={count}
              onChange={(e) => setCount(e.target.value)}
              hint="Follow-ups are extra and do not count."
            />
            <SelectField
              label="Target job (optional)"
              value={jobId}
              onChange={(e) => setJobId(e.target.value)}
              hint={
                jobs.isError
                  ? 'Your jobs could not be loaded.'
                  : 'Questions prioritise the job’s requirements and duties.'
              }
            >
              <option value="">No specific job</option>
              {(jobs.data ?? []).map((job) => (
                <option key={job.id} value={job.id}>
                  {job.title}
                  {job.company ? ` · ${job.company}` : ''}
                </option>
              ))}
            </SelectField>
            <SelectField
              label="Follow-ups per question"
              value={followups}
              onChange={(e) => setFollowups(e.target.value)}
            >
              {[0, 1, 2, 3].map((v) => (
                <option key={v} value={v}>
                  {v === 0 ? 'None' : v}
                </option>
              ))}
            </SelectField>
          </div>
        </Card>

        <Card title="AI">
          <div className="space-y-3">
            <Checkbox
              checked={useAi}
              onChange={(e) => setUseAi(e.target.checked)}
              label="Use AI for questions, follow-ups and feedback"
              hint="If no AI is available the interview still runs from a curated question bank, but your answers are saved without evaluation and there are no follow-ups."
            />
            {useAi && (
              <Checkbox
                checked={consent}
                onChange={(e) => setConsent(e.target.checked)}
                label="Allow my answers and a summary of my profile to be sent to an external AI service if one is configured"
                hint="Without this, an external service is never contacted."
              />
            )}
          </div>
        </Card>

        {problems.length > 0 && (
          <Alert tone="warning">
            <ul className="list-inside list-disc">
              {problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          </Alert>
        )}
        {error && <Alert tone="error">{error}</Alert>}
        <div className="flex gap-2">
          <Button type="submit" loading={create.isPending} disabled={problems.length > 0}>
            Create interview
          </Button>
          <Link to="/interviews">
            <Button variant="secondary">Cancel</Button>
          </Link>
        </div>
      </form>
    </>
  );
}
