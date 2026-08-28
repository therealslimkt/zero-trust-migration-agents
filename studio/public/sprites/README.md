# Reusable Mission Control sprites

These assets are stable, individually addressable copies of the raster sprites
used by the Studio. Keep their native dimensions and use integer scaling with
`image-rendering: pixelated`.

| Asset | Native size | Style | Public path |
| --- | ---: | --- | --- |
| Jetson Orin Nano Super | 96×64 RGBA | Game Boy Advance-era hardware sprite | `/sprites/jetson-orin-super-gba-96x64.png` |

The imported application copy remains under `src/web/assets/jetson/` so Vite
can content-hash it. The public copy exists for reuse in documentation, demos,
and future fleet-agent portraits without depending on a build-generated URL.
