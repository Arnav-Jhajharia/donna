'use client';

import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from 'react';

interface AttentionSheetContextValue {
  attentionId: string | null;
  openSheet: (attentionId: string) => void;
  closeSheet: () => void;
}

const AttentionSheetContext = createContext<AttentionSheetContextValue | null>(null);

export function AttentionSheetProvider({ children }: { children: ReactNode }) {
  const [attentionId, setAttentionId] = useState<string | null>(null);

  const openSheet = useCallback((id: string) => {
    setAttentionId(id);
  }, []);

  const closeSheet = useCallback(() => {
    setAttentionId(null);
  }, []);

  return (
    <AttentionSheetContext.Provider value={{ attentionId, openSheet, closeSheet }}>
      {children}
    </AttentionSheetContext.Provider>
  );
}

export function useAttentionSheet(): AttentionSheetContextValue {
  const ctx = useContext(AttentionSheetContext);
  if (!ctx) {
    return {
      attentionId: null,
      openSheet: () => {},
      closeSheet: () => {},
    };
  }
  return ctx;
}
