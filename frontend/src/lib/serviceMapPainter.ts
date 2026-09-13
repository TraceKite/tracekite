import { fitServiceLabel } from "./serviceMapLabel.ts";

/** On-screen node radius in CSS pixels, before the zoom divide. */
export function nodeRadius(node: any): number {
  return node?.is_gateway ? 13 : node?.dead_end ? 6 : 9;
}

export interface ServiceNodePaint {
  dimmed: boolean;
  /** Already disambiguated; this function only has to make it fit. */
  label: string;
  labelBudgetPx: number;
}

export function paintServiceNode(
  node: any,
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  { dimmed, label, labelBudgetPx }: ServiceNodePaint,
): void {
  const isGateway = node.is_gateway;
  const isDeadEnd = node.dead_end;
  const radius = nodeRadius(node) / globalScale;

  ctx.save();
  if (dimmed) ctx.globalAlpha = 0.12;
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

  const labelSize = 12 / globalScale;
  ctx.font = `600 ${labelSize}px ui-sans-serif, system-ui, sans-serif`;
  // measureText returns graph units at this font, and the budget is in screen
  // pixels, so the scale has to come back out before comparing.
  const shown = fitServiceLabel(
    label, labelBudgetPx, (text) => ctx.measureText(text).width * globalScale);
  const tm = ctx.measureText(shown);
  ctx.fillStyle = "rgba(255, 254, 250, 0.96)";
  ctx.beginPath();
  ctx.roundRect(node.x - tm.width / 2 - 3 / globalScale, node.y + radius + 2 / globalScale,
                tm.width + 6 / globalScale, labelSize * 1.35, 3 / globalScale);
  ctx.fill();

  ctx.fillStyle = isDeadEnd ? "#dc2626" : "#1a1d23";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(shown, node.x, node.y + radius + 2 / globalScale + labelSize * 0.7);

  ctx.restore();
}
