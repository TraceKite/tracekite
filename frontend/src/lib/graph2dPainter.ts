import type { GraphLink, GraphNode } from "@/lib/types";
import {
  getConfidenceStyle,
  getEdgeColor,
  getEdgeWidth,
  getModuleColor,
  getNodeColor,
  getNodeSize,
  graphGroupOf,
  hexToRgb,
} from "@/lib/graphStyle";
import {
  graphLinkId,
  labelIdsForScale,
  type GraphFocusContext,
  type GraphLabelBudget,
} from "@/lib/graph2dProjection";
import { endpointId } from "@/lib/graphVisibility";

type PositionedNode = GraphNode & { x?: number; y?: number; module?: string };

export interface NodePaintOptions {
  selectedId: string | null;
  hoveredId: string | null;
  focus: GraphFocusContext;
  highlightedNodeIds: Set<string>;
  labels: GraphLabelBudget;
  showLabels: boolean;
  moduleOrder: string[];
  labelOccupancy: Array<{ left: number; right: number; top: number; bottom: number }>;
}

export interface LinkPaintOptions {
  nodeIndex: Map<string, PositionedNode>;
  focus: GraphFocusContext;
  highlightedTypes: string[];
  showParticles: boolean;
}

export function paintModuleRegions(
  ctx: CanvasRenderingContext2D,
  nodes: PositionedNode[],
  globalScale: number,
  moduleOrder: string[],
  labelOccupancy: Array<{ left: number; right: number; top: number; bottom: number }>,
) {
  if (moduleOrder.length < 2) return;
  const groups = new Map<string, PositionedNode[]>();
  for (const node of nodes) {
    if (node.x == null || node.y == null) continue;
    const groupKey = node.type === "ModuleGroup"
      ? String(node.metadata.group_key ?? "")
      : graphGroupOf(node);
    const key = node.type === "ModuleGroup"
      ? groupKey.split("/").slice(0, 2).join("/")
      : groupKey;
    const group = groups.get(key) ?? [];
    group.push(node);
    groups.set(key, group);
  }
  const visibleGroups = [...groups.entries()]
    .filter(([, group]) => group.length >= 4)
    .sort((a, b) => b[1].length - a[1].length)
    .slice(0, 8);
  for (const [regionIndex, [key, group]] of visibleGroups.entries()) {
    const xs = group.map((node) => node.x as number);
    const ys = group.map((node) => node.y as number);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const pad = 22 / Math.max(globalScale, 0.2);
    const centerX = (minX + maxX) / 2;
    const centerY = (minY + maxY) / 2;
    const radiusX = Math.max(28 / globalScale, (maxX - minX) / 2 + pad);
    const radiusY = Math.max(24 / globalScale, (maxY - minY) / 2 + pad);
    const color = getModuleColor(key, moduleOrder) ??
      (regionIndex % 2 === 0 ? "#315b47" : "#a45138");
    const rgb = hexToRgb(color);
    ctx.save();
    ctx.fillStyle = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.035)`;
    ctx.strokeStyle = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.30)`;
    ctx.lineWidth = 1 / globalScale;
    ctx.setLineDash([5 / globalScale, 5 / globalScale]);
    ctx.beginPath();
    ctx.ellipse(centerX, centerY, radiusX, radiusY, 0, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    if (globalScale > 0.42) {
      ctx.setLineDash([]);
      ctx.fillStyle = "#4d5049";
      ctx.font = `${600} ${11 / globalScale}px ui-monospace, monospace`;
      ctx.textAlign = "left";
      const label = `${key} · ${group.length}`;
      const labelX = centerX - radiusX;
      const labelY = centerY - radiusY - 7 / globalScale;
      const width = ctx.measureText(label).width;
      const rect = {
        left: labelX,
        right: labelX + width,
        top: labelY - 12 / globalScale,
        bottom: labelY + 3 / globalScale,
      };
      const overlaps = labelOccupancy.some((item) =>
        rect.left < item.right && rect.right > item.left &&
        rect.top < item.bottom && rect.bottom > item.top);
      if (!overlaps) {
        labelOccupancy.push(rect);
        ctx.fillText(label, labelX, labelY);
      }
    }
    ctx.restore();
  }
}

export function paintNode(
  node: PositionedNode,
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  options: NodePaintOptions,
) {
  if (node.x == null || node.y == null) return;
  const type = node.type || "File";
  const color = getNodeColor(type);
  const groupColor = getModuleColor(graphGroupOf(node), options.moduleOrder);
  const aggregate = type === "ModuleGroup";
  const displayColor = aggregate && groupColor ? groupColor : color;
  const radius = getNodeSize(type, Math.min(node.size || 5, 10)) * 0.55;
  const selected = node.id === options.selectedId;
  const hovered = node.id === options.hoveredId;
  const focusActive = options.focus.nodeIds.size > 0;
  const inFocus = !focusActive || options.focus.nodeIds.has(node.id);
  const highlightActive = options.highlightedNodeIds.size > 0;
  const highlighted = !highlightActive || options.highlightedNodeIds.has(node.id);
  const alpha = (inFocus ? 1 : 0.11) * (highlighted ? 1 : 0.16);

  ctx.save();
  ctx.globalAlpha = aggregate ? alpha * 0.15 : alpha;
  ctx.fillStyle = displayColor;
  ctx.beginPath();
  ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
  ctx.fill();
  if (groupColor) {
    ctx.globalAlpha = alpha;
    ctx.strokeStyle = groupColor;
    ctx.lineWidth = 1.4 / globalScale;
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius + 1.8 / globalScale, 0, Math.PI * 2);
    ctx.stroke();
  }
  if (aggregate) {
    ctx.globalAlpha = alpha;
    ctx.fillStyle = displayColor;
    ctx.beginPath();
    ctx.arc(node.x, node.y, 5.5 / Math.max(globalScale, 0.35), 0, Math.PI * 2);
    ctx.fill();
  }
  if (selected || hovered) {
    ctx.strokeStyle = selected ? "#252821" : "#6e7168";
    ctx.lineWidth = (selected ? 2.6 : 1.8) / globalScale;
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius + 4 / globalScale, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.restore();

  if (!options.showLabels || hovered) return;
  const labelIds = labelIdsForScale(options.labels, globalScale, focusActive);
  if (!labelIds.has(node.id) || !inFocus) return;
  const label = String(node.label || node.name || "").slice(0, 42);
  if (!label) return;
  const pxScale = 1 / Math.max(globalScale, 0.1);
  const fontSize = 11 * pxScale;
  ctx.save();
  ctx.globalAlpha = Math.max(alpha, selected ? 1 : 0.72);
  ctx.font = `600 ${fontSize}px ui-sans-serif, system-ui, sans-serif`;
  const metrics = ctx.measureText(label);
  const paddingX = 6 * pxScale;
  const pillW = metrics.width + paddingX * 2;
  const pillH = 18 * pxScale;
  const pillX = node.x - pillW / 2;
  const pillY = node.y - radius - 8 * pxScale - pillH;
  const labelRect = {
    left: pillX - 3 * pxScale,
    right: pillX + pillW + 3 * pxScale,
    top: pillY - 2 * pxScale,
    bottom: pillY + pillH + 2 * pxScale,
  };
  const overlaps = options.labelOccupancy.some((item) =>
    labelRect.left < item.right && labelRect.right > item.left &&
    labelRect.top < item.bottom && labelRect.bottom > item.top);
  if (overlaps && !selected) return;
  options.labelOccupancy.push(labelRect);
  ctx.fillStyle = "rgba(255, 254, 250, 0.96)";
  ctx.strokeStyle = groupColor ?? color;
  ctx.lineWidth = 1 * pxScale;
  ctx.beginPath();
  ctx.roundRect(pillX, pillY, pillW, pillH, 4 * pxScale);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#252821";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, node.x, pillY + pillH / 2);
  ctx.restore();
}

export function paintNodePointerArea(
  node: PositionedNode,
  color: string,
  ctx: CanvasRenderingContext2D,
) {
  if (node.x == null || node.y == null) return;
  const radius = getNodeSize(node.type || "File", Math.min(node.size || 5, 10)) * 0.55 + 6;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(node.x, node.y, Math.max(12, radius), 0, Math.PI * 2);
  ctx.fill();
}

export function paintLink(
  link: GraphLink,
  ctx: CanvasRenderingContext2D,
  globalScale: number,
  options: LinkPaintOptions,
) {
  const start = typeof link.source === "object"
    ? link.source as PositionedNode
    : options.nodeIndex.get(endpointId(link.source));
  const end = typeof link.target === "object"
    ? link.target as PositionedNode
    : options.nodeIndex.get(endpointId(link.target));
  if (start?.x == null || start.y == null || end?.x == null || end.y == null) return;
  const type = link.type || "RELATED_TO";
  const emphasized = options.highlightedTypes.includes(type);
  const focusActive = options.focus.linkIds.size > 0;
  const incident = !focusActive || options.focus.linkIds.has(graphLinkId(link));
  const lit = options.highlightedTypes.length === 0 || emphasized;
  const alpha = (incident ? 1 : 0.06) * (lit ? 1 : 0.08);
  const color = getEdgeColor(type);
  const aggregateWidth = link.aggregate
    ? Math.min(4.2, 1.2 + Math.log2((link.member_count ?? 1) + 1) * 0.55)
    : getEdgeWidth(type);
  const width = aggregateWidth * (emphasized ? 1.8 : 1);
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const len = Math.hypot(dx, dy) || 1;
  const sourceRadius = getNodeSize(start.type, Math.min(start.size || 5, 10)) * 0.55;
  const targetRadius = getNodeSize(end.type, Math.min(end.size || 5, 10)) * 0.55;
  const sx = start.x + (dx / len) * Math.min(len * 0.45, sourceRadius + 2);
  const sy = start.y + (dy / len) * Math.min(len * 0.45, sourceRadius + 2);
  const ex = end.x - (dx / len) * Math.min(len * 0.45, targetRadius + 2);
  const ey = end.y - (dy / len) * Math.min(len * 0.45, targetRadius + 2);
  const confidence = getConfidenceStyle(link.confidence);
  ctx.save();
  ctx.globalAlpha = alpha * confidence.opacity;
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(0.55, width) / globalScale;
  ctx.lineCap = "round";
  ctx.setLineDash(confidence.dash.map((value) => value / globalScale));
  ctx.beginPath();
  ctx.moveTo(sx, sy);
  ctx.lineTo(ex, ey);
  ctx.stroke();
  ctx.setLineDash([]);

  const showDirection = incident && (link.aggregate || focusActive || emphasized || globalScale > 1.35);
  if (showDirection) {
    const angle = Math.atan2(dy, dx);
    const arrow = (6 + width) / globalScale;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(ex, ey);
    ctx.lineTo(ex - arrow * Math.cos(angle - Math.PI / 6), ey - arrow * Math.sin(angle - Math.PI / 6));
    ctx.lineTo(ex - arrow * Math.cos(angle + Math.PI / 6), ey - arrow * Math.sin(angle + Math.PI / 6));
    ctx.closePath();
    ctx.fill();
  }
  if (options.showParticles && showDirection) {
    const phase = ((Date.now() * 0.0012 + ((link as any).__phase ?? 0)) % 1);
    ctx.fillStyle = "#252821";
    ctx.beginPath();
    ctx.arc(sx + (ex - sx) * phase, sy + (ey - sy) * phase, 1.6 / globalScale, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.restore();
}
