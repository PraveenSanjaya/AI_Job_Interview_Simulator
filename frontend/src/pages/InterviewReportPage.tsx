import { Link, useParams } from 'react-router-dom';
import { useInterviewReport } from '@/api/queries';
import type { InterviewReportData, QuestionOutcome } from '@/api/types';
import { ScoreBars } from '@/components/charts';
import { DIMENSIONS } from '@/components/EvaluationFeedback';
import {
  Alert,
  Badge,
  Button,
  Card,
  PageHeader,
  ProgressBar,
  QueryBoundary,
} from '@/components/ui';
import { formatDateTime, titleCase } from '@/lib/format';

const GROUP_LABEL: Record<string, string> = {
  knowledge: 'Knowledge',
  approach: 'Approach and application',
  communication: 'Communication',
};

function Outcomes({
  title,
  items,
  empty,
}: {
  title: string;
  items: QuestionOutcome[];
  empty: string;
}) {
  return (
    <Card title={title}>
      {items.length === 0 ? (
        <p className="text-sm text-slate-600">{empty}</p>
      ) : (
        <ul className="divide-y divide-slate-100">
          {items.map((o) => (
            <li key={o.question_id} className="py-3 text-sm">
              <div className="flex items-start justify-between gap-3">
                <p className="font-medium text-slate-900">{o.text}</p>
                <Badge tone={o.status === 'evaluated' ? 'brand' : 'neutral'}>
                  {o.score !== null ? `${o.score}/10` : titleCase(o.status)}
                </Badge>
              </div>
              {o.summary && <p className="mt-1 text-slate-600">{o.summary}</p>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Report({ report }: { report: InterviewReportData }) {
  const scored = report.score_status === 'scored' && report.overall_score !== null;
  const categories = Object.entries(report.category_scores)
    .filter((entry): entry is [string, number] => entry[1] !== null)
    .map(([label, score]) => ({ label: titleCase(label), score }));
  const dimensionRows = DIMENSIONS.filter((d) => report.dimension_scores[d.key] != null);
  const groupsWithScores = Object.entries(report.group_scores).filter(([, g]) => g.score !== null);

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
          <div className="text-center sm:w-44">
            {scored ? (
              <>
                <p className="text-5xl font-semibold text-brand-700" data-testid="overall-score">
                  {report.overall_score}
                </p>
                <p className="text-xs text-slate-500">out of 100</p>
              </>
            ) : (
              <p className="text-lg font-semibold text-slate-700">Not scored</p>
            )}
          </div>
          <div className="min-w-0 flex-1 space-y-2">
            <p className="text-sm text-slate-800">{report.score_explanation}</p>
            <p className="text-xs text-slate-500">
              {report.counts.answered} answered · {report.counts.skipped} skipped ·{' '}
              {report.counts.evaluated_answers} evaluated
              {report.counts.followups_asked > 0 &&
                ` · ${report.counts.followups_asked} follow-up(s)`}
              {report.mode === 'question_bank' && ' · question bank (no AI)'}
            </p>
          </div>
        </div>
      </Card>

      {!scored && (
        <Alert tone="info" title="Why there is no score">
          None of your answers could be evaluated, usually because no AI service was available. Your
          answers are saved. A score is never estimated without an evaluation.
        </Alert>
      )}

      {groupsWithScores.length > 0 && (
        <Card title="Scores by area">
          <ul className="space-y-4">
            {groupsWithScores.map(([key, group]) => (
              <li key={key}>
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium text-slate-800">
                    {GROUP_LABEL[key] ?? titleCase(key)}{' '}
                    {group.subjective && <Badge>subjective</Badge>}
                  </span>
                  <span className="text-slate-600">{group.score}/10</span>
                </div>
                <ProgressBar value={group.score ?? 0} max={10} label={GROUP_LABEL[key] ?? key} />
                <p className="mt-0.5 text-xs text-slate-500">{group.note}</p>
              </li>
            ))}
          </ul>
          {dimensionRows.length > 0 && (
            <details className="mt-4 text-sm">
              <summary className="cursor-pointer text-slate-600">Dimension details</summary>
              <ul className="mt-2 grid gap-1 sm:grid-cols-2">
                {dimensionRows.map((d) => (
                  <li key={d.key} className="flex justify-between">
                    <span>{d.label}</span>
                    <span>{report.dimension_scores[d.key]}/10</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
        </Card>
      )}

      {categories.length > 0 && (
        <Card title="Score by interview type">
          <ScoreBars
            points={categories}
            caption="Average score out of 10 for each interview type"
          />
        </Card>
      )}

      {report.star_summary && (
        <Card title="STAR coverage in behavioral answers">
          <ul className="list-inside list-disc text-sm text-slate-700">
            {Object.entries(report.star_summary).map(([part, text]) => (
              <li key={part}>
                <span className="font-medium">{titleCase(part)}:</span> {text}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {scored && (
        <>
          <Outcomes
            title="Strongest answers"
            items={report.strong_answers}
            empty="No answer reached the strong threshold yet."
          />
          <Outcomes
            title="Answers to work on"
            items={report.weak_answers}
            empty="No answer scored below the weak threshold."
          />
        </>
      )}
      {report.not_evaluated.length > 0 && (
        <Outcomes title="Could not be evaluated" items={report.not_evaluated} empty="" />
      )}

      {report.knowledge_gaps.length > 0 && (
        <Card title="Knowledge gaps">
          <ul className="list-inside list-disc space-y-1 text-sm text-slate-700">
            {report.knowledge_gaps.map((g) => (
              <li key={g}>{g}</li>
            ))}
          </ul>
        </Card>
      )}

      {report.study_topics.length > 0 && (
        <Card title="Recommended study topics">
          <ul className="space-y-2 text-sm">
            {report.study_topics.map((t) => (
              <li key={t.topic}>
                <span className="font-medium text-slate-900">{t.topic}</span>
                <span className="block text-slate-600">{t.reason}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {report.practice_questions.length > 0 && (
        <Card title="Practice questions">
          <ul className="space-y-2 text-sm text-slate-700">
            {report.practice_questions.map((q) => (
              <li key={q.text}>
                {q.topic && <Badge>{q.topic}</Badge>} {q.text}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {report.ai_feedback ? (
        <Card title="AI feedback">
          <Alert tone="warning" className="mb-3">
            {report.ai_feedback.notice}
          </Alert>
          {report.ai_feedback.summary && (
            <p className="mb-3 text-sm text-slate-800">{report.ai_feedback.summary}</p>
          )}
          {report.ai_feedback.study_topics.length > 0 && (
            <ul className="mb-3 list-inside list-disc text-sm text-slate-700">
              {report.ai_feedback.study_topics.map((t) => (
                <li key={t.topic}>
                  {t.topic}: {t.reason}
                </li>
              ))}
            </ul>
          )}
          {report.ai_feedback.practice_questions.length > 0 && (
            <ul className="list-inside list-disc text-sm text-slate-700">
              {report.ai_feedback.practice_questions.map((q) => (
                <li key={q}>{q}</li>
              ))}
            </ul>
          )}
        </Card>
      ) : (
        <p className="text-xs text-slate-500">
          AI feedback: {report.ai_feedback_status.replace(/[:_]/g, ' ')}.
        </p>
      )}

      <details className="text-sm text-slate-600">
        <summary className="cursor-pointer">How this score was calculated</summary>
        <ul className="mt-2 list-inside list-disc space-y-1">
          {report.calculation_notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      </details>
      <p className="text-xs text-slate-500">{report.disclaimer}</p>
    </div>
  );
}

export function InterviewReportPage() {
  const { sessionId = '' } = useParams();
  const report = useInterviewReport(sessionId);
  return (
    <>
      <PageHeader
        title="Interview report"
        description={
          report.data
            ? `${report.data.report.interview_types.map(titleCase).join(' + ')} · ${titleCase(report.data.report.difficulty)}${
                report.data.report.job_title ? ` · ${report.data.report.job_title}` : ''
              } · ${formatDateTime(report.data.created_at)}`
            : undefined
        }
        actions={
          <>
            <Link to="/interviews">
              <Button variant="secondary">All interviews</Button>
            </Link>
            <Link to="/interviews/new">
              <Button>Practise again</Button>
            </Link>
          </>
        }
      />
      <QueryBoundary query={report} label="Loading the report">
        {(data) => <Report report={data.report} />}
      </QueryBoundary>
    </>
  );
}
