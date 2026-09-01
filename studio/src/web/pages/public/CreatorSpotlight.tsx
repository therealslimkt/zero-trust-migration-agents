import { useEffect, useState, type CSSProperties } from "react";
import { motion, useReducedMotion } from "motion/react";
import { PixelIcon, type PixelIconName } from "../../shared/ui/index";
import portrait from "../../assets/people/katie-ohalloran.jpg";

/**
 * Four facets, each with its own pixel icon, trailing shape, and colour lane.
 * These four icons are authored on the denser 32x32 grid, so they render at
 * `lg` (24px) rather than the site's usual 16px inline size.
 */
const identityFacets: ReadonlyArray<{
  readonly key: string;
  readonly word: string;
  readonly icon: PixelIconName;
  readonly shape: "circle" | "square" | "triangle" | "diamond";
}> = [
  { key: "creator", word: "Creator", icon: "puppet-hand", shape: "circle" },
  { key: "artist", word: "Artist", icon: "cassette", shape: "square" },
  { key: "architect", word: "Architect", icon: "robot-head", shape: "triangle" },
  { key: "explorer", word: "Explorer", icon: "telescope", shape: "diamond" },
];

/**
 * Resolve the four identity hues to concrete colours.
 *
 * motion animates real values and cannot interpolate a CSS custom property, so
 * `var(--hue-1)` has to become a colour before it can be handed over. Reading
 * them from the element keeps the palette defined in CSS with the rest of the
 * theme, and the observer re-reads on a theme change so the wave follows it.
 */
function useIdentityHues(element: HTMLElement | null): readonly string[] {
  const [hues, setHues] = useState<readonly string[]>([]);
  useEffect(() => {
    if (!element) return;
    const read = () => {
      const computed = getComputedStyle(element);
      setHues([1, 2, 3, 4]
        .map((index) => computed.getPropertyValue(`--hue-${index}`).trim())
        .filter(Boolean));
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => observer.disconnect();
  }, [element]);
  return hues;
}

const PHRASE = "Dancing Through Life";

/** Each letter lifts and settles on its own beat, so the line reads as a dance rather than a wobble. */
const LETTER_STEP = 0.085;

/** The project's author: portrait with a Bowman-eye iris rim, four facets, and a signature phrase. */
export function CreatorSpotlight() {
  const reducedMotion = useReducedMotion();
  const [phraseElement, setPhraseElement] = useState<HTMLParagraphElement | null>(null);
  const hues = useIdentityHues(phraseElement);
  // Close the loop so the last letter hands back to the first colour.
  const wave = hues.length ? [...hues, hues[0]] : undefined;

  return (
    <div className="creator-spotlight">
      <figure className="creator-portrait">
        {/* The band and the spark were ::before and ::after. Motion cannot
            target a pseudo-element, so they are real elements now and the
            rotation is driven here rather than by a CSS keyframe. */}
        <motion.span
          className="creator-portrait__band"
          aria-hidden="true"
          animate={reducedMotion ? undefined : { rotate: 360 }}
          transition={{ duration: 26, ease: "linear", repeat: Infinity }}
        />
        <motion.span
          className="creator-portrait__spark"
          aria-hidden="true"
          animate={reducedMotion ? undefined : { rotate: 360 }}
          transition={{ duration: 2.8, ease: "linear", repeat: Infinity }}
        />
        <img className="creator-portrait__photo" src={portrait} alt="Katie O’Halloran" width={184} height={184} loading="lazy" decoding="async" />
      </figure>
      <h3 className="creator-spotlight__name">Katie O’Halloran</h3>
      <ul className="creator-facets">
        {identityFacets.map((facet) => <li className="creator-facet" data-facet={facet.key} key={facet.key}>
          <span className="creator-facet__icon"><PixelIcon name={facet.icon} size="lg" /></span>
          <span className="creator-facet__word">{facet.word}</span>
          <span className={`creator-facet__shape creator-facet__shape--${facet.shape}`} aria-hidden="true" />
        </li>)}
      </ul>
      <p className="creator-spotlight__phrase" ref={setPhraseElement}>
        {[...PHRASE].map((character, index) => character === " "
          ? <span className="creator-spotlight__space" key={index}> </span>
          : <motion.span
              className="creator-spotlight__letter"
              key={index}
              style={{ "--i": index } as CSSProperties}
              animate={reducedMotion ? undefined : { y: [0, -8, 0, 2, 0], rotate: [0, -4, 0, 3, 0], ...(wave ? { color: wave } : {}) }}
              transition={{
                y: { duration: 3.2, repeat: Infinity, ease: "easeInOut", delay: index * LETTER_STEP },
                rotate: { duration: 3.2, repeat: Infinity, ease: "easeInOut", delay: index * LETTER_STEP },
                // Slower than the bounce and staggered wider, so colour travels
                // along the line rather than pulsing the whole phrase at once.
                color: { duration: 6, repeat: Infinity, ease: "linear", delay: index * 0.28 },
              }}
            >{character}</motion.span>)}
      </p>
    </div>
  );
}
