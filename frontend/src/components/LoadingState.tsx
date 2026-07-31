export default function LoadingState() {
  return (
    <div className="absolute inset-0 flex items-center justify-center" style={{ animation: "fadeIn 0.3s ease-out" }}>
      <div className="text-center space-y-4">
        <div className="relative mx-auto" style={{ width: "64px", height: "64px" }}>
          <div className="absolute inset-0 rounded-full border-2" style={{ borderColor: "rgba(59,130,246,0.2)", borderTopColor: "#3b82f6" }}>
            <style>{`
              @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
            `}</style>
            <div style={{ width: "100%", height: "100%", borderRadius: "50%", border: "inherit", borderTopColor: "inherit", animation: "spin 0.8s linear infinite" }} />
          </div>
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-2 h-2 rounded-full" style={{ background: "#60a5fa" }} />
          </div>
        </div>
        <div>
          <p className="text-sm font-medium text-[#e9ecef]">Loading graph...</p>
          <p className="text-xs mt-1" style={{ color: "#8c949e" }}>Fetching nodes and relationships from Neo4j</p>
        </div>
      </div>
    </div>
  );
}
