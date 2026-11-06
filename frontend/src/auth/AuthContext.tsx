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
import { broadcastAuth, onAuthBroadcast } from '@/lib/authSync';
import { refreshSession, setSessionExpiredHandler } from '@/lib/http';
import { hasSessionHint, purgeLegacyRefreshToken } from '@/lib/session';
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
  /** Permanently deletes the account. Resolves to whether every stored file was removed. */
  deleteAccount: (password: string) => Promise<boolean>;
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

  // Expired or revoked sessions found by the HTTP layer sign the user out (in every tab).
  useEffect(() => {
    setSessionExpiredHandler(() => {
      signOutLocally(true);
      broadcastAuth('logout');
    });
  }, [signOutLocally]);

  // Restore a session after a reload: refresh cookie -> new access token -> current user.
  // The refresh token itself is HttpOnly; the CSRF cookie only hints that a session exists.
  const restore = useCallback(
    async (isCancelled: () => boolean) => {
      purgeLegacyRefreshToken();
      if (!hasSessionHint()) {
        setStatus('anonymous');
        return;
      }
      try {
        await refreshSession();
        const me = await authApi.me();
        if (!isCancelled()) {
          setUser(me);
          setStatus('authenticated');
        }
      } catch {
        if (!isCancelled()) signOutLocally(false);
      }
    },
    [signOutLocally],
  );

  useEffect(() => {
    let cancelled = false;
    void restore(() => cancelled);
    return () => {
      cancelled = true;
    };
  }, [restore]);

  // Another tab signed out (drop everything here) or in (pick up the shared session).
  // Messages carry no tokens.
  useEffect(
    () =>
      onAuthBroadcast((event) => {
        if (event === 'logout') signOutLocally(false);
        else void restore(() => false);
      }),
    [restore, signOutLocally],
  );

  const login = useCallback(async (email: string, password: string) => {
    const issued = await authApi.login({ email, password });
    tokens.set(issued.access_token);
    setUser(await authApi.me());
    setSessionExpired(false);
    setStatus('authenticated');
    broadcastAuth('login');
  }, []);

  const register = useCallback(
    async (input: { email: string; password: string; full_name: string }) => {
      await authApi.register(input);
      await login(input.email, input.password);
    },
    [login],
  );

  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      /* the local session is ended regardless */
    }
    signOutLocally(false);
    broadcastAuth('logout');
  }, [signOutLocally]);

  const deleteAccount = useCallback(
    async (password: string) => {
      const result = await authApi.deleteAccount(password);
      signOutLocally(false);
      broadcastAuth('logout');
      return result.stored_files_removed;
    },
    [signOutLocally],
  );

  const value = useMemo(
    () => ({ status, user, sessionExpired, login, register, logout, deleteAccount }),
    [status, user, sessionExpired, login, register, logout, deleteAccount],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}
