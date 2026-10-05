import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { isPreviewMode } from "@/lib/previewFixtures";
import { observeLinkRun } from "@/lib/serviceMapRefresh";
import { useGraphStore } from "@/store/graphStore";

export function useServiceMapData(minConfidence: number) {
  const { serviceMapData, setServiceMapData, setError, linkerStatus } = useGraphStore();
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const activeRunId = useRef<string | null>(null);

  useEffect(() => {
    const decision = observeLinkRun(activeRunId.current, linkerStatus?.latest);
    activeRunId.current = decision.activeRunId;
    if (decision.refresh) setRefreshVersion((version) => version + 1);
  }, [linkerStatus?.latest?.id, linkerStatus?.latest?.status]);

  useEffect(() => {
    if (isPreviewMode()) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setLoadError(null);
      api.getServiceMap(minConfidence)
        .then((data) => { if (!cancelled) setServiceMapData(data); })
        .catch((error) => {
          if (cancelled) return;
          setLoadError(error.message);
          setError(error.message);
        })
        .finally(() => { if (!cancelled) setLoading(false); });
    }, refreshVersion ? 0 : 500);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [minConfidence, refreshVersion, setError, setServiceMapData]);

  return { serviceMapData, loading, loadError, setLoadError };
}
