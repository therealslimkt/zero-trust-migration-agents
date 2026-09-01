import { useReducedMotion } from "motion/react";
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

/**
 * The plugin factory line.
 *
 * A legacy engine goes in at one end and a sealed cartridge comes out the
 * other. The belt is decorative and marked aria-hidden; the three stations
 * underneath carry the same information as text, so nothing here is only
 * available to someone who can watch it move.
 */
export function PluginFactory() {
  const reducedMotion = useReducedMotion();

  return (
    <div className="plugin-factory">
      <div className="plugin-factory__line" aria-hidden="true" data-static={reducedMotion ? "true" : undefined}>
        <span className="pf-mouth pf-mouth--in">
          {INTAKE.map((source) => <PixelIcon key={source.icon} name={source.icon} size="lg" color="google-blue" />)}
        </span>

        <span className="pf-belt">
          {INTAKE.map((source, index) => <span className="pf-part pf-part--raw" key={`raw-${source.icon}`} style={{ animationDelay: `${index * 2.4}s` }}>
            <PixelIcon name={source.icon} size="lg" color="google-blue" />
          </span>)}
          {INTAKE.map((source, index) => <span className="pf-part pf-part--sealed" key={`sealed-${source.icon}`} style={{ animationDelay: `${index * 2.4}s` }}>
            <PixelIcon name="cartridge" size="lg" color="google-green" />
          </span>)}
          <span className="pf-press"><PixelIcon name="press" size="xl" color="google-yellow" /></span>
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
