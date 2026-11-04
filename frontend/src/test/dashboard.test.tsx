import { screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { JOB, PROFILE, RESUME } from './fixtures';
import {
  api,
  emptyAccountHandlers,
  errorBody,
  renderApp,
  signedInHandlers,
  useHandlers,
} from './utils';

const interviews = [
  {
    id: 'i3',
    status: 'in_progress',
    interview_types: ['hr'],
    difficulty: 'beginner',
    job_title: null,
    mode: 'ai',
    created_at: '2026-04-03T09:00:00Z',
    completed_at: null,
  },
  {
    id: 'i2',
    status: 'completed',
    interview_types: ['technical'],
    difficulty: 'advanced',
    job_title: 'Backend Engineer',
    mode: 'ai',
    created_at: '2026-04-02T09:00:00Z',
    completed_at: '2026-04-02T09:40:00Z',
  },
  {
    id: 'i1',
    status: 'completed',
    interview_types: ['technical'],
    difficulty: 'beginner',
    job_title: null,
    mode: 'ai',
    created_at: '2026-04-01T09:00:00Z',
    completed_at: '2026-04-01T09:40:00Z',
  },
];
const reportWith = (score: number | null) => ({
  id: 'r',
  session_id: 'x',
  created_at: '2026-04-02T09:40:00Z',
  overall_score: score,
  report: {},
});

describe('dashboard', () => {
  it('shows zeros and a getting-started list for an empty account (no placeholder numbers)', async () => {
    useHandlers(...emptyAccountHandlers());
    renderApp('/');
    expect(await screen.findByRole('heading', { name: 'Welcome, Ada' })).toBeInTheDocument();
    const jobs = (await screen.findByText('Saved jobs', { selector: 'p' })).closest(
      'a',
    ) as HTMLElement;
    await screen.findByText('You have not started an interview yet.');
    expect(within(jobs).getByText('0')).toBeInTheDocument();
    const steps = (await screen.findByText('Next steps')).closest('section') as HTMLElement;
    expect(
      within(steps).getByRole('link', { name: 'Add your skills and experience' }),
    ).toHaveAttribute('href', '/profile');
    expect(within(steps).getByRole('link', { name: 'Upload your CV' })).toBeInTheDocument();
    expect(
      within(steps).getByRole('link', { name: 'Practise your first interview' }),
    ).toHaveAttribute('href', '/interviews/new');
    expect(screen.getByText(/Still missing: A headline, An experience level/)).toBeInTheDocument();
    expect(screen.queryByText('Your progress')).toBeNull(); // no chart without interviews
  });

  it('reflects the real account: counts, completeness, recent items and a score chart', async () => {
    useHandlers(
      http.get(api('/profile'), () => HttpResponse.json(PROFILE)),
      http.get(api('/resumes'), () =>
        HttpResponse.json([RESUME, { ...RESUME, id: 'r2', has_analysis: false }]),
      ),
      http.get(api('/jobs'), () =>
        HttpResponse.json([JOB, { ...JOB, id: 'j2', title: 'Data Analyst', company: null }]),
      ),
      http.get(api('/interviews'), () => HttpResponse.json(interviews)),
      http.get(api('/interviews/i2/report'), () => HttpResponse.json(reportWith(80))),
      http.get(api('/interviews/i1/report'), () => HttpResponse.json(reportWith(60))),
      http.get(api('/integrations/github'), () => errorBody('source_not_connected', 'x', 404)),
      http.get(api('/integrations/portfolio'), () => errorBody('source_not_connected', 'x', 404)),
      ...signedInHandlers(),
    );
    renderApp('/');
    const resumes = (await screen.findByText('Resumes', { selector: 'p' })).closest(
      'a',
    ) as HTMLElement;
    await screen.findByText('1 analysed');
    expect(within(resumes).getByText('2')).toBeInTheDocument();
    const interviewsStat = screen
      .getByText('Interviews', { selector: 'p' })
      .closest('a') as HTMLElement;
    expect(within(interviewsStat).getByText('3')).toBeInTheDocument();
    expect(within(interviewsStat).getByText('2 completed')).toBeInTheDocument();
    expect(screen.getByText('7 of 7 sections filled in')).toBeInTheDocument();
    expect(
      await screen.findByRole('table', {
        name: /overall score of each completed interview/i,
        hidden: true,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText('Average score').closest('div')).toHaveTextContent('70');
    expect(screen.getByRole('link', { name: /Technical · Advanced/ })).toHaveAttribute(
      'href',
      '/interviews/i2/report',
    );
    expect(screen.getByRole('link', { name: /HR · Beginner/ })).toHaveAttribute(
      'href',
      '/interviews/i3',
    );
    expect(screen.getByRole('link', { name: 'Data Analyst' })).toBeInTheDocument();
    const steps = screen.getByText('Next steps').closest('section') as HTMLElement;
    await within(steps).findByRole('link', { name: 'Connect GitHub or a portfolio' }); // the only open step
    expect(within(steps).queryByRole('link', { name: 'Upload your CV' })).toBeNull();
  });

  it('keeps working when one data source fails, and says so', async () => {
    useHandlers(
      http.get(api('/jobs'), () =>
        errorBody('internal_error', 'An unexpected error occurred', 500),
      ),
      ...emptyAccountHandlers(),
    );
    renderApp('/');
    expect(
      await screen.findByText('Some data could not be loaded, so next steps may be incomplete.'),
    ).toBeInTheDocument();
    const jobs = screen.getByText('Saved jobs', { selector: 'p' }).closest('a') as HTMLElement;
    expect(within(jobs).getByText('—')).toBeInTheDocument(); // not a fake zero
    expect(screen.getByText('You have not started an interview yet.')).toBeInTheDocument(); // the rest still renders
  });
});
