import { FileText, Trash2, Upload } from 'lucide-react';
import { useRef, useState } from 'react';
import { resumeApi } from '@/api/endpoints';
import { keys, useApiMutation, useResumeAnalysis, useResumes } from '@/api/queries';
import type { Resume, ResumeAnalysis, ResumeStatus } from '@/api/types';
import { ApplyPanel } from '@/components/ApplyPanel';
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
} from '@/components/ui';
import { describeError } from '@/lib/errors';
import { formatBytes, formatDate } from '@/lib/format';

const MAX_BYTES = 5 * 1024 * 1024;
const ALLOWED = ['.pdf', '.docx', '.txt'];

const STATUS: Record<
  ResumeStatus,
  { label: string; tone: 'neutral' | 'brand' | 'success' | 'warning' | 'danger' }
> = {
  uploaded: { label: 'Uploaded', tone: 'neutral' },
  extracting: { label: 'Reading', tone: 'neutral' },
  extracted: { label: 'Ready to analyse', tone: 'brand' },
  analyzing: { label: 'Analysing', tone: 'warning' },
  completed: { label: 'Analysed', tone: 'success' },
  failed: { label: 'Failed', tone: 'danger' },
};

const FAILURE_HELP: Record<string, string> = {
  ocr_required:
    'This looks like a scanned document. Upload a version with selectable text (PDF export, DOCX or TXT).',
  encrypted_document: 'This file is password protected. Remove the password and upload it again.',
  empty_document: 'No text could be found in this file.',
};

export function ResumesPage() {
  const resumes = useResumes();
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <>
      <PageHeader
        title="Resumes"
        description="Upload your CV, check what was extracted, and decide what (if anything) is added to your profile. Nothing is added automatically."
      />
      <div className="space-y-6">
        <UploadCard onUploaded={(id) => setSelected(id)} />
        <QueryBoundary query={resumes} label="Loading your resumes">
          {(items) =>
            items.length === 0 ? (
              <EmptyState
                icon={<FileText className="size-5" aria-hidden />}
                title="No resumes yet"
                description="Upload a PDF, DOCX or TXT file (up to 5 MB) to get started."
              />
            ) : (
              <ResumeList items={items} selected={selected} onSelect={setSelected} />
            )
          }
        </QueryBoundary>
        {selected && <ResumeDetail id={selected} onClose={() => setSelected(null)} />}
      </div>
    </>
  );
}

function UploadCard({ onUploaded }: { onUploaded: (id: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const upload = useApiMutation((file: File) => resumeApi.upload(file), [keys.resumes]);

  async function onFile(file: File | undefined) {
    setError(null);
    if (!file) return;
    const lower = file.name.toLowerCase();
    if (!ALLOWED.some((ext) => lower.endsWith(ext))) {
      setError('Choose a PDF, DOCX or TXT file.');
      return;
    }
    if (file.size > MAX_BYTES) {
      setError(`This file is ${formatBytes(file.size)}. The limit is ${formatBytes(MAX_BYTES)}.`);
      return;
    }
    try {
      const resume = await upload.mutateAsync(file);
      onUploaded(resume.id);
    } catch (e) {
      setError(describeError(e));
    } finally {
      if (input.current) input.current.value = '';
    }
  }

  return (
    <Card title="Upload a CV">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <label htmlFor="cv-file" className="sr-only">
          CV file
        </label>
        <input
          ref={input}
          id="cv-file"
          type="file"
          accept=".pdf,.docx,.txt"
          onChange={(e) => void onFile(e.target.files?.[0])}
          className="block w-full text-sm text-slate-600 file:mr-4 file:rounded-lg file:border-0 file:bg-brand-50 file:px-4 file:py-2 file:text-sm file:font-medium file:text-brand-700 hover:file:bg-brand-100"
        />
        {upload.isPending && (
          <span className="flex items-center gap-2 text-sm text-slate-500">
            <Upload className="size-4" aria-hidden /> Uploading…
          </span>
        )}
      </div>
      <p className="mt-2 text-xs text-slate-500">
        PDF, DOCX or TXT, up to 5 MB. The file type is checked from its content, and the text is
        read on the server.
      </p>
      {error && (
        <Alert tone="error" className="mt-3">
          {error}
        </Alert>
      )}
    </Card>
  );
}

function ResumeList({
  items,
  selected,
  onSelect,
}: {
  items: Resume[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const [toDelete, setToDelete] = useState<Resume | null>(null);
  const [error, setError] = useState<string | null>(null);
  const remove = useApiMutation((id: string) => resumeApi.remove(id), [keys.resumes]);

  async function confirmDelete() {
    if (!toDelete) return;
    try {
      await remove.mutateAsync(toDelete.id);
      setToDelete(null);
    } catch (e) {
      setError(describeError(e));
      setToDelete(null);
    }
  }

  return (
    <Card title="Your resumes">
      {error && (
        <Alert tone="error" className="mb-3">
          {error}
        </Alert>
      )}
      <ul className="divide-y divide-slate-100">
        {items.map((resume) => {
          const status = STATUS[resume.status];
          return (
            <li
              key={resume.id}
              className="flex flex-col gap-2 py-3 sm:flex-row sm:items-center sm:justify-between"
            >
              <div className="min-w-0">
                <p className="truncate font-medium text-slate-900">{resume.display_name}</p>
                <p className="text-xs text-slate-500">
                  {resume.file_format.toUpperCase()} · {formatBytes(resume.size_bytes)}
                  {resume.word_count != null && ` · ${resume.word_count} words`} · uploaded{' '}
                  {formatDate(resume.created_at)}
                </p>
                {resume.status === 'failed' && (
                  <p className="mt-1 text-xs text-red-700">
                    {(resume.error_code && FAILURE_HELP[resume.error_code]) ??
                      resume.error_message ??
                      'Processing failed.'}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                <Badge tone={status.tone}>{status.label}</Badge>
                {resume.status !== 'failed' && (
                  <Button
                    variant={selected === resume.id ? 'primary' : 'secondary'}
                    onClick={() => onSelect(resume.id)}
                  >
                    {resume.has_analysis ? 'View analysis' : 'Analyse'}
                  </Button>
                )}
                <Button
                  variant="ghost"
                  onClick={() => setToDelete(resume)}
                  aria-label={`Delete ${resume.display_name}`}
                >
                  <Trash2 className="size-4" aria-hidden />
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      <ConfirmDialog
        open={toDelete !== null}
        title="Delete this resume?"
        message="The file and its analysis are permanently removed. Your profile is not changed."
        onConfirm={() => void confirmDelete()}
        onCancel={() => setToDelete(null)}
        loading={remove.isPending}
      />
    </Card>
  );
}

function ResumeDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const resumes = useResumes();
  const resume = resumes.data?.find((r) => r.id === id);
  const analysis = useResumeAnalysis(id, Boolean(resume?.has_analysis));
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const analyze = useApiMutation(
    (allow: boolean) => resumeApi.analyze(id, allow),
    [keys.resumes, keys.resumeAnalysis(id)],
  );

  if (!resume) return null;

  async function run() {
    setError(null);
    try {
      await analyze.mutateAsync(consent);
    } catch (e) {
      setError(describeError(e));
    }
  }

  return (
    <Card
      title={`Analysis of ${resume.display_name}`}
      actions={
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
      }
    >
      <div className="space-y-4">
        <div className="rounded-lg bg-slate-50 p-4">
          <Checkbox
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            label="Allow my CV details to be sent to an external AI service if one is configured"
            hint="Needed only when the server uses an external AI provider. Without it nothing leaves the server."
          />
          <div className="mt-3">
            <Button onClick={() => void run()} loading={analyze.isPending}>
              {resume.has_analysis ? 'Analyse again' : 'Analyse this CV'}
            </Button>
          </div>
        </div>
        {error && <Alert tone="error">{error}</Alert>}
        {resume.has_analysis && analysis.isPending && <Spinner label="Loading analysis" />}
        {analysis.isError && <Alert tone="error">{describeError(analysis.error)}</Alert>}
        {analysis.data && <AnalysisView analysis={analysis.data} resumeId={id} />}
        {!resume.has_analysis && !analyze.isPending && (
          <p className="text-sm text-slate-600">
            Analysis uses the AI provider configured on the server. If none is configured you can
            still upload and keep your CV; the rest of the app works without it.
          </p>
        )}
      </div>
    </Card>
  );
}

function List({ items }: { items: string[] }) {
  return items.length === 0 ? (
    <p className="text-sm text-slate-500">Nothing found.</p>
  ) : (
    <ul className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <li key={item}>
          <Badge>{item}</Badge>
        </li>
      ))}
    </ul>
  );
}

function AnalysisView({ analysis, resumeId }: { analysis: ResumeAnalysis; resumeId: string }) {
  const { facts, assessment, missing_information, unverified_items_removed } = analysis.result;
  return (
    <div className="space-y-5">
      <section aria-labelledby="facts-heading">
        <h3 id="facts-heading" className="text-sm font-semibold text-slate-900">
          What was found in your CV
        </h3>
        <p className="mb-2 text-xs text-slate-500">
          Taken from your document and checked against its text.
          {unverified_items_removed > 0 &&
            ` ${unverified_items_removed} item(s) that could not be found in the text were removed.`}
        </p>
        <dl className="grid gap-3 sm:grid-cols-2">
          <div>
            <dt className="text-xs font-medium text-slate-500">Technical skills</dt>
            <dd>
              <List items={[...facts.technical_skills, ...facts.tools_and_technologies]} />
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-slate-500">Soft skills</dt>
            <dd>
              <List items={facts.soft_skills} />
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-slate-500">Work experience</dt>
            <dd>
              <List
                items={facts.work_experience.map(
                  (w) => `${w.title ?? 'Role'} at ${w.company ?? '?'}`,
                )}
              />
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-slate-500">Education</dt>
            <dd>
              <List
                items={facts.education.map(
                  (e) => `${e.degree ?? 'Degree'} · ${e.institution ?? '?'}`,
                )}
              />
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-slate-500">Projects</dt>
            <dd>
              <List items={facts.projects.map((p) => p.name ?? 'Project')} />
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-slate-500">Certifications</dt>
            <dd>
              <List items={facts.certifications.map((c) => c.name ?? 'Certification')} />
            </dd>
          </div>
        </dl>
        {missing_information.length > 0 && (
          <p className="mt-2 text-xs text-slate-500">
            Not found in the CV: {missing_information.join(', ')}.
          </p>
        )}
      </section>

      <section
        aria-labelledby="opinion-heading"
        className="rounded-lg border border-amber-200 bg-amber-50 p-4"
      >
        <h3 id="opinion-heading" className="text-sm font-semibold text-amber-900">
          AI opinion (may be wrong)
        </h3>
        <p className="mt-1 text-xs text-amber-800">
          Generated by {analysis.provider} ({analysis.model}). This is a suggestion, not a fact
          about you.
        </p>
        {assessment.ai_summary && (
          <p className="mt-2 text-sm text-slate-800">{assessment.ai_summary}</p>
        )}
        {assessment.strengths.length > 0 && (
          <div className="mt-2">
            <p className="text-xs font-medium text-slate-600">Possible strengths</p>
            <ul className="list-inside list-disc text-sm text-slate-800">
              {assessment.strengths.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
        )}
        {assessment.potential_skill_gaps.length > 0 && (
          <div className="mt-2">
            <p className="text-xs font-medium text-slate-600">Possible gaps</p>
            <ul className="list-inside list-disc text-sm text-slate-800">
              {assessment.potential_skill_gaps.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      <ApplyPanel
        suggestion={analysis.profile_suggestion}
        notes={analysis.suggestion_notes}
        onApply={(body) => resumeApi.apply(resumeId, body)}
        emptyMessage="There is nothing to suggest from this CV."
      />
    </div>
  );
}
