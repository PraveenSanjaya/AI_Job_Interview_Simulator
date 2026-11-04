import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { resumeApi } from '@/api/endpoints';
import { ApiError } from '@/lib/errors';
import { ANALYSIS, RESUME } from './fixtures';
import { api, errorBody, renderApp, signedInHandlers, useHandlers } from './utils';

const withResumes = (list: unknown[] = [RESUME]) => [
  ...signedInHandlers(),
  http.get(api('/resumes'), () => HttpResponse.json(list)),
];

describe('resumes', () => {
  it('shows an empty state with guidance', async () => {
    useHandlers(...withResumes([]));
    renderApp('/resumes');
    expect(await screen.findByText('No resumes yet')).toBeInTheDocument();
    expect(screen.getByLabelText('CV file')).toBeInTheDocument();
  });

  it('lists resumes with their real status and explains failures', async () => {
    useHandlers(
      ...withResumes([
        RESUME,
        {
          ...RESUME,
          id: 'r2',
          display_name: 'scan.pdf',
          status: 'failed',
          has_analysis: false,
          error_code: 'ocr_required',
          error_message: 'x',
        },
      ]),
    );
    renderApp('/resumes');
    expect(await screen.findByText('cv.pdf')).toBeInTheDocument();
    expect(screen.getByText('Analysed')).toBeInTheDocument();
    expect(screen.getByText('Failed')).toBeInTheDocument();
    expect(screen.getByText(/looks like a scanned document/)).toBeInTheDocument();
    expect(
      within(screen.getByText('scan.pdf').closest('li') as HTMLElement).queryByRole('button', {
        name: /analyse/i,
      }),
    ).toBeNull();
  });

  it('rejects wrong types and oversized files without contacting the server', async () => {
    let uploads = 0;
    useHandlers(
      ...withResumes([]),
      http.post(api('/resumes'), () => {
        uploads += 1;
        return HttpResponse.json(RESUME, { status: 201 });
      }),
    );
    renderApp('/resumes');
    const input = await screen.findByLabelText('CV file');
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(input, new File(['x'], 'photo.png', { type: 'image/png' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a PDF, DOCX or TXT file.');
    await user.upload(
      input,
      new File([new Uint8Array(6 * 1024 * 1024)], 'big.pdf', { type: 'application/pdf' }),
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('The limit is 5.0 MB');
    expect(uploads).toBe(0);
  });

  // jsdom + the MSW XHR interceptor cannot complete multipart bodies, so the transport is
  // stubbed here; the real multipart contract is checked against the live backend separately.
  it('uploads the chosen file and opens its analysis panel', async () => {
    let list: unknown[] = [];
    const upload = vi.spyOn(resumeApi, 'upload').mockImplementation(async () => {
      list = [{ ...RESUME, status: 'extracted', has_analysis: false }];
      return list[0] as typeof RESUME;
    });
    useHandlers(
      ...signedInHandlers(),
      http.get(api('/resumes'), () => HttpResponse.json(list)),
    );
    renderApp('/resumes');
    const file = new File(['hello'], 'cv.txt', { type: 'text/plain' });
    await userEvent
      .setup({ applyAccept: false })
      .upload(await screen.findByLabelText('CV file'), file);
    expect(await screen.findByText('Ready to analyse')).toBeInTheDocument();
    expect(upload).toHaveBeenCalledWith(file);
    expect(await screen.findByRole('button', { name: 'Analyse this CV' })).toBeInTheDocument();
  });

  it('shows the server message when an upload is refused', async () => {
    vi.spyOn(resumeApi, 'upload').mockRejectedValue(
      new ApiError({
        status: 415,
        code: 'unsupported_file_type',
        message: 'Only PDF, DOCX and TXT files are supported',
      }),
    );
    useHandlers(...withResumes([]));
    renderApp('/resumes');
    await userEvent
      .setup({ applyAccept: false })
      .upload(
        await screen.findByLabelText('CV file'),
        new File(['x'], 'cv.txt', { type: 'text/plain' }),
      );
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Only PDF, DOCX and TXT files are supported',
    );
  });

  it('asks for confirmation before deleting and deletes on confirm', async () => {
    let deleted = 0;
    useHandlers(
      ...withResumes(),
      http.delete(api('/resumes/r1'), () => {
        deleted += 1;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderApp('/resumes');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Delete cv.pdf' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(deleted).toBe(0);
    await user.click(screen.getByRole('button', { name: 'Delete cv.pdf' }));
    await user.click(
      within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Delete' }),
    );
    await waitFor(() => expect(deleted).toBe(1));
  });

  it('runs an analysis with the consent choice and explains unavailable AI', async () => {
    const bodies: unknown[] = [];
    useHandlers(
      ...withResumes([{ ...RESUME, has_analysis: false, status: 'extracted' }]),
      http.post(api('/resumes/r1/analyze'), async ({ request }) => {
        bodies.push(await request.json());
        return bodies.length === 1
          ? errorBody('ai_unavailable', 'AI analysis is not configured on this server', 503)
          : errorBody('ai_consent_required', 'consent', 403);
      }),
    );
    renderApp('/resumes');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'Analyse' }));
    await user.click(screen.getByRole('button', { name: 'Analyse this CV' }));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'AI features are not available on this server right now.',
    );
    await user.click(screen.getByRole('button', { name: 'Analyse this CV' }));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies).toEqual([{ allow_external_ai: false }, { allow_external_ai: false }]);
    expect(await screen.findByRole('alert')).toHaveTextContent('Tick the consent box');
    await user.click(screen.getByLabelText(/allow my cv details/i));
    await user.click(screen.getByRole('button', { name: 'Analyse this CV' }));
    await waitFor(() => expect(bodies[2]).toEqual({ allow_external_ai: true }));
  });

  it('separates verified facts from the AI opinion', async () => {
    useHandlers(
      ...withResumes(),
      http.get(api('/resumes/r1/analysis'), () => HttpResponse.json(ANALYSIS)),
    );
    renderApp('/resumes');
    await userEvent.setup().click(await screen.findByRole('button', { name: 'View analysis' }));
    const facts = (
      await screen.findByRole('heading', { name: 'What was found in your CV' })
    ).closest('section') as HTMLElement;
    expect(within(facts).getByText('Python')).toBeInTheDocument();
    expect(within(facts).getByText('Engineer at Acme')).toBeInTheDocument();
    expect(facts).toHaveTextContent('2 item(s) that could not be found in the text were removed.');
    const opinion = screen
      .getByRole('heading', { name: 'AI opinion (may be wrong)' })
      .closest('section') as HTMLElement;
    expect(within(opinion).getByText('A backend engineer.')).toBeInTheDocument();
    expect(within(opinion).queryByText('Python')).toBeNull();
    expect(
      screen.getByText('An education entry without a degree was left out'),
    ).toBeInTheDocument();
  });

  it('applies only the selected suggestions and reports what happened', async () => {
    let body: Record<string, unknown> = {};
    useHandlers(
      ...withResumes(),
      http.get(api('/resumes/r1/analysis'), () => HttpResponse.json(ANALYSIS)),
      http.post(api('/resumes/r1/apply-to-profile'), async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({
          applied: { skills: 1, headline: 1 },
          skipped: [{ field: 'skills', reason: '1 already present' }],
          profile: {},
        });
      }),
    );
    renderApp('/resumes');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'View analysis' }));
    const apply = await screen.findByRole('button', { name: 'Apply selected to my profile' });
    expect(apply).toBeDisabled(); // nothing is applied by default
    await user.click(screen.getByLabelText('Headline: Backend engineer'));
    await user.click(screen.getByLabelText('FastAPI (technical)'));
    await user.click(apply);
    expect(await screen.findByText('Profile updated')).toBeInTheDocument();
    expect(body).toEqual({
      mode: 'merge',
      overwrite_existing: false,
      headline: 'Backend engineer',
      skills: [{ name: 'FastAPI', category: 'technical', proficiency: null }],
    });
    expect(screen.getByText('skills: 1 already present')).toBeInTheDocument();
  });

  it('sends replace and overwrite only when explicitly chosen', async () => {
    let body: Record<string, unknown> = {};
    useHandlers(
      ...withResumes(),
      http.get(api('/resumes/r1/analysis'), () => HttpResponse.json(ANALYSIS)),
      http.post(api('/resumes/r1/apply-to-profile'), async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json({ applied: {}, skipped: [], profile: {} });
      }),
    );
    renderApp('/resumes');
    const user = userEvent.setup();
    await user.click(await screen.findByRole('button', { name: 'View analysis' }));
    await user.click(await screen.findByLabelText('Engineer at Acme'));
    await user.click(screen.getByLabelText(/replace the matching profile sections/i));
    await user.click(screen.getByLabelText(/overwrite my name/i));
    await user.click(screen.getByRole('button', { name: 'Apply selected to my profile' }));
    await waitFor(() => expect(body.mode).toBe('replace'));
    expect(body.overwrite_existing).toBe(true);
    expect(Object.keys(body).sort()).toEqual(['mode', 'overwrite_existing', 'work_experience']);
  });
});
