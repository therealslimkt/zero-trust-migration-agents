import { motion, useReducedMotion } from "motion/react";
import type { ReactNode } from "react";

export function RoutePage({ routeKey, children }: { routeKey: string; children: ReactNode }) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.main
      className="skin-main skin-route-page"
      key={routeKey}
      initial={reduceMotion ? false : { opacity: 0, x: 14 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
    >
      {children}
    </motion.main>
  );
}
