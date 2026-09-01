import { useEffect, useRef, useState } from "react";
import { animate, motion, useMotionValue, useReducedMotion, useTransform } from "motion/react";
import { PixelIcon, type PixelIconName } from "../../shared/ui/index";

/**
 * What the factory takes in. These are the three cartridges that actually
 * exist, named by the engine each one has to be decoded out of.
 */
const INTAKE: ReadonlyArray<{ readonly icon: PixelIconName; readonly label: string }> = [
  { icon: "db2", label: "IBM Db2 for i" },
  { icon: "sqlserver", label: "SQL Server" },
  { icon: "oracle", label: "Oracle 19c" },
];

/** The three things the line does to one, in order. */
const STATIONS: ReadonlyArray<{ readonly icon: PixelIconName; readonly name: string; readonly detail: string }> = [
  { icon: "database", name: "Read", detail: "a sealed copy, never the source" },
  { icon: "compass-draft", name: "Decode", detail: "code we own, not the model" },
  { icon: "shield-check", name: "Certify", detail: "counts reconcile or it fails" },
];

const BELT_SECONDS = 7.2;
const PART_GAP_SECONDS = 2.4;

/** Measure the belt so parts travel a real distance instead of a percentage. */
function useMeasuredWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}

/**
 * One part on the belt.
 *
 * A single motion value carries it end to end, and the raw and sealed icons
 * read their opacity off that same value. The swap therefore happens at the
 * press by construction rather than because two separate keyframe timelines
 * were hand-aligned to cross at the right instant.
 */
function Part({ icon, delay, distance, still }: {
  readonly icon: PixelIconName;
  readonly delay: number;
  readonly distance: number;
  readonly still: boolean;
}) {
  const progress = useMotionValue(still ? 0.16 : 0);
  const x = useTransform(progress, [0, 1], [0, distance]);
  const rawOpacity = useTransform(progress, [0, 0.06, 0.46, 0.5], [0, 1, 1, 0]);
  const sealedOpacity = useTransform(progress, [0.5, 0.54, 0.94, 1], [0, 1, 1, 0]);

  useEffect(() => {
    if (still || distance === 0) return;
    const controls = animate(progress, 1, {
      duration: BELT_SECONDS,
      ease: "linear",
      repeat: Infinity,
      delay,
    });
    return () => controls.stop();
  }, [delay, distance, progress, still]);

  return (
    <motion.span className="pf-part" style={{ x }}>
      <motion.span className="pf-part__face" style={{ opacity: rawOpacity }}>
        <PixelIcon name={icon} size="lg" color="google-blue" />
      </motion.span>
      <motion.span className="pf-part__face" style={{ opacity: sealedOpacity }}>
        <PixelIcon name="cartridge" size="lg" color="google-green" />
      </motion.span>
    </motion.span>
  );
}

/**
 * The plugin factory line.
 *
 * A legacy engine goes in at one end and a sealed cartridge comes out the
 * other. The belt is decorative and marked aria-hidden; the three stations
 * underneath carry the same information as text, so nothing here is only
 * available to someone who can watch it move.
 */
export function PluginFactory() {
  const reducedMotion = useReducedMotion() ?? false;
  const [beltRef, beltWidth] = useMeasuredWidth<HTMLSpanElement>();

  return (
    <div className="plugin-factory">
      <div className="plugin-factory__line" aria-hidden="true">
        <span className="pf-mouth pf-mouth--in">
          {INTAKE.map((source) => <PixelIcon key={source.icon} name={source.icon} size="lg" color="google-blue" />)}
        </span>

        <span className="pf-belt" ref={beltRef}>
          {INTAKE.map((source, index) => <Part
            key={source.icon}
            icon={source.icon}
            delay={index * PART_GAP_SECONDS}
            distance={beltWidth}
            still={reducedMotion}
          />)}
          <motion.span
            className="pf-press"
            animate={reducedMotion ? undefined : { y: [0, 0, 9, 0] }}
            transition={{ duration: PART_GAP_SECONDS, times: [0, 0.6, 0.72, 0.84], repeat: Infinity, ease: "easeInOut" }}
          >
            <PixelIcon name="press" size="xl" color="google-yellow" />
          </motion.span>
        </span>

        <span className="pf-mouth pf-mouth--out">
          <PixelIcon name="cartridge" size="lg" color="google-green" glow />
        </span>
      </div>

      <ol className="pf-stations">
        {STATIONS.map((station, index) => <li className="pf-station" key={station.name}>
          <span className="pf-station__index">{String(index + 1).padStart(2, "0")}</span>
          <PixelIcon name={station.icon} size="sm" color="google-green" />
          <strong>{station.name}</strong>
          <span>{station.detail}</span>
        </li>)}
      </ol>
    </div>
  );
}
