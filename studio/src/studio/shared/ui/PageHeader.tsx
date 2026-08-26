import type { ReactNode } from "react";

export interface PageHeaderProps {
  eyebrow: string;
  title: string;
  description: string;
  accent?: "blue" | "red" | "green";
  action?: ReactNode;
}

export function PageHeader({ eyebrow, title, description, accent = "blue", action }: PageHeaderProps) {
  return (
    <header className={`skin-page-heading skin-page-heading--${accent}`}>
      <div>
        <p className="skin-eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action ? <div className="skin-page-heading__action">{action}</div> : null}
    </header>
  );
}
