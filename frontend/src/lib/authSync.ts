/**
 * Cross-tab coordination for the rotating refresh cookie.
 *
 * * `withRefreshLock` makes sure only one tab at a time refreshes. The refresh cookie is
 *   shared by every tab and each refresh rotates it, so two simultaneous refreshes would
 *   look like token replay and end the session. Web Locks is used where available; without
 *   it, a short-lived lease in localStorage (a random id and a timestamp, no secrets) gives
 *   best-effort exclusion.
 * * `broadcastAuth` / `onAuthBroadcast` tell other tabs that someone signed in or out. The
 *   message carries only the event name, never a token.
 */
export type AuthEvent = 'login' | 'logout';

const LOCK_NAME = 'ajis-refresh';
const CHANNEL_NAME = 'ajis-auth';
const LEASE_KEY = 'ajis.refresh_lease';
const LEASE_MS = 10_000;
const POLL_MS = 50;

const OWNER = Math.random().toString(36).slice(2);

function readLease(): { owner: string; until: number } | null {
  try {
    const raw = window.localStorage.getItem(LEASE_KEY);
    return raw ? (JSON.parse(raw) as { owner: string; until: number }) : null;
  } catch {
    return null;
  }
}

async function withLeaseFallback<T>(task: () => Promise<T>): Promise<T> {
  const deadline = Date.now() + LEASE_MS;
  for (;;) {
    const lease = readLease();
    if (!lease || lease.until < Date.now() || lease.owner === OWNER || Date.now() >= deadline)
      break;
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
  try {
    window.localStorage.setItem(
      LEASE_KEY,
      JSON.stringify({ owner: OWNER, until: Date.now() + LEASE_MS }),
    );
  } catch {
    /* storage unavailable: refresh without cross-tab exclusion */
  }
  try {
    return await task();
  } finally {
    try {
      if (readLease()?.owner === OWNER) window.localStorage.removeItem(LEASE_KEY);
    } catch {
      /* ignore */
    }
  }
}

export function withRefreshLock<T>(task: () => Promise<T>): Promise<T> {
  const locks = typeof navigator === 'undefined' ? undefined : navigator.locks;
  if (locks?.request) return locks.request(LOCK_NAME, task);
  return withLeaseFallback(task);
}

function openChannel(): BroadcastChannel | null {
  return typeof BroadcastChannel === 'undefined' ? null : new BroadcastChannel(CHANNEL_NAME);
}

export function broadcastAuth(event: AuthEvent): void {
  const channel = openChannel();
  if (!channel) return;
  channel.postMessage({ event, from: OWNER });
  channel.close();
}

/** Listen for sign-in/sign-out in other tabs (this tab's own messages are ignored). */
export function onAuthBroadcast(handler: (event: AuthEvent) => void): () => void {
  const channel = openChannel();
  if (!channel) return () => undefined;
  channel.onmessage = (message: MessageEvent<{ event?: unknown; from?: unknown }>) => {
    if (message.data?.from === OWNER) return; // this tab's own message
    const event = message.data?.event;
    if (event === 'login' || event === 'logout') handler(event);
  };
  return () => channel.close();
}
