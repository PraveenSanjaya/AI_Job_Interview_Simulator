import { zodResolver } from '@hookform/resolvers/zod';
import { Briefcase, Plus } from 'lucide-react';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { z } from 'zod';
import { jobApi } from '@/api/endpoints';
import {
  keys,
  useApiMutation,
  useJob,
  useJobAnalysis,
  useJobs,
  useMatch,
  useMatches,
} from '@/api/queries';
import type { Importance, JobAnalysis, JobSkill, JobStatus } from '@/api/types';
import { MatchReportView } from '@/components/MatchReportView';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  EmptyState,
  PageHeader,
  QueryBoundary,
  Spinner,
  TextArea,
  TextField,
} from '@/components/ui';
import { describeError } from '@/lib/errors';
import { formatDate, formatDateTime, titleCase } from '@/lib/format';

const STATUS_TONE: Record<JobStatus, 'success' | 'warning' | 'danger'> = {
  parsed: 'success',
  saved: 'warning',
  failed: 'danger',
};

// ---------------------------------------------------------------------- list

export function JobsPage() {
  const jobs = useJobs();
  return (
    <>
      <PageHeader
        title="Jobs"
        description="Save job descriptions you are interested in, see what they ask for, and compare them with your evidence."
        actions={
          <Link to="/jobs/new">
            <Button>
              <Plus className="size-4" aria-hidden /> Add a job
            </Button>
          </Link>
        }
      />
      <QueryBoundary query={jobs} label="Loading your jobs">
        {(items) =>
          items.length === 0 ? (
            <EmptyState
              icon={<Briefcase className="size-5" aria-hidden />}
              title="No jobs saved yet"
              description="Paste a job description to see its requirements and how well your profile matches."
              action={
                <Link to="/jobs/new">
                  <Button>Add your first job</Button>
                </Link>
              }
            />
          ) : (
            <ul className="divide-y divide-slate-100 rounded-xl bg-white shadow-sm ring-1 ring-slate-200">
              {items.map((job) => (
                <li key={job.id}>
                  <Link
                    to={`/jobs/${job.id}`}
                    className="flex items-center justify-between gap-3 px-5 py-4 hover:bg-slate-50"
                  >
                    <div className="min-w-0">
                      <p className="truncate font-medium text-slate-900">{job.title}</p>
                      <p className="text-sm text-slate-500">
                        {job.company ?? 'Company not given'} · added {formatDate(job.created_at)}
                      </p>
                    </div>
                    <Badge tone={STATUS_TONE[job.status]}>{titleCase(job.status)}</Badge>
                  </Link>
                </li>
              ))}
            </ul>
          )
        }
      </QueryBoundary>
    </>
  );
}

// ----------------------------------------------------------------------- new

const newJobSchema = z
  .object({
    title: z.string().trim().min(1, 'Enter the job title').max(200, 'Use at most 200 characters'),
    company: z.string().trim().max(200, 'Use at most 200 characters'),
    description: z.string().max(30000, 'The description can be at most 30,000 characters'),
    source_url: z
      .string()
      .trim()
      .refine((v) => v === '' || /^https?:\/\/\S+$/i.test(v), 'Start with http:// or https://'),
  })
  .superRefine((v, ctx) => {
    const text = v.description.trim();
    if (!text && !v.source_url) {
      ctx.addIssue({
        code: 'custom',
        path: ['description'],
        message: 'Paste the job description or give a link to it',
      });
    } else if (text && text.length < 40) {
      ctx.addIssue({
        code: 'custom',
        path: ['description'],
        message: 'Write at least 40 characters',
      });
    }
  });
type NewJobValues = z.infer<typeof newJobSchema>;

export function NewJobPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const create = useApiMutation(jobApi.create, [keys.jobs]);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<NewJobValues>({
    resolver: zodResolver(newJobSchema),
    defaultValues: { title: '', company: '', description: '', source_url: '' },
  });

  async function onSubmit(values: NewJobValues) {
    setError(null);
    try {
      const job = await create.mutateAsync({
        title: values.title,
        company: values.company || null,
        description: values.description.trim() || null,
        source_url: values.source_url || null,
      });
      navigate(`/jobs/${job.id}`);
    } catch (e) {
      setError(describeError(e));
    }
  }

  return (
    <>
      <PageHeader
        title="Add a job"
        description="Pasting the text is the most reliable way. Sites that need a login or forbid automated access (such as LinkedIn and Indeed) cannot be read: paste the text instead."
      />
      <Card>
        <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="space-y-4">
          {error && <Alert tone="error">{error}</Alert>}
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField label="Job title" error={errors.title?.message} {...register('title')} />
            <TextField
              label="Company (optional)"
              error={errors.company?.message}
              {...register('company')}
            />
          </div>
          <TextArea
            label="Job description"
            rows={12}
            error={errors.description?.message}
            {...register('description')}
          />
          <TextField
            label="Link to the posting (optional)"
            placeholder="https://"
            hint="If you leave the description empty, the text is read from this public page. If you paste the text, the link is only kept as a reference."
            error={errors.source_url?.message}
            {...register('source_url')}
          />
          <div className="flex gap-2">
            <Button type="submit" loading={isSubmitting}>
              Save job
            </Button>
            <Link to="/jobs">
              <Button variant="secondary">Cancel</Button>
            </Link>
          </div>
        </form>
      </Card>
    </>
  );
}

// -------------------------------------------------------------------- detail

export function JobDetailPage() {
  const { jobId = '' } = useParams();
  const job = useJob(jobId);
  const navigate = useNavigate();
  const [editing, setEditing] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const remove = useApiMutation(() => jobApi.remove(jobId), [keys.jobs]);

  return (
    <QueryBoundary query={job} label="Loading the job">
      {(data) => (
        <>
          <PageHeader
            title={data.title}
            description={
              <>
                {data.company ?? 'Company not given'} ·{' '}
                <Badge tone={STATUS_TONE[data.status]}>{titleCase(data.status)}</Badge>
                {data.source_url && (
                  <>
                    {' · '}
                    <a
                      href={data.source_url}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="text-brand-700 hover:underline"
                    >
                      posting
                    </a>
                  </>
                )}
              </>
            }
            actions={
              <>
                <Link to={`/interviews/new?job=${data.id}`}>
                  <Button>Practise for this job</Button>
                </Link>
                <Button variant="secondary" onClick={() => setEditing((v) => !v)}>
                  {editing ? 'Close editor' : 'Edit'}
                </Button>
                <Button variant="secondary" onClick={() => setConfirm(true)}>
                  Delete
                </Button>
              </>
            }
          />
          <div className="space-y-6">
            {editing ? (
              <EditJob jobId={jobId} initial={data} onDone={() => setEditing(false)} />
            ) : (
              <Card title="Description">
                <p className="max-h-72 overflow-auto whitespace-pre-wrap text-sm text-slate-700">
                  {data.description}
                </p>
              </Card>
            )}
            <AnalysisCard jobId={jobId} failed={data.status === 'failed'} />
            <MatchSection jobId={jobId} />
          </div>
          <ConfirmDialog
            open={confirm}
            title="Delete this job?"
            message="The job, its analysis and all of its match reports are permanently deleted. Your profile is not changed."
            loading={remove.isPending}
            onCancel={() => setConfirm(false)}
            onConfirm={() => void remove.mutateAsync(undefined).then(() => navigate('/jobs'))}
          />
        </>
      )}
    </QueryBoundary>
  );
}

function EditJob({
  jobId,
  initial,
  onDone,
}: {
  jobId: string;
  initial: { title: string; company: string | null; description: string };
  onDone: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const update = useApiMutation(
    (body: { title: string; company: string | null; description: string }) =>
      jobApi.update(jobId, body),
    [keys.job(jobId), keys.jobs, keys.jobAnalysis(jobId)],
  );
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<NewJobValues>({
    resolver: zodResolver(newJobSchema),
    defaultValues: {
      title: initial.title,
      company: initial.company ?? '',
      description: initial.description,
      source_url: '',
    },
  });
  async function onSubmit(values: NewJobValues) {
    setError(null);
    try {
      await update.mutateAsync({
        title: values.title,
        company: values.company || null,
        description: values.description,
      });
      onDone();
    } catch (e) {
      setError(describeError(e));
    }
  }
  return (
    <Card title="Edit job">
      <form onSubmit={(e) => void handleSubmit(onSubmit)(e)} noValidate className="space-y-4">
        <Alert tone="info">
          Changing the title or description re-reads the job. Match reports you already made are
          kept as they were.
        </Alert>
        {error && <Alert tone="error">{error}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <TextField label="Job title" error={errors.title?.message} {...register('title')} />
          <TextField label="Company" error={errors.company?.message} {...register('company')} />
        </div>
        <TextArea
          label="Job description"
          rows={10}
          error={errors.description?.message}
          {...register('description')}
        />
        <Button type="submit" loading={isSubmitting}>
          Save changes
        </Button>
      </form>
    </Card>
  );
}

const IMPORTANCE_TONE: Record<Importance, 'danger' | 'brand' | 'neutral'> = {
  required: 'danger',
  preferred: 'brand',
  unspecified: 'neutral',
};

function SkillChips({ skills }: { skills: JobSkill[] }) {
  if (skills.length === 0) return <p className="text-sm text-slate-500">None found.</p>;
  return (
    <ul className="flex flex-wrap gap-1.5">
      {skills.map((s) => (
        <li key={s.name}>
          <Badge tone={IMPORTANCE_TONE[s.importance]}>
            {s.name}
            {s.alternatives.length > 0 && ` (or ${s.alternatives.join(', ')})`}
            {s.source === 'ai' && ' · AI'}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

function AnalysisCard({ jobId, failed }: { jobId: string; failed: boolean }) {
  const analysis = useJobAnalysis(jobId);
  const [useAi, setUseAi] = useState(false);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useApiMutation(
    (body: { use_ai: boolean; allow_external_ai: boolean }) => jobApi.analyze(jobId, body),
    [keys.jobAnalysis(jobId), keys.job(jobId), keys.jobs],
  );

  async function analyze() {
    setError(null);
    try {
      await run.mutateAsync({ use_ai: useAi, allow_external_ai: consent });
    } catch (e) {
      setError(describeError(e));
    }
  }

  return (
    <Card title="What the job asks for">
      {analysis.isPending && <Spinner label="Reading the job" />}
      {analysis.isError && <Alert tone="error">{describeError(analysis.error)}</Alert>}
      {analysis.data === null && !analysis.isPending && (
        <Alert tone="warning">
          {failed
            ? 'This job could not be processed. Try analysing it again.'
            : 'This job has not been analysed yet.'}
        </Alert>
      )}
      {analysis.data && <AnalysisView analysis={analysis.data} />}
      <div className="mt-4 space-y-3 rounded-lg bg-slate-50 p-4">
        <Checkbox
          checked={useAi}
          onChange={(e) => setUseAi(e.target.checked)}
          label="Also ask the AI to find requirements the built-in reader missed"
          hint="Optional. Every item the AI adds must quote the job text; anything else is dropped."
        />
        {useAi && (
          <Checkbox
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            label="Allow the job text to be sent to an external AI service if one is configured"
          />
        )}
        {error && <Alert tone="error">{error}</Alert>}
        <Button variant="secondary" onClick={() => void analyze()} loading={run.isPending}>
          Analyse again
        </Button>
      </div>
    </Card>
  );
}

function AnalysisView({ analysis }: { analysis: JobAnalysis }) {
  const parsed = analysis.result.parsed;
  const required = parsed.technical_skills.filter(
    (s) => s.importance === 'required' && !s.context_only,
  );
  const preferred = parsed.technical_skills.filter(
    (s) => s.importance === 'preferred' && !s.context_only,
  );
  const unclear = parsed.technical_skills.filter(
    (s) => s.importance === 'unspecified' && !s.context_only,
  );
  return (
    <div className="space-y-4">
      <div>
        <h3 className="mb-1 text-sm font-semibold text-slate-900">Required</h3>
        <SkillChips skills={required} />
      </div>
      <div>
        <h3 className="mb-1 text-sm font-semibold text-slate-900">Nice to have</h3>
        <SkillChips skills={preferred} />
      </div>
      {unclear.length > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-semibold text-slate-900">
            Mentioned, importance not stated
          </h3>
          <SkillChips skills={unclear} />
        </div>
      )}
      <dl className="grid gap-2 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs text-slate-500">Seniority</dt>
          <dd>
            {parsed.seniority.level
              ? `${titleCase(parsed.seniority.level)} (${parsed.seniority.basis.replace(/_/g, ' ')})`
              : 'Not stated'}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Years of experience</dt>
          <dd>{parsed.overall_min_years ? `${parsed.overall_min_years}+` : 'Not stated'}</dd>
        </div>
        <div>
          <dt className="text-xs text-slate-500">Education</dt>
          <dd>{parsed.education[0] ? titleCase(parsed.education[0].level) : 'Not stated'}</dd>
        </div>
      </dl>
      {parsed.warnings.map((w) => (
        <Alert key={w} tone="info">
          {w}
        </Alert>
      ))}
      <p className="text-xs text-slate-500">
        Read by{' '}
        {analysis.parser === 'deterministic'
          ? 'the built-in reader'
          : 'the built-in reader plus AI'}{' '}
        on {formatDateTime(analysis.created_at)}. Each item quotes the job text; nothing is verified
        with the employer.
      </p>
    </div>
  );
}

function MatchSection({ jobId }: { jobId: string }) {
  const matches = useMatches(jobId);
  const [selected, setSelected] = useState<string | undefined>();
  const [useAi, setUseAi] = useState(false);
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const create = useApiMutation(
    (body: { use_ai: boolean; allow_external_ai: boolean }) => jobApi.match(jobId, body),
    [keys.matches(jobId)],
  );
  const latest = matches.data?.[0]?.id;
  const shown = selected ?? latest;
  const detail = useMatch(jobId, shown);

  async function compare() {
    setError(null);
    try {
      const match = await create.mutateAsync({ use_ai: useAi, allow_external_ai: consent });
      setSelected(match.id);
    } catch (e) {
      setError(describeError(e));
    }
  }

  return (
    <Card title="How you match">
      <div className="space-y-3 rounded-lg bg-slate-50 p-4">
        <p className="text-sm text-slate-600">
          Compares the job with your profile and, when available, your analysed CV, GitHub and
          portfolio. The score comes from fixed rules and works without any AI.
        </p>
        <Checkbox
          checked={useAi}
          onChange={(e) => setUseAi(e.target.checked)}
          label="Add plain-language AI advice (optional)"
          hint="The score never depends on it. Only requirement names, statuses and scores are sent, not your name, contact details or project names."
        />
        {useAi && (
          <Checkbox
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            label="Allow this summary to be sent to an external AI service if one is configured"
          />
        )}
        {error && <Alert tone="error">{error}</Alert>}
        <Button onClick={() => void compare()} loading={create.isPending}>
          {matches.data && matches.data.length > 0 ? 'Compare again' : 'Compare with my profile'}
        </Button>
      </div>

      {matches.isPending && <Spinner label="Loading earlier comparisons" />}
      {matches.isError && (
        <Alert tone="error" className="mt-4">
          {describeError(matches.error)}
        </Alert>
      )}
      {matches.data && matches.data.length === 0 && (
        <p className="mt-4 text-sm text-slate-600">
          No comparison yet. Reports you create are saved and never change afterwards.
        </p>
      )}
      {matches.data && matches.data.length > 0 && (
        <div className="mt-5 space-y-4">
          <div>
            <label htmlFor="match-select" className="mb-1 block text-sm font-medium text-slate-700">
              Saved comparisons
            </label>
            <select
              id="match-select"
              value={shown}
              onChange={(e) => setSelected(e.target.value)}
              className="block w-full rounded-lg border-0 bg-white px-3 py-2 text-sm ring-1 ring-inset ring-slate-300 sm:w-96"
            >
              {matches.data.map((m) => (
                <option key={m.id} value={m.id}>
                  {formatDateTime(m.created_at)} ·{' '}
                  {m.overall_score !== null ? `${m.overall_score}/100` : 'not scored'}
                </option>
              ))}
            </select>
          </div>
          {detail.isPending && <Spinner label="Loading the report" />}
          {detail.isError && <Alert tone="error">{describeError(detail.error)}</Alert>}
          {detail.data && <MatchReportView match={detail.data} />}
        </div>
      )}
    </Card>
  );
}
