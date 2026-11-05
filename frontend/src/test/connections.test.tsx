import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import type { GitHubSource, PortfolioSource } from '@/api/types';
import {
  api,
  errorBody,
  renderApp,
  signedInHandlers,
  useHandlers as useBaseHandlers,
} from './utils';

/** Every test starts with no resumes and no saved analyses unless it says otherwise. */
const useHandlers = (...handlers: Parameters<typeof useBaseHandlers>) =>
  useBaseHandlers(
    ...handlers,
    http.get(api('/integrations/analysis'), () => HttpResponse.json([])),
    http.get(api('/resumes'), () => HttpResponse.json([])),
  );

const GITHUB: GitHubSource = {
  source_ref: 'janedoe',
  fetched_at: '2026-03-01T10:00:00Z',
  snapshot: {
    login: 'janedoe',
    profile_url: 'https://github.com/janedoe',
    bio: 'Backend engineer',
    followers: 12,
    public_repos_total: 4,
    repos_listed: 4,
    repos_truncated: false,
    repositories: [
      {
        name: 'interview-sim',
        url: 'https://github.com/janedoe/interview-sim',
        description: 'AI mock interviews',
        primary_language: 'Python',
        topics: [],
        stars: 25,
        is_fork: false,
        is_archived: false,
        pushed_at: null,
      },
      {
        name: 'forked-lib',
        url: 'https://github.com/janedoe/forked-lib',
        description: 'A fork',
        primary_language: 'Go',
        topics: [],
        stars: 900,
        is_fork: true,
        is_archived: false,
        pushed_at: null,
      },
    ],
    language_distribution: { Python: 2, Shell: 1 },
    total_stars_own_repos: 26,
    activity: {
      own_repos_pushed_last_90_days: 1,
      own_repos_pushed_last_365_days: 2,
      most_recent_push: null,
    },
    notice: 'Counts describe public repositories only and are not a measure of ability.',
  },
};
const PORTFOLIO: PortfolioSource = {
  source_ref: 'https://jane.example/',
  fetched_at: '2026-03-01T10:00:00Z',
  snapshot: {
    requested_url: 'https://jane.example/',
    host: 'jane.example',
    pages: [
      {
        url: 'https://jane.example/',
        title: 'Jane Doe - Portfolio',
        description: 'Backend engineer',
        text_truncated: false,
      },
    ],
    skipped_pages: [{ url: 'https://jane.example/private', reason: 'disallowed by robots.txt' }],
    notice: 'It is what the site says, not verified experience.',
  },
};

const notConnected = () => [
  ...signedInHandlers(),
  http.get(api('/integrations/github'), () =>
    errorBody('source_not_connected', 'No github source is connected', 404),
  ),
  http.get(api('/integrations/portfolio'), () =>
    errorBody('source_not_connected', 'No portfolio source is connected', 404),
  ),
];

describe('connections', () => {
  it('shows both sources as not connected (a 404 is an empty state, not an error)', async () => {
    useHandlers(...notConnected());
    renderApp('/connections');
    expect(await screen.findByText('No GitHub profile connected yet.')).toBeInTheDocument();
    expect(screen.getByText('No portfolio connected yet.')).toBeInTheDocument();
    expect(screen.getAllByText('Not connected')).toHaveLength(2);
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('connects GitHub and shows only observed data', async () => {
    let connected = false;
    let sent: unknown;
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/integrations/github'), () =>
        connected ? HttpResponse.json(GITHUB) : errorBody('source_not_connected', 'x', 404),
      ),
      http.post(api('/integrations/github'), async ({ request }) => {
        sent = await request.json();
        connected = true;
        return HttpResponse.json(GITHUB);
      }),
      http.get(api('/integrations/portfolio'), () => errorBody('source_not_connected', 'x', 404)),
    );
    renderApp('/connections');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('GitHub username'), '@janedoe');
    await user.click(screen.getByRole('button', { name: 'Connect GitHub' }));
    expect(await screen.findByText('Python · 2')).toBeInTheDocument();
    expect(sent).toEqual({ username: '@janedoe' });
    expect(screen.getByText('interview-sim')).toBeInTheDocument();
    expect(screen.queryByText('forked-lib')).toBeNull(); // forks are not shown as the candidate's work
    expect(screen.getByText(/Counts describe public repositories/)).toBeInTheDocument();
    expect(screen.getByText('Connected')).toBeInTheDocument();
  });

  it('shows backend errors for an unknown GitHub user', async () => {
    useHandlers(
      ...notConnected(),
      http.post(api('/integrations/github'), () =>
        errorBody('github_user_not_found', 'GitHub user not found', 404),
      ),
    );
    renderApp('/connections');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('GitHub username'), 'nobody');
    await user.click(screen.getByRole('button', { name: 'Connect GitHub' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('GitHub user not found');
  });

  it('validates input before contacting the server', async () => {
    useHandlers(...notConnected());
    renderApp('/connections');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Connect GitHub' }));
    expect(await screen.findByText('Enter a GitHub username')).toBeInTheDocument();
    await user.type(screen.getByLabelText('Website address'), 'jane.example');
    await user.click(screen.getByRole('button', { name: 'Connect website' }));
    expect(await screen.findByText('Start with http:// or https://')).toBeInTheDocument();
  });

  it('explains a refused portfolio address', async () => {
    useHandlers(
      ...notConnected(),
      http.post(api('/integrations/portfolio'), () =>
        errorBody(
          'portfolio_url_rejected',
          'That address points to a private or internal network and cannot be used',
          422,
        ),
      ),
    );
    renderApp('/connections');
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText('Website address'), 'http://127.0.0.1/');
    await user.click(screen.getByRole('button', { name: 'Connect website' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('private or internal network');
  });

  it('shows the portfolio pages, skipped pages and the disclaimer', async () => {
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/integrations/github'), () => errorBody('source_not_connected', 'x', 404)),
      http.get(api('/integrations/portfolio'), () => HttpResponse.json(PORTFOLIO)),
    );
    renderApp('/connections');
    expect(await screen.findByText('Jane Doe - Portfolio')).toBeInTheDocument();
    expect(screen.getByText('1 page(s) skipped')).toBeInTheDocument();
    expect(screen.getByText(/not verified experience/)).toBeInTheDocument();
  });

  it('confirms before disconnecting and explains the consequence', async () => {
    let removed = 0;
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/integrations/github'), () => HttpResponse.json(GITHUB)),
      http.get(api('/integrations/portfolio'), () => errorBody('source_not_connected', 'x', 404)),
      http.delete(api('/integrations/github'), () => {
        removed += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderApp('/connections');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Disconnect' }));
    const dialog = screen.getByRole('alertdialog');
    expect(dialog).toHaveTextContent('together with any analyses built from it');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(removed).toBe(0);
    await user.click(screen.getByRole('button', { name: 'Disconnect' }));
    await user.click(
      within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Disconnect' }),
    );
    await waitFor(() => expect(removed).toBe(1));
  });
});

const ANALYSIS = {
  id: 'an-1',
  created_at: '2026-03-02T10:00:00Z',
  provider: 'openai',
  model: 'test-model',
  consent_external_ai: false,
  input_truncated: false,
  github_source_id: 'g1',
  portfolio_source_id: null,
  resume_id: null,
  result: {
    facts: {
      sources_used: ['github'],
      github: {
        login: 'janedoe',
        profile_url: 'https://github.com/janedoe',
        own_repositories_considered: 4,
        language_distribution: { Python: 2 },
        notable_repositories: [],
        own_repos_pushed_last_365_days: 2,
        note: 'Counts of public repositories; not a measure of programming ability.',
      },
      portfolio: null,
      consistency: null,
    },
    assessment: {
      summary: 'Backend-focused public work.',
      strengths: ['Consistent Python projects'],
      potential_skill_gaps: [],
      project_assessments: [
        {
          name: 'interview-sim',
          source: { source: 'github', ref: 'interview-sim' },
          technologies_demonstrated: ['Python'],
          what_it_shows: 'An API with tests.',
          relevance: null,
          complexity: 'moderate',
          complexity_basis: null,
        },
      ],
      demonstrated_skills: [
        { name: 'Python', evidence: [{ source: 'github', ref: 'interview-sim' }] },
      ],
      consistency_notes: [],
      caveats: ['Private work is not visible.'],
    },
    unverified_items_removed: 1,
  },
  profile_suggestion: { skills: [{ name: 'Python', category: 'technical', level: null }] },
  suggestion_notes: [],
};

describe('integration analysis', () => {
  const githubOnly = () => [
    ...signedInHandlers(),
    http.get(api('/integrations/github'), () => HttpResponse.json(GITHUB)),
    http.get(api('/integrations/portfolio'), () => errorBody('source_not_connected', 'x', 404)),
  ];

  it('asks the user to connect a source first', async () => {
    useHandlers(...notConnected());
    renderApp('/connections');
    expect(await screen.findByText(/Connect GitHub or a portfolio above/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Analyse my sources' })).toBeNull();
  });

  it('sends the consent choice and shows facts, opinion and evidence separately', async () => {
    let created = false;
    let sent: unknown;
    useHandlers(
      ...githubOnly(),
      http.post(api('/integrations/analysis'), async ({ request }) => {
        sent = await request.json();
        created = true;
        return HttpResponse.json(ANALYSIS, { status: 201 });
      }),
      http.get(api('/integrations/analysis'), () =>
        HttpResponse.json(
          created
            ? [
                {
                  id: 'an-1',
                  created_at: ANALYSIS.created_at,
                  provider: 'openai',
                  model: 'm',
                  sources_used: ['github'],
                },
              ]
            : [],
        ),
      ),
      http.get(api('/integrations/analysis/an-1'), () => HttpResponse.json(ANALYSIS)),
    );
    renderApp('/connections');
    const user = userEvent.setup();
    await user.click(await screen.findByLabelText(/Allow my public source data/));
    await user.click(screen.getByRole('button', { name: 'Analyse my sources' }));
    expect(await screen.findByText('Backend-focused public work.')).toBeInTheDocument();
    expect(sent).toEqual({ allow_external_ai: true });
    expect(screen.getByText('Facts read from your sources')).toBeInTheDocument();
    expect(screen.getByText('AI assessment')).toBeInTheDocument();
    expect(
      screen.getByText(/1 claim\(s\) the sources did not support were removed/),
    ).toBeInTheDocument();
    expect(screen.getByText('Evidence: GitHub: interview-sim')).toBeInTheDocument();
    expect(screen.getByText('Private work is not visible.')).toBeInTheDocument();
  });

  it('says honestly when no AI provider is configured', async () => {
    useHandlers(
      ...githubOnly(),
      http.post(api('/integrations/analysis'), () =>
        errorBody('ai_unavailable', 'No AI provider is configured on this server', 503),
      ),
    );
    renderApp('/connections');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Analyse my sources' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'AI features are not available on this server',
    );
    expect(screen.queryByText('AI assessment')).toBeNull();
  });

  it('applies only the suggestions the user ticks', async () => {
    let applied: unknown;
    useHandlers(
      ...githubOnly(),
      http.get(api('/integrations/analysis'), () =>
        HttpResponse.json([
          {
            id: 'an-1',
            created_at: ANALYSIS.created_at,
            provider: 'openai',
            model: 'm',
            sources_used: ['github'],
          },
        ]),
      ),
      http.get(api('/integrations/analysis/an-1'), () => HttpResponse.json(ANALYSIS)),
      http.post(api('/integrations/analysis/an-1/apply-to-profile'), async ({ request }) => {
        applied = await request.json();
        return HttpResponse.json({ applied: { skills: 1 }, skipped: [], profile: {} });
      }),
    );
    renderApp('/connections');
    const user = userEvent.setup();
    const apply = await screen.findByRole('button', { name: 'Apply selected to my profile' });
    expect(apply).toBeDisabled();
    await user.click(screen.getByLabelText('Python (technical)'));
    await user.click(apply);
    expect(await screen.findByText('Profile updated')).toBeInTheDocument();
    expect(applied).toEqual({
      mode: 'merge',
      overwrite_existing: false,
      skills: [{ name: 'Python', category: 'technical', level: null }],
    });
  });

  it('confirms before deleting an analysis', async () => {
    let removed = 0;
    useHandlers(
      ...githubOnly(),
      http.get(api('/integrations/analysis'), () =>
        HttpResponse.json([
          {
            id: 'an-1',
            created_at: ANALYSIS.created_at,
            provider: 'openai',
            model: 'm',
            sources_used: ['github'],
          },
        ]),
      ),
      http.get(api('/integrations/analysis/an-1'), () => HttpResponse.json(ANALYSIS)),
      http.delete(api('/integrations/analysis/an-1'), () => {
        removed += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderApp('/connections');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Delete this analysis' }));
    const dialog = screen.getByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(removed).toBe(0);
    await user.click(screen.getByRole('button', { name: 'Delete this analysis' }));
    await user.click(
      within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete' }),
    );
    await waitFor(() => expect(removed).toBe(1));
  });
});
