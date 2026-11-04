import type { Evaluation } from '@/api/types';
import { Alert, Badge, ProgressBar } from '@/components/ui';

export const DIMENSIONS: {
  key: string;
  label: string;
  group: 'content' | 'approach' | 'communication';
}[] = [
  { key: 'technical_correctness', label: 'Technical correctness', group: 'content' },
  { key: 'relevance', label: 'Relevance to the question', group: 'content' },
  { key: 'completeness', label: 'Completeness', group: 'content' },
  { key: 'problem_solving', label: 'Problem solving', group: 'approach' },
  { key: 'practical_application', label: 'Practical application', group: 'approach' },
  { key: 'clarity', label: 'Clarity of explanation', group: 'communication' },
  { key: 'evidence_examples', label: 'Examples and evidence', group: 'communication' },
];

const REASON: Record<string, string> = {
  skipped: 'You skipped this question, so it was not evaluated.',
  provider_unavailable:
    'The AI service is not available, so this answer was saved but not evaluated.',
  ai_timeout: 'The AI service took too long. Your answer is saved but was not evaluated.',
  ai_rate_limited: 'The AI service is busy. Your answer is saved but was not evaluated.',
  invalid_ai_response:
    'The AI service returned an unusable evaluation. Your answer is saved but was not evaluated.',
};

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
      <ul className="list-inside list-disc text-sm text-slate-700">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

/** Feedback on one answer. Without a real evaluation it says so instead of showing anything. */
export function EvaluationFeedback({ evaluation }: { evaluation: Evaluation }) {
  if (evaluation.status !== 'evaluated' || !evaluation.result) {
    const text =
      (evaluation.reason && REASON[evaluation.reason]) ??
      (evaluation.status === 'unavailable'
        ? 'This interview is not using AI, so your answer was saved without an evaluation.'
        : evaluation.status === 'failed'
          ? 'Your answer is saved but could not be evaluated.'
          : 'This answer was not evaluated.');
    return (
      <Alert tone="info" title="No evaluation for this answer">
        {text}
      </Alert>
    );
  }
  const result = evaluation.result;
  const present = DIMENSIONS.filter((d) => result.dimensions[d.key]?.score != null);
  return (
    <div className="space-y-4" data-testid="evaluation">
      {result.suspicious_instructions && (
        <Alert tone="warning">
          Your answer contained text that looked like instructions to the evaluator. It was ignored;
          only the content was judged.
        </Alert>
      )}
      {result.summary && <p className="text-sm text-slate-800">{result.summary}</p>}
      <ul className="space-y-3">
        {present.map((d) => {
          const dim = result.dimensions[d.key];
          return (
            <li key={d.key}>
              <div className="flex items-center justify-between gap-2 text-sm">
                <span className="font-medium text-slate-800">
                  {d.label}
                  {d.group === 'communication' && <Badge>subjective</Badge>}
                </span>
                <span className="text-slate-600">{dim?.score}/10</span>
              </div>
              <ProgressBar value={dim?.score ?? 0} max={10} label={d.label} />
              {dim?.rationale && <p className="mt-0.5 text-xs text-slate-500">{dim.rationale}</p>}
            </li>
          );
        })}
      </ul>
      {DIMENSIONS.length > present.length && (
        <p className="text-xs text-slate-500">
          Not judged for this answer:{' '}
          {DIMENSIONS.filter((d) => !present.includes(d))
            .map((d) => d.label.toLowerCase())
            .join(', ')}
          .
        </p>
      )}
      {result.star && (
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            STAR structure
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {Object.entries(result.star).map(([part, value]) => (
              <li key={part}>
                <Badge
                  tone={
                    value.present === true
                      ? 'success'
                      : value.present === false
                        ? 'warning'
                        : 'neutral'
                  }
                >
                  {part}:{' '}
                  {value.present === true
                    ? 'covered'
                    : value.present === false
                      ? 'missing'
                      : 'not judged'}
                </Badge>
              </li>
            ))}
          </ul>
        </div>
      )}
      <List title="What was right" items={result.correct_points} />
      <List title="Missing or incorrect" items={result.missing_or_incorrect_points} />
      <List title="Strengths" items={result.strengths} />
      <List title="How to improve" items={result.improvements} />
      <p className="text-xs text-slate-500">
        Evaluated by AI; it can be wrong. Scores judge the content of the written answer only.
      </p>
    </div>
  );
}
