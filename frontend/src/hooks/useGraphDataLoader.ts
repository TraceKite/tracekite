import { useEffect, useMemo } from "react";
import { useGraphStore } from "@/store/graphStore";
import { api } from "@/lib/api";
import { isPreviewMode } from "@/lib/previewFixtures";
import { effectiveRepoIds } from "@/lib/graphNavigation";

const EMPTY_STATS = {
  total_nodes: 0,
  total_edges: 0,
  node_types: {},
  edge_types: {},
  files: 0,
  apis: 0,
  dependencies: 0,
  external_systems: 0,
};

export function useGraphDataLoader() {
  const {
    selectedRepo,
    repos,
    scopeRepoIds,
    setBridgeCount,
    setBridgeStatus,
    focusNodeId,
    focusNodeRepo,
    setGraphData,
    viewMode,
    setLoadingGraph,
    setError,
  } = useGraphStore();

  const repoIds = useMemo(
    () => effectiveRepoIds(repos, scopeRepoIds, selectedRepo),
    [repos, scopeRepoIds, selectedRepo]
  );
  const repoKey = repoIds.join(",");

  useEffect(() => {
    if (!repoKey) return;
    if (isPreviewMode()) return;

    let cancelled = false;
    setLoadingGraph(true);
    setError(null);

    if (focusNodeId && focusNodeRepo) {
      api
        .getGraph(focusNodeRepo, {
          view: "impact",
          focus_node_id: focusNodeId,
          depth: 2,
          limit: 150,
        })
        .then((data) => {
          if (cancelled) return;
          const tagged = (data.nodes ?? []).map((node: any) => ({
            ...node,
            repo_id: node.repo_id ?? focusNodeRepo,
          }));
          setBridgeCount(0);
          setBridgeStatus("idle");
          setGraphData(tagged, data.links ?? [], data.stats);
        })
        .catch((err: any) => {
          if (cancelled) return;
          setError(err.message);
        })
        .finally(() => {
          if (!cancelled) setLoadingGraph(false);
        });
      return () => {
        cancelled = true;
      };
    }

    const perRepo = Math.max(30, Math.floor(300 / repoIds.length));
    setBridgeStatus("loading");
    Promise.all([
      ...repoIds.map((id) =>
        api
          .getGraph(id, { view: viewMode, limit: perRepo })
          .then((data) => ({ id, data }))
          .catch(() => null))
      ,
      repoIds.length > 1
        ? api.getCodeBridges(repoIds)
            .then((data) => ({ available: true, data }))
            .catch(() => ({ available: false, data: { nodes: [], links: [] } }))
        : Promise.resolve({ available: true, data: { nodes: [], links: [] } }),
    ])
      .then((results) => {
        if (cancelled) return;
        const bridgeResult = results[results.length - 1] as {
          available: boolean;
          data: { nodes: any[]; links: any[] };
        };
        const bridges = bridgeResult.data;
        const ok = results.slice(0, -1).filter(Boolean) as { id: string; data: any }[];
        if (ok.length === 0) throw new Error("No repository graph could be loaded");
        if (ok.length !== repoIds.length) {
          setError(`Loaded ${ok.length} of ${repoIds.length} repositories in scope.`);
        }

        const byId = new Map<string, any>();
        for (const { id, data } of ok) {
          for (const n of data.nodes ?? []) {
            byId.set(n.id, { ...n, repo_id: n.repo_id ?? id });
          }
        }
        for (const n of bridges.nodes ?? []) {
          byId.set(n.id, { ...(byId.get(n.id) ?? {}), ...n });
        }
        const nodes = [...byId.values()];
        const links = [
          ...ok.flatMap(({ data }) => data.links ?? []),
          ...(bridges.links ?? []),
        ];
        setBridgeCount(bridges.links?.length ?? 0);
        setBridgeStatus(bridgeResult.available ? "ready" : "unavailable");
        const stats =
          ok.length === 1
            ? ok[0].data.stats
            : {
                ...EMPTY_STATS,
                total_nodes: nodes.length,
                total_edges: links.length,
              };
        setGraphData(nodes, links, stats);
      })
      .catch((err: any) => {
        if (cancelled) return;
        setBridgeStatus("unavailable");
        setError(err.message);
      })
      .finally(() => {
        if (!cancelled) setLoadingGraph(false);
      });

    return () => {
      cancelled = true;
    };
  }, [
    repoKey,
    focusNodeId,
    focusNodeRepo,
    viewMode,
    setLoadingGraph,
    setGraphData,
    setBridgeCount,
    setBridgeStatus,
    setError,
  ]);
}
