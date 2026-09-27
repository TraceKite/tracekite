/** The name plate drawn under a node on a 2D canvas.
 *
 * The service map and the trace canvas had drawn this independently, down to
 * the same six magic numbers — the 3px side padding, the 1.35 line box, the
 * 3px corner. Two copies of a pill is not a crisis on its own; two copies that
 * drift are, because the placer decides whether a label fits by measuring a
 * rectangle and the painter then draws a different one.
 *
 * So the box is defined once and returned as the same `LabelRect` the placer
 * speaks, which makes "where the label goes" and "whether the label fits" two
 * halves of one fact rather than two calculations that have to be kept equal.
 *
 * Everything is screen-space, divided by the zoom into the graph units the
 * canvas is transformed into, so a pill is the same size at every zoom.
 */

import { fitServiceLabel } from "./serviceMapLabel.ts";
import type { LabelRect } from "./canvasLabelSpace.ts";

/** Constant on-screen size; in graph units this was illegible when zoomed out
 * and grew as you zoomed in, which is backwards. */
const LABEL_FONT_PX = 12;
const PAD_X_PX = 3;
const GAP_PX = 2;
const LINE_BOX = 1.35;

export interface LabelPill {
  rect: LabelRect;
  /** The label after shortening — what gets drawn, and what was measured. */
  text: string;
  /** Baseline for the text, already centred in the box. */
  textY: number;
  /** The font it was measured in. A pill measured during placement is painted
   * after other nodes have set their own fonts, so it has to bring its own. */
  font: string;
}

export interface LabelPillRequest {
  /** Node centre, and the bottom of whatever is drawn at it. */
  centerX: number;
  anchorY: number;
  text: string;
  /** Shorten the text to this on-screen width; omit to draw it whole. */
  budgetPx?: number;
}

export function labelPillFor(
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  { centerX, anchorY, text, budgetPx }: LabelPillRequest,
): LabelPill {
  const fontSize = LABEL_FONT_PX / globalScale;
  const font = `600 ${fontSize}px ui-sans-serif, system-ui, sans-serif`;
  ctx.font = font;
  // measureText returns graph units at this font while the budget is in screen
  // pixels, so the scale has to come back out before they can be compared.
  const shown = budgetPx == null
    ? text
    : fitServiceLabel(text, budgetPx,
                      (candidate) => ctx.measureText(candidate).width * globalScale);
  const width = ctx.measureText(shown).width;
  const pad = PAD_X_PX / globalScale;
  const top = anchorY + GAP_PX / globalScale;
  return {
    rect: {
      left: centerX - width / 2 - pad,
      right: centerX + width / 2 + pad,
      top,
      bottom: top + fontSize * LINE_BOX,
    },
    text: shown,
    textY: top + fontSize * 0.7,
    font,
  };
}

export function paintLabelPill(
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  pill: LabelPill,
  textColor: string,
): void {
  const { rect } = pill;
  ctx.fillStyle = "rgba(255, 254, 250, 0.96)";
  ctx.beginPath();
  ctx.roundRect(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top,
                3 / globalScale);
  ctx.fill();

  ctx.fillStyle = textColor;
  ctx.font = pill.font;
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(pill.text, (rect.left + rect.right) / 2, pill.textY);
}
