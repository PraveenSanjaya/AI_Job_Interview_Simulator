import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { PROFILE } from './fixtures';
import { profileCompleteness, splitList, toApiInput, toFormValues } from '@/pages/profileForm';
import { api, errorBody, renderApp, signedInHandlers, useHandlers } from './utils';

describe('profile conversions', () => {
  it('round-trips the stored profile without changing it', () => {
    const input = toApiInput(toFormValues(PROFILE));
    expect(input.full_name).toBe('Ada Lovelace');
    expect(input.preferred_roles).toEqual(['Backend Developer']);
    expect(input.work_experience[0]).toMatchObject({ is_current: true, end_date: null });
    expect(input.projects[0]?.technologies).toEqual(['FastAPI', 'PostgreSQL']);
    expect(input.career_objective).toBeNull();
    expect(input.skills[1]).toEqual({ name: 'Teamwork', category: 'soft', proficiency: null });
  });

  it('splits comma lists and measures completeness from real data', () => {
    expect(splitList(' a, ,b ,, c')).toEqual(['a', 'b', 'c']);
    expect(profileCompleteness(PROFILE)).toEqual({
      done: 7,
      total: 7,
      missing: [],
    });
    const empty = { ...PROFILE, headline: null, skills: [], projects: [] };
    expect(profileCompleteness(empty).missing).toEqual(['A headline', 'Skills', 'Projects']);
  });
});

describe('profile page', () => {
  it('shows the stored profile', async () => {
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/profile'), () => HttpResponse.json(PROFILE)),
    );
    renderApp('/profile');
    expect(await screen.findByDisplayValue('Ada Lovelace')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Python')).toBeInTheDocument();
    expect(screen.getByDisplayValue('Shop API')).toBeInTheDocument();
    expect(screen.getByLabelText('Email')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeDisabled(); // nothing changed
  });

  it('shows a loading state, then an error with a retry when loading fails', async () => {
    let calls = 0;
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/profile'), () => {
        calls += 1;
        return calls === 1
          ? errorBody('internal_error', 'An unexpected error occurred', 500)
          : HttpResponse.json(PROFILE);
      }),
    );
    renderApp('/profile');
    expect(await screen.findByText('Loading your profile…')).toBeInTheDocument();
    expect(await screen.findByRole('alert')).toHaveTextContent('An unexpected error occurred');
    await userEvent.setup().click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByDisplayValue('Ada Lovelace')).toBeInTheDocument();
  });

  it('saves edits as a full replacement of the profile', async () => {
    let body: Record<string, unknown> = {};
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/profile'), () => HttpResponse.json(PROFILE)),
      http.put(api('/profile'), async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ ...PROFILE, headline: 'Backend developer' });
      }),
    );
    renderApp('/profile');
    const user = userEvent.setup();
    const headline = await screen.findByLabelText('Headline');
    await user.clear(headline);
    await user.type(headline, 'Backend developer');
    await user.click(screen.getByRole('button', { name: 'Save profile' }));
    expect(await screen.findByText('Profile saved.')).toBeInTheDocument();
    expect(body.headline).toBe('Backend developer');
    expect(body.skills).toHaveLength(2); // untouched sections are sent too
    expect(body.preferred_roles).toEqual(['Backend Developer']);
    expect(body).not.toHaveProperty('email');
  });

  it('adds and removes entries', async () => {
    let body: { skills?: { name: string; category: string }[] } = {};
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/profile'), () => HttpResponse.json(PROFILE)),
      http.put(api('/profile'), async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json(PROFILE);
      }),
    );
    renderApp('/profile');
    const user = userEvent.setup();
    await screen.findByDisplayValue('Python');
    await user.click(screen.getByRole('button', { name: /add skill/i }));
    const skillInputs = screen.getAllByLabelText('Skill');
    await user.type(skillInputs[skillInputs.length - 1] as HTMLElement, 'Docker');
    await user.click(screen.getByRole('button', { name: 'Remove skill 2' })); // Teamwork
    await user.click(screen.getByRole('button', { name: 'Save profile' }));
    await waitFor(() => expect(body.skills).toBeDefined());
    expect(body.skills?.map((s) => s.name)).toEqual(['Python', 'Docker']);
  });

  it('validates before sending: required fields, duplicate skills and dates', async () => {
    let sent = false;
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/profile'), () => HttpResponse.json(PROFILE)),
      http.put(api('/profile'), () => {
        sent = true;
        return HttpResponse.json(PROFILE);
      }),
    );
    renderApp('/profile');
    const user = userEvent.setup();
    const name = await screen.findByLabelText('Full name');
    await user.clear(name);
    await user.click(screen.getByRole('button', { name: /add skill/i }));
    const skills = screen.getAllByLabelText('Skill');
    await user.type(skills[skills.length - 1] as HTMLElement, 'python'); // duplicate, case-insensitive
    const endDates = screen.getAllByLabelText('End date');
    await user.type(endDates[endDates.length - 1] as HTMLElement, '2020-01-01'); // before the education start
    await user.click(screen.getByRole('button', { name: 'Save profile' }));
    expect(await screen.findByText('Enter your name')).toBeInTheDocument();
    expect(screen.getByText('This skill is already listed')).toBeInTheDocument();
    expect(sent).toBe(false);
  });

  it('shows the server validation error and keeps the edits', async () => {
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/profile'), () => HttpResponse.json(PROFILE)),
      http.put(api('/profile'), () =>
        errorBody('validation_error', 'Request validation failed', 422, {
          details: [
            {
              location: ['body', 'projects', 0, 'url'],
              message: 'URL must use http or https',
              type: 'x',
            },
          ],
        }),
      ),
    );
    renderApp('/profile');
    const user = userEvent.setup();
    const headline = await screen.findByLabelText('Headline');
    await user.type(headline, '!');
    await user.click(screen.getByRole('button', { name: 'Save profile' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'projects.0.url: URL must use http or https',
    );
    expect(screen.getByLabelText('Headline')).toHaveValue('Junior backend developer!');
  });

  it('disables the end date of a current job', async () => {
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/profile'), () => HttpResponse.json(PROFILE)),
    );
    renderApp('/profile');
    const card = (await screen.findByText('Work experience')).closest('section') as HTMLElement;
    expect(within(card).getByLabelText('End date')).toBeDisabled();
    expect(within(card).getByLabelText('I currently work here')).toBeChecked();
  });
});
