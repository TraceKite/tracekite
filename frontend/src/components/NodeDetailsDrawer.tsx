import { useEffect, useMemo, useState } from "react";
import { isPreviewMode } from "@/lib/previewFixtures";
import { X, Copy, ArrowDownLeft, ArrowUpRight, Users, ArrowLeftRight, FileCode } from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import { api } from "@/lib/api";
import { getNodeColor } from "@/lib/graphStyle";
import type { GraphNode, NodeDetail } from "@/lib/types";
import { useGraphNavigationStore } from "@/store/graphNavigationStore";

export default function NodeDetailsDrawer() {
  const { selectedNode, setSelectedNode, selectedRepo, nodes, links,
          focusNodeId, setFocusNode, viewMode, setViewMode,
          loadingGraph, setSearchQuery } = useGraphStore();
  const clearExpandedGroup = useGraphNavigationStore(
    (state) => state.clearExpandedGroup);
  const nodeRepoId = (selectedNode as any)?.repo_id ?? selectedRepo?.id ?? null;
  const [details, setDetails] = useState<NodeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchFailed, setFetchFailed] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!selectedNode || !nodeRepoId) {
      setDetails(null);
      return;
    }
    if (isPreviewMode()) { setDetails(null); return; }
    setLoading(true);
    setFetchFailed(false);
    api.getNodeDetails(nodeRepoId, selectedNode.id)
      .then((data) => setDetails(data))
      .catch(() => { setDetails(null); setFetchFailed(true); })
      .finally(() => setLoading(false));
  }, [selectedNode?.id, nodeRepoId]);

  const local = useMemo(() => {
    if (!selectedNode) return { incoming: [], outgoing: [] };
    const byId = new Map((nodes as any[]).map((n) => [n.id, n]));
    const idOf = (v: any) => (typeof v === "object" && v ? v.id : v);
    const incoming: { relationship: string; node_label: string; id: string }[] = [];
    const outgoing: { relationship: string; node_label: string; id: string }[] = [];
    for (const l of links as any[]) {
      const s = idOf(l.source);
      const t = idOf(l.target);
      if (t === selectedNode.id) {
        incoming.push({ relationship: l.type, node_label: byId.get(s)?.label ?? s, id: s });
      } else if (s === selectedNode.id) {
        outgoing.push({ relationship: l.type, node_label: byId.get(t)?.label ?? t, id: t });
      }
    }
    return { incoming, outgoing };
  }, [selectedNode?.id, nodes, links]);

  const incoming = details?.incoming?.length ? details.incoming : local.incoming;
  const outgoing = details?.outgoing?.length ? details.outgoing : local.outgoing;

  const apiMeta = details?.node?.metadata;
  const metadata: Record<string, unknown> =
    apiMeta && typeof apiMeta === "object" && Object.keys(apiMeta).length > 0
      ? (apiMeta as Record<string, unknown>)
      : (selectedNode?.metadata ?? {});

  const handleCopyPath = async () => {
    if (!selectedNode?.path) return;
    await navigator.clipboard.writeText(selectedNode.path);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  const closeNode = () => {
    setSelectedNode(null);
    setSearchQuery("");
    if (focusNodeId) setFocusNode(null);
    if (viewMode === "impact") setViewMode("overview");
  };
  const selectRelatedNode = (node: GraphNode) => {
    setSearchQuery("");
    setSelectedNode(node);
  };
  if (!selectedNode) {
    return (
      <aside className="w-80 flex-shrink-0 flex items-center justify-center"
        style={{ background: "#ffffff", borderLeft: "1px solid #dfe2e8" }}>
        <div className="text-center px-6">
          <FileCode className="w-8 h-8 mx-auto mb-2" style={{ color: "#3b424c" }} />
          <p className="text-sm" style={{ color: "#8b929e" }}>Click on a node in the graph to view its details</p>
        </div>
      </aside>
    );
  }

  const nodeColor = getNodeColor(selectedNode.type);
  const onCanvas = (nodes as any[]).some((n) => n.id === selectedNode.id);
  const loadingFocusedNode = loadingGraph && focusNodeId === selectedNode.id;

  return (
    <aside className="w-80 flex-shrink-0 flex flex-col overflow-hidden"
      style={{ background: "#f4f1e9", borderLeft: "1px solid #c9c3b7", animation: "fadeIn 0.2s ease-out" }}>

      <div className="p-4 flex-shrink-0" style={{ borderBottom: "1px solid #dfe2e8" }}>
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: nodeColor }} />
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-[#1a1d23] truncate">{selectedNode.label}</h3>
              <span className="text-2xs text-[#8b929e] px-1.5 py-0.5 rounded" style={{ background: "#f1f5f9" }}>{selectedNode.type}</span>
            </div>
          </div>
          <button onClick={closeNode} aria-label="Close node details" className="text-[#8b929e] hover:text-[#1a1d23] transition-colors flex-shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>

        {!onCanvas && (
          <div className="mt-2 space-y-1.5">
            <p className="text-2xs text-[#6f5723] leading-relaxed">
              {loadingFocusedNode
                ? "Loading this node's exact neighborhood…"
                : "Found by search, but outside the capped graph currently drawn."}
            </p>
            {nodeRepoId && !loadingFocusedNode && (
              <button
                onClick={() => {
                  clearExpandedGroup();
                  setFocusNode(selectedNode.id, nodeRepoId);
                }}
                className="w-full text-2xs px-2 py-1.5 rounded-md bg-[#315b47]/10
                           text-[#274a3a] hover:bg-[#315b47]/15 transition-colors"
              >
                Load this node's neighborhood
              </button>
            )}
          </div>
        )}

        <div className="flex items-center gap-1 mt-3">
          <button onClick={handleCopyPath} disabled={!selectedNode.path}
            className="flex items-center gap-1 px-2 py-1 rounded-md text-2xs text-[#8b929e] hover:text-[#1a1d23] hover:bg-slate-100 transition-colors">
            <Copy className="w-3 h-3" /> {copied ? "Copied" : "Copy path"}
          </button>
          <span className="sr-only" aria-live="polite">{copied ? "Path copied" : ""}</span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div className="w-6 h-6 border-2 border-[#c9c3b7] border-t-[#9b7a31] rounded-full animate-spin" />
          </div>
        ) : (
          <>
            {fetchFailed && (
              <div className="rounded-md px-3 py-2 text-2xs leading-relaxed
                              bg-amber-50 border border-amber-200 text-amber-600">
                Couldn't load the full record for this node — showing what the loaded
                graph knows. Relationships below may be limited to what's on screen.
              </div>
            )}

            <div className="space-y-2">
              <h4 className="text-2xs font-semibold text-[#8b929e] uppercase tracking-wider">Properties</h4>
              <div className="rounded-lg p-3 space-y-2" style={{ background: "#f1f5f9", border: "1px solid #e2e8f0" }}>
                <div>
                  <span className="text-2xs text-[#8b929e]">Name</span>
                  <p className="text-xs text-[#1a1d23] break-all">{selectedNode.name || selectedNode.label}</p>
                </div>
                <div>
                  <span className="text-2xs text-[#8b929e]">Type</span>
                  <p className="text-xs text-[#1a1d23]">{selectedNode.type}</p>
                </div>
                {selectedNode.path && (
                  <div>
                    <span className="text-2xs text-[#8b929e]">Path</span>
                    <p className="text-xs text-[#1a1d23] font-mono break-all">{selectedNode.path}</p>
                  </div>
                )}
                {selectedNode.language && (
                  <div>
                    <span className="text-2xs text-[#8b929e]">Language</span>
                    <p className="text-xs text-[#1a1d23]">{selectedNode.language}</p>
                  </div>
                )}
                {selectedNode.group && selectedNode.group !== selectedNode.type && (
                  <div>
                    <span className="text-2xs text-[#8b929e]">Group</span>
                    <p className="text-xs text-[#1a1d23]">{selectedNode.group}</p>
                  </div>
                )}
                <div>
                  <span className="text-2xs text-[#8b929e]">Node ID</span>
                  <p className="text-xs text-[#8b929e] font-mono break-all">{selectedNode.id}</p>
                </div>
                {Object.keys(metadata).length > 0 && (
                  <div className="space-y-1">
                    {Object.entries(metadata).map(([key, value]) => (
                      <div key={key}>
                        <span className="text-2xs text-[#8b929e]">{key}</span>
                        <p className="text-xs text-[#1a1d23] font-mono">
                          {typeof value === "object" ? JSON.stringify(value) : String(value)}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {incoming.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-2xs font-semibold text-[#8b929e] uppercase tracking-wider flex items-center gap-1">
                  <ArrowDownLeft className="w-3 h-3" /> Incoming ({incoming.length})
                </h4>
                <div className="space-y-1">
                  {incoming.slice(0, 10).map((rel: any, i: number) => (
                    <button
                      type="button"
                      key={i}
                      onClick={() => {
                        const relationNodeId = rel.node_id ?? rel.id;
                        const targetNode = nodes.find((n) => n.id === relationNodeId);
                        selectRelatedNode(targetNode ?? ({
                          id: relationNodeId, type: rel.node_type ?? "Node",
                          label: rel.node_label, name: rel.node_label, size: 8,
                          group: rel.node_type ?? "Node", metadata: {}, repo_id: nodeRepoId,
                        } as GraphNode));
                      }}
                      className="w-full rounded-md p-2 text-left text-xs flex items-center gap-2 hover:bg-slate-200 transition-colors"
                      style={{ background: "#f1f5f9" }}
                    >
                      <span className="text-2xs text-[#7f3e2d] px-1.5 py-0.5 rounded bg-[#a45138]/10">{rel.relationship}</span>
                      <span className="text-[#1a1d23] truncate flex-1">{rel.node_label}</span>
                    </button>
                  ))}
                  {incoming.length > 10 && <p className="text-2xs text-[#8b929e] text-center">+{incoming.length - 10} more</p>}
                </div>
              </div>
            )}

            {outgoing.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-2xs font-semibold text-[#8b929e] uppercase tracking-wider flex items-center gap-1">
                  <ArrowUpRight className="w-3 h-3" /> Outgoing ({outgoing.length})
                </h4>
                <div className="space-y-1">
                  {outgoing.slice(0, 10).map((rel: any, i: number) => (
                    <button
                      type="button"
                      key={i}
                      onClick={() => {
                        const relationNodeId = rel.node_id ?? rel.id;
                        const targetNode = nodes.find((n) => n.id === relationNodeId);
                        selectRelatedNode(targetNode ?? ({
                          id: relationNodeId, type: rel.node_type ?? "Node",
                          label: rel.node_label, name: rel.node_label, size: 8,
                          group: rel.node_type ?? "Node", metadata: {}, repo_id: nodeRepoId,
                        } as GraphNode));
                      }}
                      className="w-full rounded-md p-2 text-left text-xs flex items-center gap-2 hover:bg-slate-200 transition-colors"
                      style={{ background: "#f1f5f9" }}
                    >
                      <span className="text-2xs text-[#274a3a] px-1.5 py-0.5 rounded bg-[#315b47]/10">{rel.relationship}</span>
                      <span className="text-[#1a1d23] truncate flex-1">{rel.node_label}</span>
                    </button>
                  ))}
                  {outgoing.length > 10 && <p className="text-2xs text-[#8b929e] text-center">+{outgoing.length - 10} more</p>}
                </div>
              </div>
            )}

            {details?.neighbors && details.neighbors.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-2xs font-semibold text-[#8b929e] uppercase tracking-wider flex items-center gap-1">
                  <Users className="w-3 h-3" /> Neighbors ({details.neighbors.length})
                </h4>
                <div className="space-y-1">
                  {details.neighbors.slice(0, 8).map((n) => (
                    <button key={n.id} type="button"
                      onClick={() => {
                        selectRelatedNode({
                          id: n.id, type: n.type, label: n.label, name: n.label,
                          path: n.path || undefined, size: 8, group: n.type,
                          metadata: {}, repo_id: nodeRepoId,
                        } as GraphNode);
                      }}
                      className="w-full rounded-md p-2 text-left text-xs flex items-center gap-2 hover:bg-slate-100 transition-colors"
                      style={{ background: "#f1f5f9" }}>
                      <ArrowLeftRight className="w-3 h-3 text-[#8b929e] flex-shrink-0" />
                      <span className="text-[#1a1d23] truncate flex-1">{n.label}</span>
                      <span className="text-2xs text-[#8b929e] flex-shrink-0">{n.type}</span>
                    </button>
                  ))}
                  {details.neighbors.length > 8 && <p className="text-2xs text-[#8b929e] text-center">+{details.neighbors.length - 8} more</p>}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
