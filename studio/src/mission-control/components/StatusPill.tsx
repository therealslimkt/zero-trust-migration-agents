import type { Tone } from './presentation';

interface StatusPillProps {
  tone: Tone;
  label: string;
  /** Optional trailing detail, e.g. a count. Kept textual so colour is never the only signal. */
  detail?: string;
  size?: 'sm' | 'md';
}

export function StatusPill({ tone, label, detail, size = 'md' }: StatusPillProps) {
  return (
    <span className={`mc-pill mc-pill--${tone} mc-pill--${size}`}>
      <span className="mc-pill__marker" aria-hidden="true" />
      <span className="mc-pill__label">{label}</span>
      {detail ? <span className="mc-pill__detail">{detail}</span> : null}
    </span>
  );
}
