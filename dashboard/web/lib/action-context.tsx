'use client';

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from 'react';
import type { ActionVerb } from './plan';

/**
 * ActionHandler — fired when any interactive block is tapped. Returns the
 * full backend response so callers can do verb-specific UI work (e.g.
 * collapse a row after mark_reminder_done). Never throws — surface errors
 * land as toasts.
 */
export type ActionHandler = (verb: ActionVerb) => Promise<ActionResponse>;

export interface ActionResponse {
  ok: boolean;
  message?: string;
  /** Verb echoed back from the backend. */
  verb?: ActionVerb;
  /** Per-verb payload extras (observation_id, attention_id, etc.). */
  [key: string]: unknown;
}

export interface Toast {
  id: string;
  /** "donna" / "donna · system" */
  kicker: string;
  body: string;
  tone: 'donna' | 'system' | 'error';
}

interface ActionContextValue {
  fire: ActionHandler;
  toasts: Toast[];
  dismissToast: (id: string) => void;
  /** Last action response — useful for debug overlays. */
  lastResponse: ActionResponse | null;
}

const ActionContext = createContext<ActionContextValue | null>(null);

const TOAST_TTL_MS = 4500;

export interface ActionProviderProps {
  children: ReactNode;
  /** Authoritative user id. Sent on every POST. Without it actions error. */
  userId: string | null;
  /**
   * Optional refresh hook the dashboard wires up. Fired AFTER a successful
   * action so the manifest re-renders without waiting for SSE/poll.
   * The renderer's ``DashboardClient`` provides this.
   */
  onActionSuccess?: (response: ActionResponse) => void;
}

export function ActionProvider({
  children,
  userId,
  onActionSuccess,
}: ActionProviderProps) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [lastResponse, setLastResponse] = useState<ActionResponse | null>(null);

  const dismissToast = useCallback((id: string) => {
    setToasts((curr) => curr.filter((t) => t.id !== id));
  }, []);

  const pushToast = useCallback(
    (toast: Toast) => {
      setToasts((curr) => [...curr, toast]);
      setTimeout(() => dismissToast(toast.id), TOAST_TTL_MS);
    },
    [dismissToast],
  );

  const fire = useCallback<ActionHandler>(
    async (verb) => {
      if (!userId) {
        const fallback: ActionResponse = {
          ok: false,
          message: "can't tell who you are. sign in again.",
        };
        pushToast({
          id: cryptoRandomId(),
          kicker: 'donna',
          body: fallback.message!,
          tone: 'error',
        });
        setLastResponse(fallback);
        return fallback;
      }
      try {
        const res = await fetch('/api/dashboard/action', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ verb, user_id: userId }),
        });
        const json = (await res.json().catch(() => ({}))) as ActionResponse;
        if (!res.ok || !json.ok) {
          const body =
            typeof json.message === 'string' && json.message.trim()
              ? json.message
              : 'something broke. try again.';
          pushToast({
            id: cryptoRandomId(),
            kicker: 'donna',
            body,
            tone: 'error',
          });
          setLastResponse(json);
          return json;
        }
        if (typeof json.message === 'string' && json.message.trim()) {
          pushToast({
            id: cryptoRandomId(),
            kicker: 'donna',
            body: json.message,
            tone: 'donna',
          });
        }
        setLastResponse(json);
        onActionSuccess?.(json);
        return json;
      } catch (err) {
        const fallback: ActionResponse = {
          ok: false,
          message: "couldn't reach the brain.",
          error: String(err),
        };
        pushToast({
          id: cryptoRandomId(),
          kicker: 'donna',
          body: fallback.message!,
          tone: 'error',
        });
        setLastResponse(fallback);
        return fallback;
      }
    },
    [userId, pushToast, onActionSuccess],
  );

  return (
    <ActionContext.Provider value={{ fire, toasts, dismissToast, lastResponse }}>
      {children}
    </ActionContext.Provider>
  );
}

export function useAction(): ActionHandler {
  const ctx = useContext(ActionContext);
  if (!ctx) {
    // Storybook / fixture render fallback. Resolve to ok=true so optimistic
    // UI tests don't trip over a sentinel error.
    return async () => ({ ok: true, message: 'noop (no provider)' });
  }
  return ctx.fire;
}

export function useToasts(): {
  toasts: Toast[];
  dismissToast: (id: string) => void;
} {
  const ctx = useContext(ActionContext);
  if (!ctx) return { toasts: [], dismissToast: () => {} };
  return { toasts: ctx.toasts, dismissToast: ctx.dismissToast };
}

export function useLastActionResponse(): ActionResponse | null {
  const ctx = useContext(ActionContext);
  return ctx?.lastResponse || null;
}

function cryptoRandomId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `t_${Math.random().toString(36).slice(2)}_${Date.now()}`;
}
