import { trimLinkToNodes } from "./canvasLinkGeometry.ts";
import { labelPillFor, paintLabelPill } from "./canvasLabelPill.ts";
import type { LabelPill } from "./canvasLabelPill.ts";

/** On-screen node radius in CSS pixels, before the zoom divide. */
export function nodeRadius(node: any): number {
  return node?.is_gateway ? 13 : node?.dead_end ? 6 : 9;
}

/** Opacity of a node, and its label, outside the focused neighbourhood. */
const DIMMED_NODE_ALPHA = 0.12;

export interface ServiceNodePaint {
  dimmed: boolean;
}

/** The disc and its scope badge. The name is painted separately, by
 * paintServiceLabel, and only for the nodes the placer gave room to. */
export function paintServiceNode(
  node: any,
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  { dimmed }: ServiceNodePaint,
): void {
  const isGateway = node.is_gateway;
  const isDeadEnd = node.dead_end;
  const radius = nodeRadius(node) / globalScale;

  ctx.save();
  if (dimmed) ctx.globalAlpha = DIMMED_NODE_ALPHA;
  ctx.beginPath();

  if (isGateway) {
    for (let i = 0; i < 6; i++) {
      const angle = (Math.PI / 3) * i;
      const hx = node.x + radius * Math.cos(angle);
      const hy = node.y + radius * Math.sin(angle);
      if (i === 0) ctx.moveTo(hx, hy);
      else ctx.lineTo(hx, hy);
    }
    ctx.closePath();
    ctx.fillStyle = "rgba(49, 91, 71, 0.15)";
    ctx.fill();
    ctx.strokeStyle = "#315b47";
    ctx.lineWidth = 2 / globalScale;
    ctx.stroke();
  } else if (isDeadEnd) {
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = "rgba(164, 81, 56, 0.14)";
    ctx.fill();
    ctx.strokeStyle = "#a45138";
    ctx.lineWidth = 1 / globalScale;
    ctx.stroke();
  } else {
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = "rgba(117, 99, 66, 0.13)";
    ctx.fill();
    ctx.strokeStyle = "#756342";
    ctx.lineWidth = 1.5 / globalScale;
    ctx.stroke();
  }

  if (node.scope) {
    const scopeText = node.scope;
    // Screen-space: dividing by globalScale holds the label at a constant
    // on-screen size. At a fixed 4px in GRAPH units this was a smudge at
    // default zoom and grew as you zoomed in — backwards.
    const scopeSize = 10 / globalScale;
    ctx.font = `500 ${scopeSize}px ui-sans-serif, system-ui, sans-serif`;
    const tm = ctx.measureText(scopeText);
    ctx.fillStyle = "#eeeae1";
    ctx.beginPath();
    ctx.roundRect(node.x - tm.width / 2 - 2 / globalScale, node.y - radius - scopeSize * 1.7,
                  tm.width + 4 / globalScale, scopeSize * 1.4, 2 / globalScale);
    ctx.fill();
    ctx.fillStyle = "#6e7168";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(scopeText, node.x, node.y - radius - scopeSize);
  }
  ctx.restore();
}

export interface ServiceLabelPaint {
  /** As placed: the same box the placer tested, so what fits is what is drawn. */
  pill: LabelPill;
  dimmed: boolean;
}

export function paintServiceLabel(
  node: any,
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  { pill, dimmed }: ServiceLabelPaint,
): void {
  ctx.save();
  if (dimmed) ctx.globalAlpha = DIMMED_NODE_ALPHA;
  paintLabelPill(ctx, globalScale, pill, node.dead_end ? "#dc2626" : "#1a1d23");
  ctx.restore();
}

/** The box a node's label will occupy, measured once per frame by the placer
 * and handed to paintServiceLabel as it stands, so the label is drawn in
 * exactly the rectangle that was tested for room. */
export function serviceLabelBox(
  node: any,
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  label: string,
  labelBudgetPx: number,
): LabelPill {
  return labelPillFor(ctx, globalScale, {
    centerX: node.x,
    anchorY: node.y + nodeRadius(node) / globalScale,
    text: label,
    budgetPx: labelBudgetPx,
  });
}

export interface ServiceLinkPaint {
  color: string;
  /** Stroke opacity and dash pattern for the link's confidence band. */
  opacity: number;
  dash: number[];
  dimmed: boolean;
  selected: boolean;
  /** False when a highlight is active and this link's type is not in it. */
  lit: boolean;
}

/** Opacities for the two ways a link can be pushed into the background.
 *
 * They multiply, so a link that is both off-focus and off-highlight fades
 * further than either alone — which is the honest reading: it is twice
 * removed from what the viewer asked to see. */
const DIM_ALPHA = 0.06;
const UNLIT_ALPHA = 0.07;

export function paintServiceLink(
  link: any,
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  { color, opacity, dash, dimmed, selected, lit }: ServiceLinkPaint,
): void {
  const start = link.source;
  const end = link.target;
  if (!start || !end || start.x == null || end.x == null) return;

  const line = trimLinkToNodes(start, end, {
    startClearancePx: nodeRadius(start) + 3,
    endClearancePx: nodeRadius(end) + 5,
    arrowPx: selected ? 10 : 7,
    globalScale,
  });
  if (!line) return;
  const { sx, sy, ex, ey, arrowLength } = line;

  ctx.save();
  ctx.globalAlpha = (dimmed ? DIM_ALPHA : selected ? 1 : opacity)
    * (lit ? 1 : UNLIT_ALPHA);

  if (selected) {
    ctx.shadowBlur = 8;
    ctx.shadowColor = color;
    ctx.lineWidth = 4 / globalScale;
    ctx.strokeStyle = "rgba(37,40,33,0.18)";
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(ex, ey);
    ctx.stroke();
  }

  ctx.strokeStyle = color;
  ctx.lineWidth = (selected ? 2.5 : 1.5) / globalScale;
  ctx.setLineDash(dash.map((d: number) => d / globalScale));
  ctx.beginPath();
  ctx.moveTo(sx, sy);
  ctx.lineTo(ex, ey);
  ctx.stroke();
  ctx.setLineDash([]);

  const angle = Math.atan2(ey - sy, ex - sx);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(ex, ey);
  ctx.lineTo(ex - arrowLength * Math.cos(angle - Math.PI / 6),
             ey - arrowLength * Math.sin(angle - Math.PI / 6));
  ctx.lineTo(ex - arrowLength * Math.cos(angle + Math.PI / 6),
             ey - arrowLength * Math.sin(angle + Math.PI / 6));
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}
