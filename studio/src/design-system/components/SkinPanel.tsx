import type { ReactNode } from "react";
import { Card } from "@heroui/react";

export interface SkinPanelProps {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function SkinPanel({ title, description, action, children, className = "" }: SkinPanelProps) {
  return (
    <Card className={`border border-[var(--separator)] bg-[var(--surface)] shadow-[var(--skin-shadow-resting)] ${className}`}>
      <Card.Header className="flex items-start justify-between gap-4">
        <div>
          <Card.Title className="font-[var(--skin-font-display)] text-base font-semibold tracking-[-0.02em]">
            {title}
          </Card.Title>
          {description ? <Card.Description className="mt-1 text-sm text-[var(--muted)]">{description}</Card.Description> : null}
        </div>
        {action}
      </Card.Header>
      <Card.Content>{children}</Card.Content>
    </Card>
  );
}

