import type { EvidenceRef, Match, RequirementMatch, SkillGroup, SkillStatus } from '@/api/types';
import { Alert, Badge, Card, ProgressBar } from '@/components/ui';
import { titleCase } from '@/lib/format';

const STATUS: Record<
  SkillStatus,
  { label: string; tone: 'success' | 'warning' | 'danger' | 'neutral' }
> = {
  supported: { label: 'Shown in your material', tone: 'success' },
  weakly_supported: { label: 'Listed only', tone: 'warning' },
  not_found: { label: 'No evidence found', tone: 'danger' },
  unknown: { label: 'Cannot be assessed', tone: 'neutral' },
};

function Evidence({ refs }: { refs: EvidenceRef[] }) {
  if (refs.length === 0) return null;
  return (
    <ul className="mt-1 flex flex-wrap gap-1.5" aria-label="Evidence">
      {refs.map((ref) => (
        <li key={`${ref.source}-${ref.kind}-${ref.ref}`}>
          <Badge tone="brand">
            {ref.source}: {ref.ref}
          </Badge>
        </li>
      ))}
    </ul>
  );
}

function SkillRow({ item }: { item: RequirementMatch }) {
  const status = STATUS[item.status];
  return (
    <li className="py-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-slate-900">{item.name}</span>
        <Badge tone={status.tone}>{status.label}</Badge>
        {item.importance === 'unspecified' && <Badge>Importance not stated</Badge>}
        {item.satisfied_via && <Badge tone="success">Covered by {item.satisfied_via}</Badge>}
      </div>
      <p className="mt-1 text-sm text-slate-600">{item.note}</p>
      <Evidence refs={item.evidence} />
      {item.job_quote && (
        <p className="mt-1 text-xs italic text-slate-500">Job text: “{item.job_quote}”</p>
      )}
    </li>
  );
}

function SkillGroupCard({ group }: { group: SkillGroup }) {
  if (group.total === 0) {
    return (
      <Card title={group.label}>
        <p className="text-sm text-slate-600">The job names none.</p>
      </Card>
    );
  }
  return (
    <Card title={`${group.label} (${group.total})`}>
      <p className="mb-2 text-sm text-slate-600">
        {group.supported} shown · {group.weakly_supported} listed only · {group.not_found} no
        evidence found
        {group.unknown > 0 && ` · ${group.unknown} cannot be assessed`}
      </p>
      <ul className="divide-y divide-slate-100">
        {group.items.map((item) => (
          <SkillRow key={item.name} item={item} />
        ))}
      </ul>
    </Card>
  );
}

export function MatchReportView({ match }: { match: Match }) {
  const { report, ai_advice: advice } = match;
  const score = report.score;
  return (
    <div className="space-y-4" data-testid="match-report">
      <Card>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <div className="text-center sm:w-40">
            {score.score !== null ? (
              <>
                <p className="text-5xl font-semibold text-brand-700">{score.score}</p>
                <p className="text-xs text-slate-500">out of 100</p>
              </>
            ) : (
              <p className="text-lg font-semibold text-slate-700">Not scored</p>
            )}
            <p className="mt-1 text-xs text-slate-500">Confidence: {score.confidence}</p>
          </div>
          <div className="min-w-0 flex-1 space-y-2">
            <p className="text-sm text-slate-800">{score.explanation}</p>
            <p className="text-xs text-slate-500">
              This measures how much of the job description your recorded evidence covers under
              fixed rules. It is not the chance of getting the job.
            </p>
          </div>
        </div>
      </Card>

      <Card title="How the score is built">
        <ul className="space-y-3">
          {score.dimensions.map((d) => (
            <li key={d.key}>
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium text-slate-800">{d.label}</span>
                <span className="text-slate-600">
                  {d.applicable
                    ? `${Math.round((d.value ?? 0) * 100)}% · ${d.points.toFixed(1)} points`
                    : 'Not assessed'}
                </span>
              </div>
              {d.applicable && (
                <ProgressBar value={(d.value ?? 0) * 100} label={`${d.label} coverage`} />
              )}
              <p className="mt-0.5 text-xs text-slate-500">{d.explanation}</p>
            </li>
          ))}
        </ul>
      </Card>

      <Card title="Evidence used">
        <ul className="flex flex-wrap gap-2">
          {(['profile', 'resume', 'github', 'portfolio'] as const).map((source) => (
            <li key={source}>
              <Badge tone={report.sources[source] ? 'success' : 'neutral'}>
                {titleCase(source)}: {report.sources[source] ? 'used' : 'not used'}
              </Badge>
            </li>
          ))}
        </ul>
        {Object.entries(report.sources.not_available).length > 0 && (
          <p className="mt-2 text-sm text-slate-600">
            Not available:{' '}
            {Object.entries(report.sources.not_available)
              .map(([s, why]) => `${s} (${why})`)
              .join(', ')}
            . A skill that looks missing may simply be recorded there.
          </p>
        )}
      </Card>

      <SkillGroupCard group={report.required_skills} />
      <SkillGroupCard group={report.preferred_skills} />

      {report.technical_strengths.length > 0 && (
        <Card title="Technical strengths">
          <ul className="space-y-2">
            {report.technical_strengths.map((s) => (
              <li key={s.skill}>
                <span className="font-medium text-slate-900">{s.skill}</span>
                <span className="ml-2 text-xs text-slate-500">
                  {s.independent_evidence} independent piece(s) of evidence
                </span>
                <Evidence refs={s.evidence} />
              </li>
            ))}
          </ul>
        </Card>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <Card title="Experience">
          <p className="text-sm text-slate-700">{titleCase(report.experience.status)}</p>
          {report.experience.notes.map((n) => (
            <p key={n} className="mt-1 text-xs text-slate-500">
              {n}
            </p>
          ))}
        </Card>
        <Card title="Education">
          <p className="text-sm text-slate-700">{titleCase(report.education.status)}</p>
          {report.education.notes.map((n) => (
            <p key={n} className="mt-1 text-xs text-slate-500">
              {n}
            </p>
          ))}
        </Card>
      </div>

      {report.project_relevance.projects.length > 0 && (
        <Card title="Relevant projects">
          <ul className="space-y-1 text-sm">
            {report.project_relevance.projects.map((p) => (
              <li key={p.name}>
                <span className="font-medium">{p.name}</span>
                <span className="text-slate-600"> covers {p.matched_technologies.join(', ')}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {report.improvement_areas.length > 0 && (
        <Card title="Where to improve">
          <ul className="space-y-3">
            {report.improvement_areas.map((a) => (
              <li key={a.topic}>
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-900">{a.topic}</span>
                  <Badge
                    tone={
                      a.priority === 'high'
                        ? 'danger'
                        : a.priority === 'medium'
                          ? 'warning'
                          : 'neutral'
                    }
                  >
                    {a.priority} priority
                  </Badge>
                </div>
                <p className="text-sm text-slate-600">{a.reason}</p>
                <p className="text-sm text-slate-800">{a.suggestion}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {report.preparation_topics.length > 0 && (
        <Card title="What to prepare for the interview">
          <ul className="space-y-2 text-sm">
            {report.preparation_topics.map((t) => (
              <li key={t.topic}>
                <span className="font-medium text-slate-900">{t.topic}</span>
                <span className="block text-slate-600">{t.reason}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {advice && (
        <Card title="AI advice">
          <Alert tone="warning" className="mb-3">
            {advice.notice}
          </Alert>
          {advice.summary && <p className="mb-3 text-sm text-slate-800">{advice.summary}</p>}
          {advice.learning_topics.length > 0 && (
            <>
              <h3 className="text-sm font-semibold text-slate-900">Suggested topics to learn</h3>
              <ul className="mb-3 list-inside list-disc text-sm text-slate-700">
                {advice.learning_topics.map((t) => (
                  <li key={t.topic}>
                    {t.topic}: {t.reason}
                  </li>
                ))}
              </ul>
            </>
          )}
          {advice.project_ideas.length > 0 && (
            <>
              <h3 className="text-sm font-semibold text-slate-900">Project ideas</h3>
              <ul className="list-inside list-disc text-sm text-slate-700">
                {advice.project_ideas.map((p) => (
                  <li key={p.title}>
                    {p.title}: {p.description}
                  </li>
                ))}
              </ul>
            </>
          )}
        </Card>
      )}

      {report.caveats.length > 0 && (
        <Card title="Things to keep in mind">
          <ul className="list-inside list-disc space-y-1 text-sm text-slate-600">
            {report.caveats.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </Card>
      )}
      <p className="text-xs text-slate-500">{report.disclaimer}</p>
    </div>
  );
}
