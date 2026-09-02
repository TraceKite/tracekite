import { useEffect, useState } from "react";
import { Zap } from "lucide-react";
import { api } from "@/lib/api";
import { isPreviewMode } from "@/lib/previewFixtures";
import { useGraphStore } from "@/store/graphStore";
import TraceCanvas from "@/components/TraceCanvas";
import TraceSidebar from "@/components/TraceSidebar";
import GraphCanvasMessage from "@/components/GraphCanvasMessage";

export default function TraceView() {
  const { traceData, setTraceData, serviceMapData, setServiceMapData } = useGraphStore();
  const [tracing, setTracing] = useState(false);
  const [traceError, setTraceError] = useState<any>(null);

  // The endpoint suggestions come from the service list, which otherwise only
  // exists after visiting Service Map. Fetch it once if we arrived here first.
  useEffect(() => {
    if (serviceMapData || isPreviewMode()) return;
    api.getServiceMap(0.6).then(setServiceMapData).catch(() => {});
  }, [serviceMapData, setServiceMapData]);

  const handleTrace = async (f: string, t: string, c: number, a: string, h: number, k: number) => {
    setTracing(true);
    setTraceError(null);
    setTraceData(null);
    useGraphStore.getState().setSelectedEdge(null);
    try {
      const data = await api.getTrace(f, t, c, h, k, a);
      setTraceData(data);
    } catch(err: any) {
      try {
        const parsed = JSON.parse(err.message.replace(/^API error \d+: /, ""));
        setTraceError(parsed.detail);
      } catch {
        setTraceError({ error: err.message });
      }
    } finally {
      setTracing(false);
    }
  };

  return (
    <>
      <TraceSidebar onTrace={handleTrace} tracing={tracing} traceError={traceError} />
      <main className="flex-1 relative overflow-hidden bg-[#f5f6f8]">
        <TraceCanvas />
        {!traceData && !tracing && (
          <div className="absolute inset-0 z-10 flex items-center justify-center px-8">
            <div className="max-w-md text-center space-y-3">
              <Zap className="w-8 h-8 mx-auto text-[#9b7a31]" />
              <h3 className="text-lg font-bold text-[#1a1d23]">
                How does one service reach another?
              </h3>
              <p className="text-xs leading-relaxed text-[#8b929e]">
                The Service Map shows the selected estate scope. Trace answers a
                narrower question: pick an origin and a destination, and it
                returns the ranked routes between them — laid out in hop order,
                with the file and line behind every hop.
              </p>
              <p className="text-2xs text-[#8b929e]">
                Pick two services on the left, or open the Service Map, select a
                service and choose <span className="text-[#315b47]">Trace from here</span>.
              </p>
            </div>
          </div>
        )}
        {tracing && (
          <GraphCanvasMessage
            title="Tracing verified paths…"
            detail="Ranking directed routes and collecting file-and-line evidence for every hop."
          />
        )}
        {!tracing && traceData?.paths.length === 0 && (
          <GraphCanvasMessage
            title="No path matches these constraints"
            detail="Lower minimum confidence, allow more hops, or choose another endpoint."
          />
        )}
        {!tracing && traceError && !traceData && (
          <GraphCanvasMessage
            title="Trace unavailable"
            detail={traceError.error === "service_not_found"
              ? "One endpoint is not available in the selected repository scope."
              : String(traceError.error ?? "The trace request failed.")}
            warning
          />
        )}
      </main>
    </>
  );
}
