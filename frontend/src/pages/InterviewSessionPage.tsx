import { Info } from 'lucide-react';
import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { interviewApi } from '@/api/endpoints';
import {
  keys,
  useApiMutation,
  useCurrentQuestion,
  useInterview,
  useQuestions,
} from '@/api/queries';
import type { AnswerSubmitted, Interview, Question } from '@/api/types';
import { EvaluationFeedback } from '@/components/EvaluationFeedback';
import {
  Alert,
  Badge,
  Button,
  Card,
  ConfirmDialog,
  PageHeader,
  ProgressBar,
  QueryBoundary,
  Spinner,
  TextArea,
} from '@/components/ui';
import { describeError } from '@/lib/errors';
import { titleCase } from '@/lib/format';
import { STATUS_TONE, TYPE_LABEL } from './InterviewsPages';

const MAX_ANSWER = 8000;

export function InterviewSessionPage() {
  const { sessionId = '' } = useParams();
  const interview = useInterview(sessionId);
  return (
    <QueryBoundary query={interview} label="Loading the interview">
      {(data) => <Session interview={data} />}
    </QueryBoundary>
  );
}

function Session({ interview }: { interview: Interview }) {
  const id = interview.id;
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<'cancel' | 'finish' | null>(null);
  const all = [keys.interview(id), keys.interviews, keys.current(id), keys.questions(id)];
  const start = useApiMutation(() => interviewApi.start(id), all);
  const cancel = useApiMutation(() => interviewApi.cancel(id), all);
  const complete = useApiMutation(() => interviewApi.complete(id), [...all, keys.report(id)]);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(describeError(e));
    }
  }

  async function finish() {
    setConfirm(null);
    await run(async () => {
      await complete.mutateAsync(undefined);
      navigate(`/interviews/${id}/report`);
    });
  }

  const running = interview.status === 'in_progress';
  const types = interview.interview_types.map((t) => TYPE_LABEL[t]).join(' + ');
  return (
    <>
      <PageHeader
        title={types}
        description={
          <>
            {titleCase(interview.difficulty)} · {interview.progress.main_questions_total} questions
            {interview.job_title && ` · ${interview.job_title}`} ·{' '}
            <Badge tone={STATUS_TONE[interview.status]}>{titleCase(interview.status)}</Badge>
          </>
        }
        actions={
          (running || interview.status === 'interrupted') && (
            <>
              <Button variant="secondary" onClick={() => setConfirm('finish')}>
                Finish early
              </Button>
              <Button variant="secondary" onClick={() => setConfirm('cancel')}>
                Cancel interview
              </Button>
            </>
          )
        }
      />
      {error && (
        <Alert tone="error" className="mb-4">
          {error}
        </Alert>
      )}
      {interview.mode === 'question_bank' && (
        <Alert tone="info" className="mb-4" title="Practising without AI">
          <ul className="list-inside list-disc">
            {interview.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </Alert>
      )}

      {interview.status === 'created' && (
        <Card title="Ready when you are">
          <p className="mb-4 text-sm text-slate-600">
            Questions are prepared when you start. Answer in your own words; you can skip a
            question, finish early or cancel.
            {interview.use_ai
              ? ' AI will be used if it is available.'
              : ' AI is turned off for this interview, so the question bank is used.'}
          </p>
          <Button
            onClick={() => void run(() => start.mutateAsync(undefined))}
            loading={start.isPending}
          >
            Start interview
          </Button>
        </Card>
      )}

      {interview.status === 'interrupted' && (
        <Card title="Paused">
          <p className="mb-4 text-sm text-slate-600">
            This interview was idle for a while and paused. Nothing was lost: resume to continue
            where you stopped.
          </p>
          <Button
            onClick={() => void run(() => start.mutateAsync(undefined))}
            loading={start.isPending}
          >
            Resume interview
          </Button>
        </Card>
      )}

      {running && <Running interview={interview} onFinish={() => setConfirm('finish')} />}

      {interview.status === 'completed' && (
        <Card title="Interview completed">
          <Link to={`/interviews/${id}/report`}>
            <Button>View your report</Button>
          </Link>
        </Card>
      )}
      {(interview.status === 'cancelled' || interview.status === 'expired') && (
        <Card title={`This interview was ${interview.status}`}>
          <Link to="/interviews/new">
            <Button>Start a new interview</Button>
          </Link>
        </Card>
      )}

      <ConfirmDialog
        open={confirm === 'cancel'}
        title="Cancel this interview?"
        message="Your answers so far are kept, but you will not get a report and the interview cannot be resumed."
        confirmLabel="Cancel interview"
        loading={cancel.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={() =>
          void run(async () => {
            await cancel.mutateAsync(undefined);
            setConfirm(null);
            navigate('/interviews');
          })
        }
      />
      <ConfirmDialog
        open={confirm === 'finish'}
        title="Finish the interview now?"
        message="Questions you have not answered are left out of the score. You will get your report."
        confirmLabel="Finish and get report"
        loading={complete.isPending}
        onCancel={() => setConfirm(null)}
        onConfirm={() => void finish()}
      />
    </>
  );
}

function Running({ interview, onFinish }: { interview: Interview; onFinish: () => void }) {
  const id = interview.id;
  const current = useCurrentQuestion(id, true);
  const history = useQuestions(id);
  const [text, setText] = useState('');
  const [last, setLast] = useState<AnswerSubmitted | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmSkip, setConfirmSkip] = useState(false);
  const submit = useApiMutation(
    (body: { question_id: string; text?: string; skip?: boolean }) => interviewApi.answer(id, body),
    [keys.interview(id), keys.current(id), keys.questions(id), keys.interviews],
  );

  async function send(question: Question, skip: boolean) {
    setError(null);
    try {
      const result = await submit.mutateAsync(
        skip
          ? { question_id: question.id, skip: true }
          : { question_id: question.id, text: text.trim() },
      );
      setLast(result);
      setText('');
    } catch (e) {
      setError(describeError(e));
    }
  }

  const progress = interview.progress;
  const busy = submit.isPending || current.isFetching;
  return (
    <div className="space-y-6">
      <Card>
        <div className="mb-1 flex justify-between text-sm text-slate-600">
          <span>
            Question {Math.min(progress.main_questions_asked, progress.main_questions_total)} of{' '}
            {progress.main_questions_total}
          </span>
          <span>
            {progress.answered} answered · {progress.skipped} skipped
            {progress.followups_asked > 0 && ` · ${progress.followups_asked} follow-up(s)`}
          </span>
        </div>
        <ProgressBar
          value={progress.answered + progress.skipped}
          max={Math.max(progress.main_questions_total, 1)}
          label="Interview progress"
        />
      </Card>

      {last && (
        <Card title="Feedback on your last answer">
          <EvaluationFeedback evaluation={last.evaluation} />
          {last.followups_note && (
            <p className="mt-3 flex items-start gap-2 text-xs text-slate-500">
              <Info className="mt-0.5 size-3.5 shrink-0" aria-hidden /> {last.followups_note}
            </p>
          )}
        </Card>
      )}

      <QueryBoundary query={current} label="Loading the question">
        {(state) =>
          state.question ? (
            <Card
              title={
                state.question.is_followup
                  ? 'Follow-up question'
                  : `Question ${state.question.main_index + 1}`
              }
            >
              <div className="mb-2 flex flex-wrap gap-2">
                <Badge tone="brand">{TYPE_LABEL[state.question.category]}</Badge>
                {state.question.is_followup && (
                  <Badge tone="warning">
                    Follow-up
                    {state.question.followup_kind
                      ? `: ${titleCase(state.question.followup_kind)}`
                      : ''}
                  </Badge>
                )}
                {state.question.source === 'question_bank' && <Badge>Question bank</Badge>}
              </div>
              <p className="mb-4 text-lg text-slate-900" data-testid="question-text">
                {state.question.text}
              </p>
              <TextArea
                label="Your answer"
                rows={8}
                value={text}
                maxLength={MAX_ANSWER}
                onChange={(e) => setText(e.target.value)}
                hint={`${text.length} / ${MAX_ANSWER} characters. Explain your reasoning; a correct, focused answer beats a long one.`}
              />
              {error && (
                <Alert tone="error" className="mt-3">
                  {error}
                </Alert>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  onClick={() => void send(state.question as Question, false)}
                  disabled={text.trim() === '' || busy}
                  loading={submit.isPending}
                >
                  Submit answer
                </Button>
                <Button variant="secondary" onClick={() => setConfirmSkip(true)} disabled={busy}>
                  Skip question
                </Button>
              </div>
              <ConfirmDialog
                open={confirmSkip}
                title="Skip this question?"
                message="A skipped question scores 0 in your report. You cannot come back to it."
                confirmLabel="Skip"
                onCancel={() => setConfirmSkip(false)}
                onConfirm={() => {
                  setConfirmSkip(false);
                  void send(state.question as Question, true);
                }}
              />
            </Card>
          ) : (
            <Card title="You have answered every question">
              <p className="mb-4 text-sm text-slate-600">
                Finish the interview to get your report.
              </p>
              <Button onClick={onFinish}>Finish and get report</Button>
            </Card>
          )
        }
      </QueryBoundary>

      {history.isPending ? (
        <Spinner label="Loading earlier answers" />
      ) : (
        history.data &&
        history.data.some((q) => q.answer) && (
          <Card title="Earlier in this interview">
            <ul className="divide-y divide-slate-100">
              {history.data
                .filter((q) => q.answer)
                .map((q) => (
                  <li key={q.id} className="py-3 text-sm">
                    <p className="font-medium text-slate-900">
                      {q.is_followup && <Badge tone="warning">Follow-up</Badge>} {q.text}
                    </p>
                    <p className="mt-1 whitespace-pre-wrap text-slate-600">
                      {q.answer?.skipped ? <em>Skipped</em> : q.answer?.text}
                    </p>
                  </li>
                ))}
            </ul>
          </Card>
        )
      )}
    </div>
  );
}
