import { Component, Suspense, type ReactNode } from 'react';
import { Alert, Button, Spinner } from '@/components/ui';

interface State {
  failed: boolean;
}

/** Catches a page that failed to load (for example a stale chunk after a deploy). */
class LoadErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <Alert tone="error" title="This page could not be loaded">
        <p>
          Check your connection, then reload. If the problem continues, the app may have been
          updated.
        </p>
        <Button className="mt-3" variant="secondary" onClick={() => window.location.reload()}>
          Reload
        </Button>
      </Alert>
    );
  }
}

/** Shows a spinner while a lazily loaded page downloads, and a message if it cannot. */
export function RouteBoundary({ children }: { children: ReactNode }) {
  return (
    <LoadErrorBoundary>
      <Suspense fallback={<Spinner label="Loading page" />}>{children}</Suspense>
    </LoadErrorBoundary>
  );
}
