import { render, screen } from '@testing-library/react';
import { lazy } from 'react';
import { RouteBoundary } from '@/components/RouteBoundary';

describe('RouteBoundary', () => {
  it('shows a spinner while a page loads and then the page', async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const Page = lazy(() => gate.then(() => ({ default: () => <p>Loaded page</p> })));
    render(
      <RouteBoundary>
        <Page />
      </RouteBoundary>,
    );
    expect(screen.getByText(/Loading page/)).toBeInTheDocument();
    release();
    expect(await screen.findByText('Loaded page')).toBeInTheDocument();
  });

  it('explains a page that could not be downloaded and offers a reload', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined);
    const Broken = lazy(() =>
      Promise.reject(new Error('Failed to fetch dynamically imported module')),
    );
    render(
      <RouteBoundary>
        <Broken />
      </RouteBoundary>,
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('This page could not be loaded');
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument();
  });
});
