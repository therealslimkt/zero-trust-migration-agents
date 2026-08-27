# Mission Control pixel icons

Generated from `src/web/assets/pixel/*.svg` with `npm run assets:pixel`. Do not hand-edit this directory.

- Standalone assets: `icons/<name>.svg`
- SVG symbol sprite: `pixel-icons.svg#pixel-<name>`
- Visual contact sheet: `pixel-icons-sheet.svg`
- Machine-readable index: `manifest.json`

Standalone example:

`<img src="/pixel-icons/icons/radar.svg" width="32" height="32" alt="Radar">`

Same-document symbol example:

`<svg viewBox="0 0 16 16"><use href="/pixel-icons/pixel-icons.svg#pixel-radar" /></svg>`

All artwork uses `currentColor`, a `16 16` view box, and crisp integer-grid geometry.
