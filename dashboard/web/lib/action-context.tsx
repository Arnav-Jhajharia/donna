'use client';

import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';
import type { ActionVerb } from './plan';

/**
 * ActionHandler — fired when any interactive block in the dashboard is tapped.
 * The page provides the handler via <ActionProvider>. Blocks consume it via
 * useAction(). The handler POSTs to /api/dashboard/action and surfaces the
 * fake-WA ack via the toast queue.
 */
export type ActionHandler = (verb: ActionVerb) => Promise<void>;

export interface Toast {
  id: string;
  /** "donna · whatsapp" */
  kicker: string;
  body: string;
}

interface ActionContextValue {
  fire: ActionHandler;
  toasts: Toast[];
  dismissToast: (id: string) => void;
}

const ActionContext = createContext<ActionContextValue | null>(null);

const TOAST_TTL_MS = 4500;

export function ActionProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

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
      try {
        const res = await fetch('/api/dashboard/action', {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ verb }),
        });
        if (!res.ok) {
          pushToast({
            id: cryptoRandomId(),
            kicker: 'donna · system',
            body: 'something broke. try again.',
          });
          return;
        }
        const json = (await res.json()) as { wa_ack?: string };
        if (json.wa_ack) {
          pushToast({
            id: cryptoRandomId(),
            kicker: 'donna · whatsapp',
            body: json.wa_ack,
          });
        }
      } catch {
        pushToast({
          id: cryptoRandomId(),
          kicker: 'donna · system',
          body: "couldn't reach the brain.",
        });
      }
    },
    [pushToast],
  );

  return (
    <ActionContext.Provider value={{ fire, toasts, dismissToast }}>
      {children}
    </ActionContext.Provider>
  );
}

export function useAction(): ActionHandler {
  const ctx = useContext(ActionContext);
  if (!ctx) {
    return async () => {
      // No-op when used outside provider (e.g. fixture render in storybook).
    };
  }
  return ctx.fire;
}

export function useToasts(): { toasts: Toast[]; dismissToast: (id: string) => void } {
  const ctx = useContext(ActionContext);
  if (!ctx) return { toasts: [], dismissToast: () => {} };
  return { toasts: ctx.toasts, dismissToast: ctx.dismissToast };
}

function cryptoRandomId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `t_${Math.random().toString(36).slice(2)}_${Date.now()}`;
}
