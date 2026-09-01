/** A chunky 8-step pixel spinner, drawn on the same 16x16 grid as the icons.
 *
 * Eight blocks around a ring light in sequence, the way a low-colour loading
 * indicator would. It is CSS-driven so it costs nothing and stops dead under
 * prefers-reduced-motion.
 */
const BLOCKS = [
  { x: 6, y: 0 }, { x: 11, y: 2 }, { x: 13, y: 6 }, { x: 11, y: 11 },
  { x: 6, y: 13 }, { x: 2, y: 11 }, { x: 0, y: 6 }, { x: 2, y: 2 },
]

export function PixelSpinner({ size = 18 }: { readonly size?: number }) {
  return (
    <svg
      className="pixspin"
      viewBox="0 0 16 16"
      width={size}
      height={size}
      role="img"
      aria-label="working"
      shapeRendering="crispEdges"
    >
      {BLOCKS.map((block, index) => (
        <rect
          key={index}
          x={block.x}
          y={block.y}
          width="3"
          height="3"
          fill="currentColor"
          style={{ animationDelay: `${index * 0.1}s` }}
        />
      ))}
    </svg>
  )
}
