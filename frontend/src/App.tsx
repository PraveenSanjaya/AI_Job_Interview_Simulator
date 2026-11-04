import { Link, Route, Routes } from 'react-router-dom';
import { GuestOnly, RequireAuth } from '@/auth/RequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { EmptyState } from '@/components/ui';
import { LoginPage, RegisterPage } from '@/pages/AuthPages';
import { ConnectionsPage } from '@/pages/ConnectionsPage';
import { DashboardPage } from '@/pages/DashboardPage';
import { InterviewReportPage } from '@/pages/InterviewReportPage';
import { InterviewSessionPage } from '@/pages/InterviewSessionPage';
import { InterviewsPage, NewInterviewPage } from '@/pages/InterviewsPages';
import { JobDetailPage, JobsPage, NewJobPage } from '@/pages/JobsPages';
import { ProfilePage } from '@/pages/ProfilePage';
import { ResumesPage } from '@/pages/ResumesPage';

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
    <Routes>
      <Route element={<GuestOnly />}>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />
      </Route>
      <Route element={<RequireAuth />}>
        <Route element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="profile" element={<ProfilePage />} />
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
  );
}
