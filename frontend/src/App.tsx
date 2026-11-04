import { Link, Route, Routes } from 'react-router-dom';
import { useAuth } from '@/auth/AuthContext';
import { GuestOnly, RequireAuth } from '@/auth/RequireAuth';
import { AppShell } from '@/components/layout/AppShell';
import { EmptyState, PageHeader } from '@/components/ui';
import { LoginPage, RegisterPage } from '@/pages/AuthPages';
import { ConnectionsPage } from '@/pages/ConnectionsPage';
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

function Home() {
  const { user } = useAuth();
  return <PageHeader title="Dashboard" description={`Signed in as ${user?.email ?? ''}`} />;
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
          <Route index element={<Home />} />
          <Route path="profile" element={<ProfilePage />} />
          <Route path="resumes" element={<ResumesPage />} />
          <Route path="connections" element={<ConnectionsPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  );
}
