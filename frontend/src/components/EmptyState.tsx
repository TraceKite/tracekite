import { GitGraph, ArrowUp } from "lucide-react";

export default function EmptyState() {
  return (
    <div className="absolute inset-0 flex items-center justify-center" style={{ animation: "fadeIn 0.5s ease-out" }}>
      <div className="text-center space-y-6">
        <div className="relative inline-block">
          <div className="w-24 h-24 rounded-full flex items-center justify-center mx-auto"
            style={{
              background: "linear-gradient(135deg, rgba(59,130,246,0.08), rgba(139,92,246,0.08))",
              border: "1px solid rgba(59,130,246,0.15)",
              boxShadow: "0 0 20px rgba(59,130,246,0.08)",
            }}>
            <GitGraph className="w-10 h-10" style={{ color: "#315b47" }} />
          </div>
          <div className="absolute inset-0" style={{ animation: "spin 8s linear infinite" }}>
            <div className="absolute -top-1 left-1/2 w-2 h-2 rounded-full"
              style={{ background: "#315b47", boxShadow: "0 0 6px rgba(49,91,71,0.25)" }} />
          </div>
        </div>

        <div className="space-y-2">
          <h2 className="text-2xl font-bold text-[#1a1d23]">Adduce</h2>
          <p className="text-sm max-w-md mx-auto leading-relaxed" style={{ color: "#8b929e" }}>
            Trace which service calls which — across repository boundaries, through
            gateways, with a file and line behind every edge.
          </p>
        </div>

        <div className="flex items-center gap-2 justify-center text-xs" style={{ color: "#8b929e" }}>
          <ArrowUp className="w-3 h-3" />
          <span>Start by entering a GitHub URL and clicking Ingest</span>
        </div>

        {/* Example repos.
         *
         * These are deliberately NOT famous monorepos. A single repo yields a
         * file graph with an empty Service Map and Trace, which is the worst
         * possible first impression for a cross-repo tool — the previous
         * suggestions (react, go, linux) sent every new user straight into it.
         * The petclinic pair is listed first because ingesting both is what
         * makes the product become itself: services unify across the two repos
         * and the gateway route table resolves real call edges between them. */}
        <div className="space-y-3 pt-4">
          <p className="text-xs uppercase tracking-wider" style={{ color: "#8b929e" }}>
            Try the demo corpus — ingest both petclinic repos first
          </p>
          <div className="flex flex-wrap gap-2 justify-center">
            {[
              {
                url: "https://github.com/spring-petclinic/spring-petclinic-microservices",
                label: "petclinic-microservices",
              },
              {
                url: "https://github.com/spring-petclinic/spring-petclinic-cloud",
                label: "petclinic-cloud",
              },
              {
                url: "https://github.com/confluentinc/kafka-streams-examples",
                label: "kafka-streams-examples",
              },
              {
                url: "https://github.com/grpc-ecosystem/grpc-gateway",
                label: "grpc-gateway",
              },
            ].map(({ url, label }) => (
              <button
                key={url}
                onClick={() => {
                  window.dispatchEvent(new CustomEvent("set-example-repo", { detail: url }));
                }}
                className="px-3 py-1.5 text-xs rounded-lg hover:bg-slate-200 transition-colors text-[#1a1d23]"
                style={{ background: "#f1f5f9", border: "1px solid #e2e8f0" }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
