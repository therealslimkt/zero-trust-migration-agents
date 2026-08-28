# Technology pixel icon system

These 16×16 integer-grid SVGs are reusable project artwork inspired by the
silhouette or function of the technology they identify. They are not official
brand assets and must always appear beside a text label.

The visual references are the Google Cloud product icon library, Apache Beam's
logo resources, and each vendor's current brand guidance. Identity Platform
uses a generic identity shield rather than a redrawn Firebase mark because the
Firebase brand guidelines prohibit altering that mark.

## Workflow

1. Add one canonical `currentColor` SVG with a `0 0 16 16` view box and
   `shape-rendering="crispEdges"`.
2. Add the same path to `index.ts` so `PixelIcon` can render it in React.
3. Run `npm run assets:pixel` to generate standalone SVGs, the symbol sprite,
   contact sheet, and manifest under `public/pixel-icons/`.
4. Inspect the contact sheet at 1× and 2× scale before accepting the icon.

This code-native registry is the style-preservation mechanism. A LoRA is not
appropriate for the current icon set: deterministic integer geometry produces
more repeatable results, is editable in source control, and avoids raster
cleanup. Reconsider model training only if the art direction expands into a
large family of textured raster illustrations that cannot be represented by
the SVG grammar.

Reference sources:

- Google Cloud icon library: https://cloud.google.com/icons
- Apache Beam logos: https://beam.apache.org/community/logos/
- Firebase brand guidelines: https://firebase.google.com/brand-guidelines
