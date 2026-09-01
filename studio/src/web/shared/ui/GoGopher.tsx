import type { SVGProps } from 'react'

import sprite from '../../assets/sprites/go-gopher.svg?raw'

/** The Go gopher, as a full-colour 20x26 pixel sprite.
 *
 * The pixel icon library is single-path and monochrome by design, so this
 * character lives beside it rather than inside it. The editable source is
 * src/web/assets/sprites/go-gopher.csv — one character per pixel — and the SVG
 * is generated from that grid.
 */
export function GoGopher({
  size = 26,
  title,
  ...props
}: { readonly size?: number; readonly title?: string } & Omit<SVGProps<SVGSVGElement>, 'children'>) {
  const markup = title
    ? sprite.replace('aria-label="Go gopher"', `aria-label="${title}"`)
    : sprite
  return (
    <span
      className="go-gopher"
      style={{ display: 'inline-flex', width: size * (20 / 26), height: size }}
      aria-hidden={title ? undefined : true}
      dangerouslySetInnerHTML={{ __html: markup }}
      {...(props as object)}
    />
  )
}
