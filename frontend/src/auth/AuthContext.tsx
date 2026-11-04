import { useQueryClient } from '@tanstack/react-query';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { authApi } from '@/api/endpoints';
import type { User } from '@/api/types';
import { refreshSession, setSessionExpiredHandler } from '@/lib/http';
import { tokens } from '@/lib/tokens';

type Status = 'loading' | 'authenticated' | 'anonymous';

interface AuthValue {
  status: Status;
  user: User | null;
  /** True when the user was signed out because their session expired or was revoked. */
  sessionExpired: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (input: { email: string; password: string; full_name: string }) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>('loading');
  const [user, setUser] = useState<User | null>(null);
  const [sessionExpired, setSessionExpired] = useState(false);

  const signOutLocally = useCallback(
    (expired: boolean) => {
      tokens.clear();
      queryClient.clear();
      setUser(null);
      setStatus('anonymous');
      setSessionExpired(expired);
    },
    [queryClient],
  );

  // Expired or revoked sessions found by the HTTP layer sign the user out.
  useEffect(() => {
    setSessionExpiredHandler(() => signOutLocally(true));
  }, [signOutLocally]);

  // Restore a session after a reload: refresh token -> new tokens -> current user.
  useEffect(() => {
    let cancelled = false;
    async function restore() {
      if (!tokens.getRefresh()) {
        setStatus('anonymous');
        return;
      }
      try {
        await refreshSession();
        const me = await authApi.me();
        if (!cancelled) {
          setUser(me);
          setStatus('authenticated');
        }
      } catch {
        if (!cancelled) signOutLocally(false);
      }
    }
    void restore();
    return () => {
      cancelled = true;
    };
  }, [signOutLocally]);

  const login = useCallback(async (email: string, password: string) => {
    const pair = await authApi.login({ email, password });
    tokens.set(pair.access_token, pair.refresh_token);
    setUser(await authApi.me());
    setSessionExpired(false);
    setStatus('authenticated');
  }, []);

  const register = useCallback(
    async (input: { email: string; password: string; full_name: string }) => {
      await authApi.register(input);
      await login(input.email, input.password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    const refresh = tokens.getRefresh();
    try {
      if (refresh) await authApi.logout(refresh);
    } catch {
      /* the local session is ended regardless */
    }
    signOutLocally(false);
  }, [signOutLocally]);

  const value = useMemo(
    () => ({ status, user, sessionExpired, login, register, logout }),
    [status, user, sessionExpired, login, register, logout],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}
