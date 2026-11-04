import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { JOB, JOB_ANALYSIS, MATCH, MATCH_SUMMARY } from './fixtures';
import { api, errorBody, renderApp, signedInHandlers, useHandlers } from './utils';

const jobHandlers = (extra: Parameters<typeof useHandlers> = []) => [
  ...extra, // first: the first matching handler wins, so overrides must precede the defaults
  ...signedInHandlers(),
  http.get(api('/jobs/j1'), () => HttpResponse.json(JOB)),
  http.get(api('/jobs/j1/analysis'), () => HttpResponse.json(JOB_ANALYSIS)),
  http.get(api('/jobs/j1/matches'), () => HttpResponse.json([])),
];

describe('job list', () => {
  it('shows an empty state with a call to action', async () => {
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/jobs'), () => HttpResponse.json([])),
    );
    renderApp('/jobs');
    expect(await screen.findByText('No jobs saved yet')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Add your first job' })).toHaveAttribute(
      'href',
      '/jobs/new',
    );
  });

  it('lists saved jobs with their status', async () => {
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/jobs'), () =>
        HttpResponse.json([
          { ...JOB, description: undefined },
          { ...JOB, id: 'j2', title: 'Data Analyst', company: null, status: 'failed' },
        ]),
      ),
    );
    renderApp('/jobs');
    expect(await screen.findByText('Backend Engineer')).toBeInTheDocument();
    expect(screen.getByText(/Acme Payments/)).toBeInTheDocument();
    expect(screen.getByText('Parsed')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText(/Company not given/)).toBeInTheDocument();
  });
});

describe('adding a job', () => {
  it('requires a description or a link and a minimum length', async () => {
    let posted = 0;
    useHandlers(
      ...signedInHandlers(),
      http.post(api('/jobs'), () => {
        posted += 1;
        return HttpResponse.json(JOB, { status: 201 });
      }),
    );
    renderApp('/jobs/new');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Job title'), 'Engineer');
    await user.click(screen.getByRole('button', { name: 'Save job' }));
    expect(
      await screen.findByText('Paste the job description or give a link to it'),
    ).toBeInTheDocument();
    await user.type(screen.getByLabelText('Job description'), 'too short');
    await user.click(screen.getByRole('button', { name: 'Save job' }));
    expect(await screen.findByText('Write at least 40 characters')).toBeInTheDocument();
    expect(posted).toBe(0);
  });

  it('saves the pasted text and opens the new job', async () => {
    let body: unknown;
    useHandlers(
      ...jobHandlers([
        http.post(api('/jobs'), async ({ request }) => {
          body = await request.json();
          return HttpResponse.json(JOB, { status: 201 });
        }),
      ]),
    );
    renderApp('/jobs/new');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Job title'), 'Backend Engineer');
    await user.type(screen.getByLabelText('Company (optional)'), 'Acme Payments');
    await user.type(
      screen.getByLabelText('Job description'),
      'We need someone who knows Python and PostgreSQL well.',
    );
    await user.click(screen.getByRole('button', { name: 'Save job' }));
    expect(await screen.findByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument();
    expect(body).toEqual({
      title: 'Backend Engineer',
      company: 'Acme Payments',
      description: 'We need someone who knows Python and PostgreSQL well.',
      source_url: null,
    });
  });

  it('sends only the link when no text is pasted, and explains refused sites', async () => {
    let body: Record<string, unknown> = {};
    useHandlers(
      ...signedInHandlers(),
      http.post(api('/jobs'), async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return errorBody(
          'job_platform_not_supported',
          'This site does not allow automated access.',
          422,
        );
      }),
    );
    renderApp('/jobs/new');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Job title'), 'Engineer');
    await user.type(
      screen.getByLabelText(/link to the posting/i),
      'https://www.linkedin.com/jobs/view/1',
    );
    await user.click(screen.getByRole('button', { name: 'Save job' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Paste the job description text instead',
    );
    expect(body.description).toBeNull();
    expect(body.source_url).toBe('https://www.linkedin.com/jobs/view/1');
  });
});

describe('job detail and analysis', () => {
  it('groups requirements by how the posting ranks them and flags AI additions', async () => {
    useHandlers(...jobHandlers());
    renderApp('/jobs/j1');
    expect(await screen.findByRole('heading', { name: 'Backend Engineer' })).toBeInTheDocument();
    const required = (await screen.findByText('Required')).parentElement as HTMLElement;
    expect(within(required).getByText('Python (or Java)')).toBeInTheDocument();
    expect(within(required).getByText('PostgreSQL')).toBeInTheDocument();
    const nice = screen.getByText('Nice to have').parentElement as HTMLElement;
    expect(within(nice).getByText('AWS')).toBeInTheDocument();
    expect(within(nice).getByText('Prefect · AI')).toBeInTheDocument();
    const unclear = screen.getByText('Mentioned, importance not stated')
      .parentElement as HTMLElement;
    expect(within(unclear).getByText('Git')).toBeInTheDocument();
    expect(screen.queryByText('Kafka')).toBeNull(); // company-background mentions are not requirements
    expect(screen.getByText(/mentioned without saying whether/)).toBeInTheDocument();
    expect(screen.getByText('Senior (stated)')).toBeInTheDocument();
  });

  it('shows an error state for a job that does not exist', async () => {
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/jobs/zzz'), () => errorBody('job_not_found', 'Job not found', 404)),
    );
    renderApp('/jobs/zzz');
    expect(await screen.findByRole('alert')).toHaveTextContent('Job not found');
  });

  it('asks for AI consent only when AI is requested and sends the choice', async () => {
    const bodies: unknown[] = [];
    useHandlers(
      ...jobHandlers([
        http.post(api('/jobs/j1/analyze'), async ({ request }) => {
          bodies.push(await request.json());
          return bodies.length === 1
            ? HttpResponse.json(JOB_ANALYSIS)
            : errorBody('ai_unavailable', 'x', 503);
        }),
      ]),
    );
    renderApp('/jobs/j1');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Analyse again' }));
    expect(screen.queryByLabelText(/allow the job text/i)).toBeNull();
    await user.click(screen.getByLabelText(/also ask the ai/i));
    await user.click(screen.getByLabelText(/allow the job text/i));
    await user.click(screen.getByRole('button', { name: 'Analyse again' }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies).toEqual([
      { use_ai: false, allow_external_ai: false },
      { use_ai: true, allow_external_ai: true },
    ]);
    expect(await screen.findByRole('alert')).toHaveTextContent('AI features are not available');
  });

  it('edits the title and text', async () => {
    let body: unknown;
    useHandlers(
      ...jobHandlers([
        http.put(api('/jobs/j1'), async ({ request }) => {
          body = await request.json();
          return HttpResponse.json({ ...JOB, title: 'Senior Backend Engineer' });
        }),
      ]),
    );
    renderApp('/jobs/j1');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Edit' }));
    expect(screen.getByText(/Match reports you already made are kept/)).toBeInTheDocument();
    const title = screen.getByLabelText('Job title');
    await user.clear(title);
    await user.type(title, 'Senior Backend Engineer');
    await user.click(screen.getByRole('button', { name: 'Save changes' }));
    await waitFor(() =>
      expect(body).toMatchObject({ title: 'Senior Backend Engineer', company: 'Acme Payments' }),
    );
  });

  it('confirms before deleting and returns to the list', async () => {
    let deleted = 0;
    useHandlers(
      ...jobHandlers([
        http.delete(api('/jobs/j1'), () => {
          deleted += 1;
          return new HttpResponse(null, { status: 204 });
        }),
        http.get(api('/jobs'), () => HttpResponse.json([])),
      ]),
    );
    renderApp('/jobs/j1');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Delete' }));
    expect(screen.getByRole('alertdialog')).toHaveTextContent(
      'all of its match reports are permanently deleted',
    );
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(deleted).toBe(0);
    await user.click(screen.getByRole('button', { name: 'Delete' }));
    await user.click(
      within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete' }),
    );
    expect(await screen.findByText('No jobs saved yet')).toBeInTheDocument();
    expect(deleted).toBe(1);
  });

  it('links to a practice interview for the job', async () => {
    useHandlers(...jobHandlers());
    renderApp('/jobs/j1');
    expect(await screen.findByRole('link', { name: 'Practise for this job' })).toHaveAttribute(
      'href',
      '/interviews/new?job=j1',
    );
  });
});

describe('match reports', () => {
  it('invites the first comparison when none exists', async () => {
    useHandlers(...jobHandlers());
    renderApp('/jobs/j1');
    expect(await screen.findByText(/No comparison yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Compare with my profile' })).toBeInTheDocument();
  });

  it('creates a comparison without AI by default and shows the explained report', async () => {
    let created = false;
    let body: unknown;
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/jobs/j1'), () => HttpResponse.json(JOB)),
      http.get(api('/jobs/j1/analysis'), () => HttpResponse.json(JOB_ANALYSIS)),
      http.get(api('/jobs/j1/matches'), () => HttpResponse.json(created ? [MATCH_SUMMARY] : [])),
      http.get(api('/jobs/j1/matches/m1'), () => HttpResponse.json(MATCH)),
      http.post(api('/jobs/j1/match'), async ({ request }) => {
        body = await request.json();
        created = true;
        return HttpResponse.json(MATCH, { status: 201 });
      }),
    );
    renderApp('/jobs/j1');
    await userEvent
      .setup()
      .click(await screen.findByRole('button', { name: 'Compare with my profile' }));
    const report = await screen.findByTestId('match-report');
    expect(body).toEqual({ use_ai: false, allow_external_ai: false });
    expect(within(report).getByText('77')).toBeInTheDocument();
    expect(within(report).getByText(/77\/100 = Required skills 43.8/)).toBeInTheDocument();
    expect(within(report).getByText(/not the chance of getting the job/)).toBeInTheDocument();
    expect(within(report).getByText('Shown in your material')).toBeInTheDocument();
    expect(within(report).getByText('No evidence found')).toBeInTheDocument();
    expect(within(report).getAllByText('profile: Shop API').length).toBeGreaterThan(0);
    expect(within(report).getByText(/Job text: “Experience with Python”/)).toBeInTheDocument();
    expect(within(report).getByText('Not assessed')).toBeInTheDocument(); // the experience dimension
    expect(within(report).getByText(/Not available: github \(not connected\)/)).toBeInTheDocument();
    expect(within(report).getByText(/No score guarantees an interview/)).toBeInTheDocument();
  });

  it('shows an unscored report honestly and never invents a number', async () => {
    const unscored = {
      ...MATCH,
      overall_score: null,
      report: {
        ...MATCH.report,
        score: {
          ...MATCH.report.score,
          score: null,
          status: 'insufficient_evidence' as const,
          confidence: 'none' as const,
          explanation: 'There is no candidate evidence yet, so no score was calculated.',
        },
      },
    };
    useHandlers(
      ...jobHandlers([
        http.get(api('/jobs/j1/matches'), () =>
          HttpResponse.json([{ ...MATCH_SUMMARY, overall_score: null }]),
        ),
        http.get(api('/jobs/j1/matches/m1'), () => HttpResponse.json(unscored)),
      ]),
    );
    renderApp('/jobs/j1');
    const report = await screen.findByTestId('match-report');
    expect(within(report).getByText('Not scored')).toBeInTheDocument();
    expect(within(report).getByText(/no score was calculated/)).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /not scored/ })).toBeInTheDocument();
  });

  it('labels AI advice as such and keeps it apart from the score', async () => {
    const advised = {
      ...MATCH,
      ai_advice: {
        summary: 'Focus on PostgreSQL first.',
        improvement_areas: [],
        learning_topics: [{ topic: 'Indexes', reason: 'Common interview topic' }],
        project_ideas: [{ title: 'Orders DB', description: 'Model an orders schema' }],
        interview_preparation: [],
        caveats: [],
        notice: 'AI-generated suggestions. The scores above are authoritative.',
      },
    };
    useHandlers(
      ...jobHandlers([
        http.get(api('/jobs/j1/matches'), () => HttpResponse.json([MATCH_SUMMARY])),
        http.get(api('/jobs/j1/matches/m1'), () => HttpResponse.json(advised)),
      ]),
    );
    renderApp('/jobs/j1');
    const heading = await screen.findByRole('heading', { name: 'AI advice' });
    const card = heading.closest('section') as HTMLElement;
    expect(within(card).getByText(/scores above are authoritative/)).toBeInTheDocument();
    expect(within(card).getByText('Focus on PostgreSQL first.')).toBeInTheDocument();
  });

  it('requests AI advice with explicit consent and reports provider problems', async () => {
    let body: unknown;
    useHandlers(
      ...jobHandlers([
        http.post(api('/jobs/j1/match'), async ({ request }) => {
          body = await request.json();
          return errorBody('ai_consent_required', 'consent', 403);
        }),
      ]),
    );
    renderApp('/jobs/j1');
    const user = userEvent.setup();
    await user.click(await screen.findByLabelText(/add plain-language ai advice/i));
    await user.click(screen.getByRole('button', { name: 'Compare with my profile' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Tick the consent box');
    await user.click(screen.getByLabelText(/allow this summary/i));
    await user.click(screen.getByRole('button', { name: 'Compare with my profile' }));
    await waitFor(() => expect(body).toEqual({ use_ai: true, allow_external_ai: true }));
  });

  it('lets the user open an older saved comparison', async () => {
    const older = {
      ...MATCH,
      id: 'm0',
      overall_score: 40,
      report: {
        ...MATCH.report,
        score: { ...MATCH.report.score, score: 40, explanation: '40/100 = older' },
      },
    };
    useHandlers(
      ...jobHandlers([
        http.get(api('/jobs/j1/matches'), () =>
          HttpResponse.json([
            MATCH_SUMMARY,
            { ...MATCH_SUMMARY, id: 'm0', overall_score: 40, created_at: '2026-02-01T10:00:00Z' },
          ]),
        ),
        http.get(api('/jobs/j1/matches/m1'), () => HttpResponse.json(MATCH)),
        http.get(api('/jobs/j1/matches/m0'), () => HttpResponse.json(older)),
      ]),
    );
    renderApp('/jobs/j1');
    expect(await screen.findByText(/77\/100 = Required/)).toBeInTheDocument();
    await userEvent.setup().selectOptions(screen.getByLabelText('Saved comparisons'), 'm0');
    expect(await screen.findByText('40/100 = older')).toBeInTheDocument();
  });
});
