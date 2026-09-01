import type { GraphLink, GraphNode } from "./types.ts";

const LOCKFILE_NAMES = [
  "package-lock.json",
  "pnpm-lock.yaml",
  "yarn.lock",
  "bun.lock",
  "bun.lockb",
  "poetry.lock",
  "uv.lock",
  "cargo.lock",
  "go.sum",
  "composer.lock",
  "gemfile.lock",
];

export function endpointId(endpoint: GraphLink["source"]): string {
  return typeof endpoint === "object" ? endpoint?.id : endpoint;
}

export function isLockfileDependencyNode(node: GraphNode): boolean {
  if (node.type !== "Dependency") return false;
  const source = `${node.path ?? ""} ${node.name ?? ""}`.toLowerCase();
  return LOCKFILE_NAMES.some((name) => source.includes(name));
}

export function isNodeVisible(
  node: GraphNode,
  hiddenTypes: string[],
  hideLockfileDependencies: boolean,
): boolean {
  if (hiddenTypes.includes(node.type)) return false;
  return !(hideLockfileDependencies && isLockfileDependencyNode(node));
}

export function isLinkVisible(
  link: GraphLink,
  hiddenTypes: string[],
  visibleNodeIds: Set<string>,
): boolean {
  if (hiddenTypes.includes(link.type)) return false;
  return visibleNodeIds.has(endpointId(link.source)) &&
    visibleNodeIds.has(endpointId(link.target));
}
