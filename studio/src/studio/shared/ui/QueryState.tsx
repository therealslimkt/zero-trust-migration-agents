import type { ReactNode } from "react";

export interface QueryStateProps {
  pending: boolean;
  error: Error | null;
  empty?: boolean;
  emptyMessage?: string;
  children: ReactNode;
}

export function QueryState({ pending, error, empty = false, emptyMessage = "Nothing to show yet.", children }: QueryStateProps) {
  if (pending) return <p className="skin-muted">Loading real local state…</p>;
  if (error) return <p className="skin-error" role="alert">{error.message}</p>;
  if (empty) return <p className="skin-muted">{emptyMessage}</p>;
  return children;
}

