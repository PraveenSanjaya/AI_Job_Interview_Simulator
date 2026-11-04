/**
 * End-to-end candidate journeys: the whole app (router, auth, queries, forms) runs against a
 * small stateful in-memory API, so a journey crosses many screens and many requests.
 */
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse, type HttpHandler } from 'msw';
import type { Interview, Match, Question } from '@/api/types';
import { JOB_ANALYSIS, MATCH, PROFILE } from './fixtures';
import { api, errorBody, renderApp, useHandlers, USER } from './utils';

const PASSWORD = 'S3cure-passphrase-42';

/** One fake backend per test. `ai` decides whether interviews are evaluated. */
function fakeBackend({ ai }: { ai: boolean }) {
  const state = {
    registered: false,
    profile: {
      ...PROFILE,
      full_name: 'Ada Lovelace',
      skills: [],
      projects: [],
      work_experience: [],
      education: [],
      headline: null,
      experience_level: null,
      preferred_roles: [],
    } as typeof PROFILE,
    jobs: [] as {
      id: string;
      title: string;
      company: string | null;
      description: string;
      source_url: null;
      status: 'parsed';
      has_analysis: true;
      created_at: string;
      updated_at: string;
    }[],
    matches: [] as Match[],
    interview: null as Interview | null,
    questions: [] as Question[],
    answers: new Map<string, { text: string | null; skipped: boolean }>(),
    reports: new Map<string, unknown>(),
  };
  const bank = [
    'How would you index a large orders table?',
    'Describe a time you debugged a production problem.',
  ];

  const asked = () => state.questions.filter((q) => q.asked_at);
  const open = () => asked().find((q) => !state.answers.has(q.id)) ?? null;
  const progress = () => ({
    main_questions_total: bank.length,
    main_questions_asked: asked().filter((q) => !q.is_followup).length,
    answered: [...state.answers.values()].filter((a) => !a.skipped).length,
    skipped: [...state.answers.values()].filter((a) => a.skipped).length,
    followups_asked: asked().filter((q) => q.is_followup).length,
    remaining_main_questions: state.questions.filter((q) => !q.asked_at).length,
  });
  const snapshot = (): Interview => ({ ...(state.interview as Interview), progress: progress() });
  const evaluation = (answerId: string, questionId: string) =>
    ai
      ? {
          id: `e-${answerId}`,
          answer_id: answerId,
          question_id: questionId,
          status: 'evaluated' as const,
          reason: null,
          result: {
            dimensions: {
              technical_correctness: { score: 8, rationale: 'Correct.' },
              clarity: { score: 8, rationale: 'Clear.' },
            },
            star: null,
            correct_points: ['The core idea'],
            missing_or_incorrect_points: [],
            strengths: [],
            improvements: ['Add an example'],
            summary: 'A solid answer.',
            suspicious_instructions: false,
          },
        }
      : {
          id: `e-${answerId}`,
          answer_id: answerId,
          question_id: questionId,
          status: 'unavailable' as const,
          reason: 'ai_not_used:provider_unavailable',
          result: null,
        };

  const handlers: HttpHandler[] = [
    http.post(api('/auth/register'), () => {
      state.registered = true;
      return HttpResponse.json({ message: 'ok' }, { status: 202 });
    }),
    http.post(api('/auth/login'), () =>
      state.registered
        ? HttpResponse.json({
            access_token: 'a1',
            refresh_token: 'r1',
            token_type: 'bearer',
            expires_in: 1800,
          })
        : errorBody('invalid_credentials', 'Invalid email or password', 401),
    ),
    http.get(api('/auth/me'), () => HttpResponse.json(USER)),
    http.post(api('/auth/refresh'), () =>
      HttpResponse.json({
        access_token: 'a2',
        refresh_token: 'r2',
        token_type: 'bearer',
        expires_in: 1800,
      }),
    ),
    http.post(api('/auth/logout'), () => new HttpResponse(null, { status: 204 })),

    http.get(api('/profile'), () => HttpResponse.json(state.profile)),
    http.put(api('/profile'), async ({ request }) => {
      state.profile = {
        ...state.profile,
        ...((await request.json()) as object),
      } as typeof state.profile;
      return HttpResponse.json(state.profile);
    }),
    http.get(api('/resumes'), () => HttpResponse.json([])),
    http.get(api('/integrations/github'), () => errorBody('source_not_connected', 'x', 404)),
    http.get(api('/integrations/portfolio'), () => errorBody('source_not_connected', 'x', 404)),

    http.get(api('/jobs'), () => HttpResponse.json(state.jobs)),
    http.post(api('/jobs'), async ({ request }) => {
      const body = (await request.json()) as {
        title: string;
        company: string | null;
        description: string;
      };
      const job = {
        id: 'j1',
        title: body.title,
        company: body.company,
        description: body.description,
        source_url: null,
        status: 'parsed' as const,
        has_analysis: true as const,
        created_at: '2026-05-01T00:00:00Z',
        updated_at: '2026-05-01T00:00:00Z',
      };
      state.jobs.push(job);
      return HttpResponse.json(job, { status: 201 });
    }),
    http.get(api('/jobs/j1'), () => HttpResponse.json(state.jobs[0])),
    http.get(api('/jobs/j1/analysis'), () => HttpResponse.json(JOB_ANALYSIS)),
    http.get(api('/jobs/j1/matches'), () =>
      HttpResponse.json(
        state.matches.map((m) => ({
          id: m.id,
          job_id: 'j1',
          created_at: m.created_at,
          overall_score: m.overall_score,
          score_status: 'scored',
          confidence: m.confidence,
        })),
      ),
    ),
    http.post(api('/jobs/j1/match'), () => {
      const hasPython = state.profile.skills.some((s) => s.name === 'Python');
      const match: Match = {
        ...MATCH,
        id: `m${state.matches.length + 1}`,
        overall_score: hasPython ? 90 : 20,
      };
      match.report = {
        ...MATCH.report,
        score: {
          ...MATCH.report.score,
          score: match.overall_score,
          explanation: `${match.overall_score}/100 from your recorded skills`,
        },
      };
      state.matches.unshift(match);
      return HttpResponse.json(match, { status: 201 });
    }),
    http.get(api('/jobs/j1/matches/:id'), ({ params }) =>
      HttpResponse.json(state.matches.find((m) => m.id === params.id) as object),
    ),

    http.get(api('/interviews'), () =>
      HttpResponse.json(
        state.interview ? [{ ...state.interview, completed_at: state.interview.completed_at }] : [],
      ),
    ),
    http.post(api('/interviews'), async ({ request }) => {
      const body = (await request.json()) as Partial<Interview> & {
        interview_types: Interview['interview_types'];
      };
      state.interview = {
        id: 'i1',
        status: 'created',
        interview_types: body.interview_types,
        difficulty: (body.difficulty ?? 'intermediate') as Interview['difficulty'],
        question_count: bank.length,
        max_followups: 1,
        job_id: body.job_id ?? null,
        job_title: body.job_id ? 'Backend Engineer' : null,
        use_ai: true,
        consent_external_ai: false,
        mode: null,
        ai_status: null,
        adaptive_followups: null,
        notes: [],
        progress: progress(),
        created_at: '2026-05-01T09:00:00Z',
        started_at: null,
        completed_at: null,
      };
      return HttpResponse.json(snapshot(), { status: 201 });
    }),
    http.get(api('/interviews/i1'), () => HttpResponse.json(snapshot())),
    http.post(api('/interviews/i1/start'), () => {
      const interview = state.interview as Interview;
      interview.status = 'in_progress';
      interview.mode = ai ? 'ai' : 'question_bank';
      interview.adaptive_followups = ai;
      interview.notes = ai
        ? []
        : [
            'No AI provider is configured; the question bank is used and answers are saved without evaluation.',
          ];
      state.questions = bank.map((text, i) => ({
        id: `q${i + 1}`,
        main_index: i,
        followup_index: 0,
        is_followup: false,
        followup_kind: null,
        category: 'technical' as const,
        text,
        source: ai ? ('ai' as const) : ('question_bank' as const),
        skill_tags: [],
        asked_at: i === 0 ? '2026-05-01T09:01:00Z' : null,
      }));
      return HttpResponse.json(snapshot());
    }),
    http.get(api('/interviews/i1/current-question'), () => {
      const question = open();
      return HttpResponse.json({
        status: state.interview?.status,
        question,
        all_questions_answered: !question && state.questions.length > 0,
      });
    }),
    http.get(api('/interviews/i1/questions'), () =>
      HttpResponse.json(
        asked().map((q) => ({
          ...q,
          answer: state.answers.has(q.id)
            ? { id: `a-${q.id}`, ...state.answers.get(q.id), submitted_at: '2026-05-01T09:05:00Z' }
            : null,
        })),
      ),
    ),
    http.post(api('/interviews/i1/answers'), async ({ request }) => {
      const body = (await request.json()) as { question_id: string; text?: string; skip?: boolean };
      const current = open();
      if (!current || current.id !== body.question_id)
        return errorBody('not_current_question', 'That is not the current question', 409);
      state.answers.set(current.id, { text: body.text ?? null, skipped: Boolean(body.skip) });
      let next: Question | null = null;
      let followUp = false;
      if (ai && !body.skip && !current.is_followup) {
        next = {
          ...current,
          id: `${current.id}f`,
          followup_index: 1,
          is_followup: true,
          followup_kind: 'example',
          text: 'Can you give a concrete example from your own work?',
          asked_at: '2026-05-01T09:06:00Z',
        };
        state.questions.splice(state.questions.indexOf(current) + 1, 0, next);
        followUp = true;
      } else {
        next = state.questions.find((q) => !q.asked_at) ?? null;
        if (next) next.asked_at = '2026-05-01T09:06:00Z';
      }
      return HttpResponse.json(
        {
          answer: { id: `a-${current.id}`, text: body.text ?? null, skipped: Boolean(body.skip) },
          evaluation: body.skip
            ? {
                id: 'e',
                answer_id: 'a',
                question_id: current.id,
                status: 'not_evaluated',
                reason: 'skipped',
                result: null,
              }
            : evaluation(`a-${current.id}`, current.id),
          follow_up_asked: followUp,
          followups_note: ai
            ? null
            : 'Adaptive follow-ups are unavailable: this interview uses the question bank.',
          next_question: next,
          all_questions_answered: !next,
          progress: progress(),
        },
        { status: 201 },
      );
    }),
    http.post(api('/interviews/i1/complete'), () => {
      const interview = state.interview as Interview;
      interview.status = 'completed';
      interview.completed_at = '2026-05-01T09:30:00Z';
      const score = ai ? 80 : null;
      const body = {
        id: 'rep1',
        session_id: 'i1',
        created_at: '2026-05-01T09:30:00Z',
        overall_score: score,
        report: {
          session_id: 'i1',
          interview_types: ['technical'],
          difficulty: 'intermediate',
          mode: interview.mode,
          job_title: interview.job_title,
          counts: {
            main_questions_planned: 2,
            main_questions_asked: 2,
            answered: 2,
            skipped: 0,
            followups_asked: ai ? 1 : 0,
            followups_answered: 0,
            evaluated_answers: ai ? 3 : 0,
            not_evaluated_answers: ai ? 0 : 2,
          },
          overall_score: score,
          score_status: ai ? 'scored' : 'not_evaluated',
          score_explanation: ai
            ? '80/100 = mean of 2 question score(s) (8.0, 8.0) x 10.'
            : 'No score was calculated because none of the answers could be evaluated.',
          dimension_scores: {},
          group_scores: ai ? { knowledge: { score: 8, subjective: false, note: 'Content.' } } : {},
          category_scores: ai ? { technical: 8 } : {},
          star_summary: null,
          strong_answers: [],
          weak_answers: [],
          not_evaluated: [],
          knowledge_gaps: [],
          study_topics: [],
          practice_questions: [],
          ai_feedback: null,
          ai_feedback_status: ai ? 'not_requested' : 'unavailable:question_bank_session',
          calculation_notes: [],
          disclaimer:
            'A mock-interview score is practice feedback, not a predictor of any real hiring outcome.',
        },
      };
      state.reports.set('i1', body);
      return HttpResponse.json(body);
    }),
    http.get(api('/interviews/i1/report'), () =>
      HttpResponse.json(state.reports.get('i1') as object),
    ),
  ];
  return { state, handlers };
}

async function register(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('link', { name: 'Create an account' }));
  await user.type(await screen.findByLabelText('Full name'), 'Ada Lovelace');
  await user.type(screen.getByLabelText('Email'), 'ada@example.com');
  await user.type(screen.getByLabelText('Password'), PASSWORD);
  await user.click(screen.getByRole('button', { name: 'Create account' }));
}

describe('candidate journeys', () => {
  it(
    'new candidate: register, build a profile, add a job, compare, practise with AI and read the report',
    { timeout: 60_000 },
    async () => {
      const { state, handlers } = fakeBackend({ ai: true });
      useHandlers(...handlers);
      renderApp('/');
      const user = userEvent.setup();

      // 1. sign up (lands on the profile page)
      await register(user);
      expect(await screen.findByRole('heading', { name: 'Your profile' })).toBeInTheDocument();

      // 2. add a skill and save
      await user.click(await screen.findByRole('button', { name: /add skill/i }));
      await user.type(screen.getByLabelText('Skill'), 'Python');
      await user.click(screen.getByRole('button', { name: 'Save profile' }));
      expect(await screen.findByText('Profile saved.')).toBeInTheDocument();
      expect(state.profile.skills.map((s) => s.name)).toEqual(['Python']);

      // 3. save a job from the jobs page
      await user.click(screen.getByRole('link', { name: 'Jobs' }));
      await user.click(await screen.findByRole('link', { name: 'Add your first job' }));
      await user.type(await screen.findByLabelText('Job title'), 'Backend Engineer');
      await user.type(screen.getByLabelText('Company (optional)'), 'Acme Payments');
      await user.type(
        screen.getByLabelText('Job description'),
        'We need a developer who knows Python and PostgreSQL well.',
      );
      await user.click(screen.getByRole('button', { name: 'Save job' }));
      expect(await screen.findByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument();
      expect(await screen.findByText('Python (or Java)')).toBeInTheDocument();

      // 4. compare with the profile: the score comes from the recorded skills
      await user.click(screen.getByRole('button', { name: 'Compare with my profile' }));
      expect(await screen.findByText(/90\/100 from your recorded skills/)).toBeInTheDocument();

      // 5. practise for this job
      await user.click(screen.getByRole('link', { name: 'Practise for this job' }));
      await screen.findByRole('heading', { name: 'New interview' });
      expect(screen.getByLabelText('Target job (optional)')).toHaveValue('j1');
      await user.click(screen.getByRole('button', { name: 'Create interview' }));
      await user.click(await screen.findByRole('button', { name: 'Start interview' }));
      expect(await screen.findByTestId('question-text')).toHaveTextContent(
        'How would you index a large orders table?',
      );

      // 6. answer; the AI asks a follow-up and shows feedback
      await user.type(
        screen.getByLabelText('Your answer'),
        'I would add a composite index on the filter columns.',
      );
      await user.click(screen.getByRole('button', { name: 'Submit answer' }));
      expect(await screen.findByText('Follow-up question')).toBeInTheDocument();
      expect(
        within(await screen.findByTestId('evaluation')).getByText('A solid answer.'),
      ).toBeInTheDocument();
      await user.type(
        screen.getByLabelText('Your answer'),
        'On the orders table we indexed customer and date.',
      );
      await user.click(screen.getByRole('button', { name: 'Submit answer' }));

      // 7. second question (skip it), then finish
      await waitFor(() =>
        expect(screen.getByTestId('question-text')).toHaveTextContent(
          'Describe a time you debugged',
        ),
      );
      await user.type(screen.getByLabelText('Your answer'), 'I traced a slow query with the logs.');
      await user.click(screen.getByRole('button', { name: 'Submit answer' }));
      await screen.findByText('Follow-up question');
      await user.click(screen.getByRole('button', { name: 'Skip question' }));
      await user.click(
        within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Skip' }),
      );
      await user.click(await screen.findByRole('button', { name: 'Finish and get report' }));
      await user.click(
        within(await screen.findByRole('alertdialog')).getByRole('button', {
          name: 'Finish and get report',
        }),
      );

      // 8. the report
      expect(await screen.findByTestId('overall-score')).toHaveTextContent('80');
      expect(screen.getByText(/80\/100 = mean of 2 question score/)).toBeInTheDocument();
      expect(screen.getByText(/not a predictor of any real hiring outcome/)).toBeInTheDocument();

      // 9. history and dashboard reflect the completed interview
      await user.click(screen.getByRole('link', { name: 'All interviews' }));
      expect(await screen.findByRole('link', { name: 'View report' })).toBeInTheDocument();
      await user.click(screen.getByRole('link', { name: 'Dashboard' }));
      expect(await screen.findByText('1 completed')).toBeInTheDocument();
    },
  );

  it(
    'works end to end without any AI: honest notices, no scores, no follow-ups',
    { timeout: 30_000 },
    async () => {
      const { handlers } = fakeBackend({ ai: false });
      useHandlers(...handlers);
      renderApp('/');
      const user = userEvent.setup();
      await register(user);
      await screen.findByRole('heading', { name: 'Your profile' });

      await user.click(screen.getByRole('link', { name: 'Interviews' }));
      await user.click(await screen.findByRole('link', { name: 'Start your first interview' }));
      await user.click(await screen.findByRole('button', { name: 'Create interview' }));
      await user.click(await screen.findByRole('button', { name: 'Start interview' }));
      expect(await screen.findByText('Practising without AI')).toBeInTheDocument();

      for (let i = 0; i < 2; i += 1) {
        await user.type(await screen.findByLabelText('Your answer'), `My answer number ${i + 1}`);
        await user.click(screen.getByRole('button', { name: 'Submit answer' }));
        expect(await screen.findByText('No evaluation for this answer')).toBeInTheDocument();
        expect(screen.queryByTestId('evaluation')).toBeNull();
        expect(screen.queryByText('Follow-up question')).toBeNull();
      }
      await user.click(await screen.findByRole('button', { name: 'Finish and get report' }));
      await user.click(
        within(await screen.findByRole('alertdialog')).getByRole('button', {
          name: 'Finish and get report',
        }),
      );

      expect(await screen.findByText('Not scored')).toBeInTheDocument();
      expect(screen.getByText('Why there is no score')).toBeInTheDocument();
      expect(screen.queryByTestId('overall-score')).toBeNull();
    },
  );

  it('an expired session sends the user to sign in again with an explanation', async () => {
    // After registering, the server stops accepting the session: 401, and the refresh is refused.
    useHandlers(
      http.get(api('/profile'), () => errorBody('unauthorized', 'Token expired', 401)),
      http.post(api('/auth/refresh'), () =>
        errorBody('invalid_refresh_token', 'Refresh token revoked', 401),
      ),
      ...fakeBackend({ ai: false }).handlers,
    );
    renderApp('/');
    await register(userEvent.setup());
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
    expect(await screen.findByText('Your session expired')).toBeInTheDocument();
  });

  it('a returning visitor is taken straight back into the app after a reload', async () => {
    const { handlers } = fakeBackend({ ai: false });
    window.localStorage.setItem('ajis.refresh_token', 'r1');
    useHandlers(...handlers);
    renderApp('/jobs');
    expect(await screen.findByText('No jobs saved yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign out/i })).toBeInTheDocument();
  });
});
