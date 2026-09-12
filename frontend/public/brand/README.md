# TraceKite revised logo assets

The kite-and-tether concept is retained from the supplied TraceKite Mark artifact. This revision simplifies the primary mark to two colors, ends the lower spar at the sail, uses a transparent center, improves export padding, and adds a micro mark that retains the attached tether.

## Choose the right asset

- `tracekite-mark.svg`: primary two-color mark on white or light backgrounds. Recommended minimum height 48 px.
- `tracekite-mark-reverse.svg`: white outline with crimson detail for dark backgrounds.
- `tracekite-mark-mono.svg`: one-color dark mark.
- `tracekite-mark-white.svg`: one-color white mark.
- `tracekite-micro.svg` and `tracekite-micro-white.svg`: optically simplified marks for 16–32 px. The solid sail, junction and tether are intentional.
- `tracekite-horizontal.svg` and `tracekite-horizontal-reverse.svg`: full mark and outlined Archivo ExtraBold wordmark. Recommended minimum width 160 px.
- `tracekite-compact.svg`: micro mark with outlined wordmark for compact navigation. Recommended minimum width 120 px.
- `tracekite-stacked.svg`: centered mark and wordmark for documentation and cover layouts.
- `png/`: transparent PNG exports, including 16, 24, 32, 48, 64, 128, 256 and 512 px mark heights. Sizes 16–32 use the micro artwork.

SVG wordmarks contain paths rather than live font text. No font installation or network request is required to render them. Use the original Archivo font if rebuilding editable text.

## Colors

Primary ink #121A24. Signal crimson #CE3048. White #FFFFFF. Suggested cool vellum background #ECEFF3.

The revised master uses two ink colors. Slate #4E7A9B may remain an optional diagram/UI color; it is not part of the primary mark.

Use crimson as a logo accent, not as a default small-text color. Calculated sRGB contrast is 4.40:1 on vellum and 3.45:1 on ink. Ink on vellum is 15.19:1 and white on ink is 17.52:1. Logotype exemptions do not make the same colors suitable for all interface text.

## Construction and placement

The full mark has a 128 × 160 viewBox. Sail vertices are (64,18), (100,54), (64,108), (28,54). Its width is 72 units and height 90 units: a true 4:5 ratio. The junction is 40 percent down the sail. The outline is 6 units, spars 3, tether 4.5 and junction ring 4. The center is genuinely transparent; there is no background-colored patch.

The micro mark is an optical redraw, not a geometrically exact reduction of the full mark.

Keep clear space of at least one eighth of the rendered symbol height outside the asset box. Scale uniformly. Keep the wordmark capitalization TraceKite. Do not stretch, rotate, add shadows/gradients, detach the tether or recolor pieces independently. Use the full one-color mark for single-ink reproduction.

Recommended optional descriptor: Code intelligence with evidence.
Keep the descriptor separate from the logo, especially at small sizes.

## Source and font

Original concept: https://claude.ai/code/artifact/31a27c6e-43fe-42c5-9786-f73bdda2ae47

Wordmark: Archivo ExtraBold, 800, with modest optical tracking. Font source: https://github.com/Omnibus-Type/Archivo

Archivo is distributed under the SIL Open Font License 1.1. The font's license is included as Archivo-OFL.txt. Font binaries are not needed for the outlined artwork and are not included in this pack.

The application examples in the review document are design mockups. They are not a deployment record.

