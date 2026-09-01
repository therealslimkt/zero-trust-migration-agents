import type { CSSProperties } from "react";
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
  { key: "architect", word: "Architect", icon: "compass-draft", shape: "triangle" },
  { key: "explorer", word: "Explorer", icon: "telescope", shape: "diamond" },
];

const PHRASE = "Dancing Through Life";

/** Each letter lifts and settles on its own beat, so the line reads as a dance rather than a wobble. */
const LETTER_STEP = 0.085;

/** The project's author: portrait with a Bowman-eye iris rim, four facets, and a signature phrase. */
export function CreatorSpotlight() {
  const reducedMotion = useReducedMotion();

  return (
    <div className="creator-spotlight">
      <figure className="creator-portrait">
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
      <p className="creator-spotlight__phrase">
        {[...PHRASE].map((character, index) => character === " "
          ? <span className="creator-spotlight__space" key={index}> </span>
          : <motion.span
              className="creator-spotlight__letter"
              key={index}
              style={{ "--i": index } as CSSProperties}
              animate={reducedMotion ? undefined : { y: [0, -8, 0, 2, 0], rotate: [0, -4, 0, 3, 0] }}
              transition={{ duration: 3.2, repeat: Infinity, ease: "easeInOut", delay: index * LETTER_STEP }}
            >{character}</motion.span>)}
      </p>
    </div>
  );
}
