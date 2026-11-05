import { useState } from 'react';
import { integrationApi } from '@/api/endpoints';
import {
  keys,
  useApiMutation,
  useGithub,
  useIntegrationAnalyses,
  useIntegrationAnalysis,
  usePortfolio,
  useResumes,
} from '@/api/queries';
import type { IntegrationAnalysis, SourceReference } from '@/api/types';
import { ApplyPanel } from '@/components/ApplyPanel';
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  ConfirmDialog,
  SelectField,
  Spinner,
} from '@/components/ui';
import { describeError } from '@/lib/errors';
import { formatDateTime } from '@/lib/format';

const SOURCE_LABEL: Record<string, string> = {
  github: 'GitHub',
  portfolio: 'Portfolio',
  resume: 'CV',
};

const refLabel = (r: SourceReference) =>
  `${SOURCE_LABEL[r.source] ?? r.source}${r.ref ? `: ${r.ref}` : ''}`;

/** Runs and shows an analysis of the connected public sources, with its evidence. */
export function IntegrationAnalysisCard() {
  const github = useGithub();
  const portfolio = usePortfolio();
  const resumes = useResumes();
  const list = useIntegrationAnalyses();
  const latestId = list.data?.[0]?.id;
  const detail = useIntegrationAnalysis(latestId);

  const [consent, setConsent] = useState(false);
  const [resumeId, setResumeId] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState(false);
  const analyze = useApiMutation(integrationApi.analyze, [keys.analyses]);
  const remove = useApiMutation((id: string) => integrationApi.removeAnalysis(id), [keys.analyses]);

  const connected = Boolean(github.data) || Boolean(portfolio.data);
  const loadingSources = github.isPending || portfolio.isPending;
  const analysedResumes = (resumes.data ?? []).filter((r) => r.has_analysis);

  async function run() {
    setError(null);
    try {
      await analyze.mutateAsync({
        allow_external_ai: consent,
        ...(resumeId ? { resume_id: resumeId } : {}),
      });
    } catch (e) {
      setError(describeError(e));
    }
  }

  return (
    <Card title="Evidence analysis">
      <div className="space-y-4">
        <p className="text-sm text-slate-600">
          Reads your connected sources (and, if you choose, an analysed CV) and describes what they
          show. It is an AI opinion based only on public pages and is not a measure of ability.
          Nothing is added to your profile until you approve it.
        </p>
        {loadingSources ? (
          <Spinner label="Loading connections" />
        ) : !connected ? (
          <Alert tone="info">Connect GitHub or a portfolio above to run an analysis.</Alert>
        ) : (
          <div className="space-y-3 rounded-lg bg-slate-50 p-4">
            {analysedResumes.length > 0 && (
              <SelectField
                label="Compare with a CV (optional)"
                hint="Shows which CV skills have public evidence. A missing match does not mean the skill is missing."
                value={resumeId}
                onChange={(e) => setResumeId(e.target.value)}
              >
                <option value="">Do not compare</option>
                {analysedResumes.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.display_name}
                  </option>
                ))}
              </SelectField>
            )}
            <Checkbox
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              label="Allow my public source data to be sent to an external AI service if one is configured"
              hint="Needed only when the server uses an external AI provider. Without it nothing leaves the server."
            />
            <Button onClick={() => void run()} loading={analyze.isPending}>
              {latestId ? 'Analyse again' : 'Analyse my sources'}
            </Button>
          </div>
        )}
        {error && <Alert tone="error">{error}</Alert>}
        {list.isError && <Alert tone="error">{describeError(list.error)}</Alert>}
        {detail.isPending && latestId && <Spinner label="Loading analysis" />}
        {detail.isError && <Alert tone="error">{describeError(detail.error)}</Alert>}
        {list.isSuccess && list.data.length === 0 && connected && !analyze.isPending && (
          <p className="text-sm text-slate-600">
            No analysis yet. Analysis needs an AI provider on the server; connecting sources works
            without one.
          </p>
        )}
        {detail.data && (
          <>
            <AnalysisView analysis={detail.data} />
            <div>
              <Button variant="secondary" onClick={() => setConfirm(true)}>
                Delete this analysis
              </Button>
            </div>
            <ConfirmDialog
              open={confirm}
              title="Delete this analysis?"
              message="The analysis and its suggestions are deleted. Your connections and profile are not affected."
              confirmLabel="Delete"
              loading={remove.isPending}
              onCancel={() => setConfirm(false)}
              onConfirm={() =>
                void remove.mutateAsync(detail.data.id).then(() => setConfirm(false))
              }
            />
          </>
        )}
      </div>
    </Card>
  );
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="list-inside list-disc text-sm text-slate-800">
      {items.map((s) => (
        <li key={s}>{s}</li>
      ))}
    </ul>
  );
}

function Heading({ children }: { children: string }) {
  return <h4 className="text-sm font-semibold text-slate-900">{children}</h4>;
}

function AnalysisView({ analysis }: { analysis: IntegrationAnalysis }) {
  const { facts, assessment, unverified_items_removed } = analysis.result;
  const suggestion = analysis.profile_suggestion;
  return (
    <div className="space-y-5 border-t border-slate-100 pt-4">
      <p className="text-xs text-slate-500">
        Analysed {formatDateTime(analysis.created_at)} by {analysis.provider} / {analysis.model}.
        Sources: {facts.sources_used.map((s) => SOURCE_LABEL[s] ?? s).join(', ') || 'none'}.
      </p>
      {analysis.input_truncated && (
        <Alert tone="warning">
          Some source text was too long and only the first part was used.
        </Alert>
      )}

      <section aria-labelledby="ia-facts">
        <h3 id="ia-facts" className="text-sm font-semibold text-slate-900">
          Facts read from your sources
        </h3>
        <p className="mb-2 text-xs text-slate-500">Counted by the application, not by the AI.</p>
        {facts.github && (
          <div className="mb-3 text-sm text-slate-800">
            <p>
              GitHub <strong>{facts.github.login}</strong>:{' '}
              {facts.github.own_repositories_considered} own repositories considered,{' '}
              {facts.github.own_repos_pushed_last_365_days} updated in the last year.
            </p>
            <ul className="mt-1.5 flex flex-wrap gap-1.5">
              {Object.entries(facts.github.language_distribution).map(([lang, n]) => (
                <li key={lang}>
                  <Badge tone="brand">
                    {lang} · {n}
                  </Badge>
                </li>
              ))}
            </ul>
          </div>
        )}
        {facts.portfolio && (
          <p className="mb-3 text-sm text-slate-800">
            Portfolio <strong>{facts.portfolio.host}</strong>: {facts.portfolio.pages.length}{' '}
            page(s) read.
          </p>
        )}
        {facts.consistency && (
          <div className="text-sm text-slate-800">
            <p className="font-medium">CV skills with public evidence</p>
            {facts.consistency.cv_skills_with_public_evidence.length === 0 ? (
              <p className="text-slate-500">None matched in the connected sources.</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {facts.consistency.cv_skills_with_public_evidence.map((s) => (
                  <li key={s.skill}>
                    {s.skill}{' '}
                    <span className="text-xs text-slate-500">
                      ({s.found_in.map(refLabel).join('; ')})
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {facts.consistency.cv_skills_without_public_evidence.length > 0 && (
              <>
                <p className="mt-2 font-medium">CV skills with no match in these sources</p>
                <p className="text-slate-700">
                  {facts.consistency.cv_skills_without_public_evidence.join(', ')}
                </p>
              </>
            )}
            <p className="mt-1 text-xs text-slate-500">{facts.consistency.note}</p>
          </div>
        )}
      </section>

      <section aria-labelledby="ia-assessment">
        <h3 id="ia-assessment" className="text-sm font-semibold text-slate-900">
          AI assessment
        </h3>
        <p className="mb-2 text-xs text-slate-500">
          An opinion that may be incomplete or wrong.
          {unverified_items_removed > 0 &&
            ` ${unverified_items_removed} claim(s) the sources did not support were removed.`}
        </p>
        {assessment.summary && <p className="mb-3 text-sm text-slate-800">{assessment.summary}</p>}
        {assessment.strengths.length > 0 && (
          <div className="mb-3">
            <Heading>Strengths</Heading>
            <Bullets items={assessment.strengths} />
          </div>
        )}
        {assessment.potential_skill_gaps.length > 0 && (
          <div className="mb-3">
            <Heading>Possible gaps</Heading>
            <Bullets items={assessment.potential_skill_gaps} />
          </div>
        )}
        {assessment.project_assessments.length > 0 && (
          <div className="mb-3">
            <Heading>Projects</Heading>
            <ul className="divide-y divide-slate-100 text-sm">
              {assessment.project_assessments.map((p, i) => (
                <li key={`${p.name}-${i}`} className="py-2">
                  <p className="font-medium text-slate-900">
                    {p.name ?? 'Unnamed project'}{' '}
                    <Badge>
                      {p.complexity === 'unclear' ? 'complexity unclear' : p.complexity}
                    </Badge>
                  </p>
                  {p.what_it_shows && <p className="text-slate-700">{p.what_it_shows}</p>}
                  {p.technologies_demonstrated.length > 0 && (
                    <p className="text-xs text-slate-500">
                      Technologies: {p.technologies_demonstrated.join(', ')}
                    </p>
                  )}
                  <p className="text-xs text-slate-500">Evidence: {refLabel(p.source)}</p>
                </li>
              ))}
            </ul>
          </div>
        )}
        {assessment.demonstrated_skills.length > 0 && (
          <div className="mb-3">
            <Heading>Skills shown, with evidence</Heading>
            <ul className="space-y-1 text-sm text-slate-800">
              {assessment.demonstrated_skills.map((s, i) => (
                <li key={`${s.name}-${i}`}>
                  {s.name}{' '}
                  <span className="text-xs text-slate-500">
                    ({s.evidence.map(refLabel).join('; ')})
                  </span>
                </li>
              ))}
            </ul>
          </div>
        )}
        {assessment.consistency_notes.length > 0 && (
          <div className="mb-3">
            <Heading>Consistency with your CV</Heading>
            <Bullets items={assessment.consistency_notes} />
          </div>
        )}
        {assessment.caveats.length > 0 && (
          <div>
            <Heading>Caveats</Heading>
            <Bullets items={assessment.caveats} />
          </div>
        )}
      </section>

      {suggestion && (
        <ApplyPanel
          suggestion={suggestion}
          notes={analysis.suggestion_notes}
          onApply={(body) => integrationApi.applyAnalysis(analysis.id, body)}
          emptyMessage="There is nothing to suggest from these sources."
        />
      )}
    </div>
  );
}
