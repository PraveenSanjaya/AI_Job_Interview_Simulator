import { lazy } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import { GuestOnly, RequireAuth } from '@/auth/RequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { RouteBoundary } from '@/components/RouteBoundary';
import { EmptyState } from '@/components/ui';

/* Pages load on demand so the first visit downloads only what it needs. */
const LoginPage = lazy(() => import('@/pages/AuthPages').then((m) => ({ default: m.LoginPage })));
const RegisterPage = lazy(() =>
  import('@/pages/AuthPages').then((m) => ({ default: m.RegisterPage })),
);
const ConnectionsPage = lazy(() =>
  import('@/pages/ConnectionsPage').then((m) => ({ default: m.ConnectionsPage })),
);
const DashboardPage = lazy(() =>
  import('@/pages/DashboardPage').then((m) => ({ default: m.DashboardPage })),
);
const InterviewReportPage = lazy(() =>
  import('@/pages/InterviewReportPage').then((m) => ({ default: m.InterviewReportPage })),
);
const InterviewSessionPage = lazy(() =>
  import('@/pages/InterviewSessionPage').then((m) => ({ default: m.InterviewSessionPage })),
);
const InterviewsPage = lazy(() =>
  import('@/pages/InterviewsPages').then((m) => ({ default: m.InterviewsPage })),
);
const NewInterviewPage = lazy(() =>
  import('@/pages/InterviewsPages').then((m) => ({ default: m.NewInterviewPage })),
);
const JobDetailPage = lazy(() =>
  import('@/pages/JobsPages').then((m) => ({ default: m.JobDetailPage })),
);
const JobsPage = lazy(() => import('@/pages/JobsPages').then((m) => ({ default: m.JobsPage })));
const NewJobPage = lazy(() => import('@/pages/JobsPages').then((m) => ({ default: m.NewJobPage })));
const AccountPage = lazy(() =>
  import('@/pages/AccountPage').then((m) => ({ default: m.AccountPage })),
);
const ProfilePage = lazy(() =>
  import('@/pages/ProfilePage').then((m) => ({ default: m.ProfilePage })),
);
const ResumesPage = lazy(() =>
  import('@/pages/ResumesPage').then((m) => ({ default: m.ResumesPage })),
);

function NotFound() {
  return (
    <EmptyState
      title="Page not found"
      description="The page you are looking for does not exist."
      action={
        <Link to="/" className="text-sm font-medium text-brand-700 hover:underline">
          Back to the dashboard
        </Link>
      }
    />
  );
}

export function App() {
  return (
    <RouteBoundary>
      <Routes>
        <Route element={<GuestOnly />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
        </Route>
        <Route element={<RequireAuth />}>
          <Route element={<AppShell />}>
            <Route index element={<DashboardPage />} />
            <Route path="profile" element={<ProfilePage />} />
            <Route path="account" element={<AccountPage />} />
            <Route path="resumes" element={<ResumesPage />} />
            <Route path="connections" element={<ConnectionsPage />} />
            <Route path="jobs" element={<JobsPage />} />
            <Route path="jobs/new" element={<NewJobPage />} />
            <Route path="jobs/:jobId" element={<JobDetailPage />} />
            <Route path="interviews" element={<InterviewsPage />} />
            <Route path="interviews/new" element={<NewInterviewPage />} />
            <Route path="interviews/:sessionId" element={<InterviewSessionPage />} />
            <Route path="interviews/:sessionId/report" element={<InterviewReportPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Route>
      </Routes>
    </RouteBoundary>
  );
}
