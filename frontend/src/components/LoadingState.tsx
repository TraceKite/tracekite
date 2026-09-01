export default function LoadingState() {
  return (
    <div className="absolute inset-0 flex items-center justify-center" style={{ animation: "fadeIn 0.3s ease-out" }}>
      <div className="text-center space-y-4">
        <div className="relative mx-auto" style={{ width: "64px", height: "64px" }}>
          <div className="absolute inset-0 rounded-full border-2" style={{ borderColor: "rgba(49,91,71,0.2)", borderTopColor: "#315b47" }}>
            <style>{`
              @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
            `}</style>
            <div style={{ width: "100%", height: "100%", borderRadius: "50%", border: "inherit", borderTopColor: "inherit", animation: "spin 0.8s linear infinite" }} />
          </div>
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-2 h-2 rounded-full" style={{ background: "#315b47" }} />
          </div>
        </div>
        <div>
          <p className="text-sm font-medium text-[#1a1d23]">Loading graph...</p>
          <p className="text-xs mt-1" style={{ color: "#8b929e" }}>Fetching nodes and relationships from Neo4j</p>
        </div>
      </div>
    </div>
  );
}
