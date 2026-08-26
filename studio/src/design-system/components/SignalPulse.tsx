import { motion, useReducedMotion } from "motion/react";

export interface SignalPulseProps {
  active: boolean;
  label: string;
}

export function SignalPulse({ active, label }: SignalPulseProps) {
  const reduceMotion = useReducedMotion();
  return (
    <span className="inline-flex items-center gap-2 text-sm">
      <motion.span
        aria-hidden="true"
        className="size-2 rounded-full bg-[var(--success)]"
        animate={active && !reduceMotion ? { opacity: [0.45, 1, 0.45], scale: [0.9, 1.15, 0.9] } : { opacity: active ? 1 : 0.35, scale: 1 }}
        transition={{ duration: 1.8, repeat: active && !reduceMotion ? Infinity : 0, ease: "easeInOut" }}
      />
      <span>{label}</span>
    </span>
  );
}

