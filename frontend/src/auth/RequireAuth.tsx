import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Spinner } from '@/components/ui';
import { useAuth } from './AuthContext';

/** Renders child routes only for signed-in users; everyone else goes to the login page. */
export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === 'loading') return <Spinner label="Restoring your session" />;
  if (status === 'anonymous') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}

/** Login and register are for signed-out visitors; signed-in users go to the dashboard. */
export function GuestOnly() {
  const { status } = useAuth();
  if (status === 'loading') return <Spinner label="Loading" />;
  if (status === 'authenticated') return <Navigate to="/" replace />;
  return <Outlet />;
}
