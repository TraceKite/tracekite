import { useEffect, useMemo, useState } from "react";
import { isPreviewMode } from "@/lib/previewFixtures";
import { X, Copy, ArrowDownLeft, ArrowUpRight, Users, ArrowLeftRight, FileCode } from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import { api } from "@/lib/api";
import { getNodeColor } from "@/lib/graphStyle";
import type { NodeDetail } from "@/lib/types";

export default function NodeDetailsDrawer() {
  const { selectedNode, setSelectedNode, selectedRepo, nodes, links,
          setFocusNode } = useGraphStore();
  // With several repos on the canvas the selected node may not belong to
  // `selectedRepo`, and asking the wrong repo for its details returns a 404.
  // Nodes are tagged with their origin when the graphs are merged.
  const nodeRepoId = (selectedNode as any)?.repo_id ?? selectedRepo?.id ?? null;
  const [details, setDetails] = useState<NodeDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [fetchFailed, setFetchFailed] = useState(false);

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

  // The drawer used to gate EVERY section on the API response, so a failed
  // enrichment call rendered an empty "Properties" box and nothing else — even
  // though the graph on screen already knows this node's edges. Derive
  // relationships from the loaded graph and let the API only enrich.
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

  const handleCopyPath = () => {
    if (selectedNode?.path) navigator.clipboard.writeText(selectedNode.path);
  };

  if (!selectedNode) {
    return (
      <aside className="w-80 flex-shrink-0 flex items-center justify-center"
        style={{ background: "rgba(17,24,39,0.5)", borderLeft: "1px solid #2b313a" }}>
        <div className="text-center px-6">
          <FileCode className="w-8 h-8 mx-auto mb-2" style={{ color: "#3b424c" }} />
          <p className="text-sm" style={{ color: "#8c949e" }}>Click on a node in the graph to view its details</p>
        </div>
      </aside>
    );
  }

  const nodeColor = getNodeColor(selectedNode.type);
  // The canvas draws a capped sample while search queries the whole repo, so a
  // hit can be perfectly real and still not be on screen. Saying so beats
  // leaving the user hunting the canvas for a node that was never drawn.
  const onCanvas = (nodes as any[]).some((n) => n.id === selectedNode.id);

  return (
    <aside className="w-80 flex-shrink-0 flex flex-col overflow-hidden"
      style={{ background: "rgba(17,24,39,0.5)", borderLeft: "1px solid #2b313a", animation: "fadeIn 0.2s ease-out" }}>

      <div className="p-4 flex-shrink-0" style={{ borderBottom: "1px solid #2b313a" }}>
        <div className="flex items-start justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <div className="w-3 h-3 rounded-full flex-shrink-0" style={{ backgroundColor: nodeColor, boxShadow: `0 0 8px ${nodeColor}80` }} />
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-[#e9ecef] truncate">{selectedNode.label}</h3>
              <span className="text-2xs text-[#8c949e] px-1.5 py-0.5 rounded" style={{ background: "#2b313a" }}>{selectedNode.type}</span>
            </div>
          </div>
          <button onClick={() => setSelectedNode(null)} className="text-[#8c949e] hover:text-[#e9ecef] transition-colors flex-shrink-0">
            <X className="w-4 h-4" />
          </button>
        </div>

        {!onCanvas && (
          <div className="mt-2 space-y-1.5">
            <p className="text-2xs text-amber-300/90 leading-relaxed">
              Found by search, but outside the part of the graph currently drawn
              — the canvas shows a capped sample.
            </p>
            {nodeRepoId && (
              <button
                onClick={() => setFocusNode(selectedNode.id, nodeRepoId)}
                className="w-full text-2xs px-2 py-1.5 rounded-md bg-blue-500/20
                           text-blue-300 hover:bg-blue-500/30 transition-colors"
              >
                Show it on the graph
              </button>
            )}
          </div>
        )}

        <div className="flex items-center gap-1 mt-3">
          <button onClick={handleCopyPath}
            className="flex items-center gap-1 px-2 py-1 rounded-md text-2xs text-[#8c949e] hover:text-[#e9ecef] hover:bg-white/5 transition-colors">
            <Copy className="w-3 h-3" /> Copy path
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <div className="w-6 h-6 border-2 border-blue-500/30 border-t-blue-500 rounded-full animate-spin" />
          </div>
        ) : (
          <>
            {fetchFailed && (
              <div className="rounded-md px-3 py-2 text-2xs leading-relaxed
                              bg-amber-500/10 border border-amber-500/25 text-amber-300">
                Couldn't load the full record for this node — showing what the loaded
                graph knows. Relationships below may be limited to what's on screen.
              </div>
            )}

            <div className="space-y-2">
              <h4 className="text-2xs font-semibold text-[#8c949e] uppercase tracking-wider">Properties</h4>
              <div className="rounded-lg p-3 space-y-2" style={{ background: "rgba(30,41,59,0.6)", border: "1px solid rgba(255,255,255,0.05)" }}>
                {/* Always render the facts the graph already carries. Gating
                    these on the API response is what produced an empty box. */}
                <div>
                  <span className="text-2xs text-[#8c949e]">Name</span>
                  <p className="text-xs text-[#e9ecef] break-all">{selectedNode.name || selectedNode.label}</p>
                </div>
                <div>
                  <span className="text-2xs text-[#8c949e]">Type</span>
                  <p className="text-xs text-[#e9ecef]">{selectedNode.type}</p>
                </div>
                {selectedNode.path && (
                  <div>
                    <span className="text-2xs text-[#8c949e]">Path</span>
                    <p className="text-xs text-[#e9ecef] font-mono break-all">{selectedNode.path}</p>
                  </div>
                )}
                {selectedNode.language && (
                  <div>
                    <span className="text-2xs text-[#8c949e]">Language</span>
                    <p className="text-xs text-[#e9ecef]">{selectedNode.language}</p>
                  </div>
                )}
                {selectedNode.group && selectedNode.group !== selectedNode.type && (
                  <div>
                    <span className="text-2xs text-[#8c949e]">Group</span>
                    <p className="text-xs text-[#e9ecef]">{selectedNode.group}</p>
                  </div>
                )}
                <div>
                  <span className="text-2xs text-[#8c949e]">Node ID</span>
                  <p className="text-xs text-[#8c949e] font-mono break-all">{selectedNode.id}</p>
                </div>
                {Object.keys(metadata).length > 0 && (
                  <div className="space-y-1">
                    {Object.entries(metadata).map(([key, value]) => (
                      <div key={key}>
                        <span className="text-2xs text-[#8c949e]">{key}</span>
                        <p className="text-xs text-[#e9ecef] font-mono">
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
                <h4 className="text-2xs font-semibold text-[#8c949e] uppercase tracking-wider flex items-center gap-1">
                  <ArrowDownLeft className="w-3 h-3" /> Incoming ({incoming.length})
                </h4>
                <div className="space-y-1">
                  {incoming.slice(0, 10).map((rel: any, i: number) => (
                    <div key={i} className="rounded-md p-2 text-xs flex items-center gap-2" style={{ background: "rgba(30,41,59,0.4)" }}>
                      <span className="text-2xs text-blue-400 px-1.5 py-0.5 rounded" style={{ background: "rgba(59,130,246,0.1)" }}>{rel.relationship}</span>
                      <span className="text-[#e9ecef] truncate flex-1">{rel.node_label}</span>
                    </div>
                  ))}
                  {incoming.length > 10 && <p className="text-2xs text-[#8c949e] text-center">+{incoming.length - 10} more</p>}
                </div>
              </div>
            )}

            {outgoing.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-2xs font-semibold text-[#8c949e] uppercase tracking-wider flex items-center gap-1">
                  <ArrowUpRight className="w-3 h-3" /> Outgoing ({outgoing.length})
                </h4>
                <div className="space-y-1">
                  {outgoing.slice(0, 10).map((rel: any, i: number) => (
                    <div key={i} className="rounded-md p-2 text-xs flex items-center gap-2" style={{ background: "rgba(30,41,59,0.4)" }}>
                      <span className="text-2xs text-green-400 px-1.5 py-0.5 rounded" style={{ background: "rgba(34,197,94,0.1)" }}>{rel.relationship}</span>
                      <span className="text-[#e9ecef] truncate flex-1">{rel.node_label}</span>
                    </div>
                  ))}
                  {outgoing.length > 10 && <p className="text-2xs text-[#8c949e] text-center">+{outgoing.length - 10} more</p>}
                </div>
              </div>
            )}

            {details?.neighbors && details.neighbors.length > 0 && (
              <div className="space-y-2">
                <h4 className="text-2xs font-semibold text-[#8c949e] uppercase tracking-wider flex items-center gap-1">
                  <Users className="w-3 h-3" /> Neighbors ({details.neighbors.length})
                </h4>
                <div className="space-y-1">
                  {details.neighbors.slice(0, 8).map((n) => (
                    <div key={n.id}
                      onClick={() => {
                        setSelectedNode({
                          id: n.id, type: n.type, label: n.label, name: n.label,
                          path: n.path || undefined, size: 8, group: n.type, metadata: {},
                        });
                      }}
                      className="rounded-md p-2 text-xs flex items-center gap-2 cursor-pointer hover:bg-white/5 transition-colors"
                      style={{ background: "rgba(30,41,59,0.4)" }}>
                      <ArrowLeftRight className="w-3 h-3 text-[#8c949e] flex-shrink-0" />
                      <span className="text-[#e9ecef] truncate flex-1">{n.label}</span>
                      <span className="text-2xs text-[#8c949e] flex-shrink-0">{n.type}</span>
                    </div>
                  ))}
                  {details.neighbors.length > 8 && <p className="text-2xs text-[#8c949e] text-center">+{details.neighbors.length - 8} more</p>}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </aside>
  );
}
