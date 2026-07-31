import { useEffect, useState } from "react";
import { X, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { useGraphStore } from "@/store/graphStore";
import { api } from "@/lib/api";

export default function IngestionStatus() {
  const { ingestionJob, setIngestionJob, selectedRepo, setSelectedRepo, setRepos } = useGraphStore();
  const [visible, setVisible] = useState(true);
  const [dots, setDots] = useState("");

  useEffect(() => {
    if (!ingestionJob) return undefined;
    if (ingestionJob.status === "running" || ingestionJob.status === "queued") {
      const interval = setInterval(() => {
        setDots((prev) => (prev.length >= 3 ? "" : prev + "."));
      }, 500);
      return () => clearInterval(interval);
    }
    return undefined;
  }, [ingestionJob?.status]);

  useEffect(() => {
    if (!ingestionJob) return;
    if (ingestionJob.status === "completed" || ingestionJob.status === "failed") return;

    const interval = setInterval(async () => {
      try {
        const status = await api.getJobStatus(ingestionJob.job_id);
        setIngestionJob(status);

        if (status.status === "completed") {
          const list = await api.listRepos();
          setRepos(list.repos);
          const newRepo = list.repos.find((r) => r.id === status.repo_id);
          if (newRepo && !selectedRepo) {
            setSelectedRepo(newRepo);
          }
          setTimeout(() => setVisible(false), 4000);
        }
        // A failure does NOT auto-dismiss. It is the one state carrying
        // information the user cannot recover anywhere else (the clone error,
        // for instance), and a six-second window is easy to miss entirely.
        // It stays until dismissed.
      } catch (err) {
        console.error("Job poll failed:", err);
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [ingestionJob?.job_id, ingestionJob?.status]);

  if (!ingestionJob || !visible) return null;

  const isRunning = ingestionJob.status === "running" || ingestionJob.status === "queued";
  const isCompleted = ingestionJob.status === "completed";
  const isFailed = ingestionJob.status === "failed";

  const borderColor = isCompleted ? "border-green-500/30" : isFailed ? "border-red-500/30" : "border-blue-500/30";

  return (
    <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-30 w-96" style={{ animation: "fadeIn 0.3s ease-out" }}>
      <div className={`rounded-xl p-4 border ${borderColor}`}
        style={{ background: "rgba(17,24,39,0.9)", backdropFilter: "blur(12px)" }}
      >
        <div className="flex items-start gap-3">
          <div className="mt-0.5">
            {isRunning && <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />}
            {isCompleted && <CheckCircle2 className="w-4 h-4 text-green-400" />}
            {isFailed && <AlertCircle className="w-4 h-4 text-red-400" />}
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium text-[#e9ecef]">
                {isRunning && "Ingesting repository"}
                {isCompleted && "Ingestion complete"}
                {isFailed && "Ingestion failed"}
              </h4>
              <button onClick={() => setVisible(false)} className="text-[#8c949e] hover:text-[#e9ecef] transition-colors">
                <X className="w-3.5 h-3.5" />
              </button>
            </div>

            <p className="text-xs text-[#8c949e] mt-1 truncate">
              {ingestionJob.message}{dots}
            </p>

            {isFailed && ingestionJob.error && (
              <p className="text-xs text-red-400 mt-1">{ingestionJob.error}</p>
            )}

            <div className="mt-2">
              <div className="w-full h-1.5 rounded-full overflow-hidden" style={{ background: "#2b313a" }}>
                <div
                  className="h-full rounded-full transition-all duration-500"
                  style={{
                    width: `${ingestionJob.progress}%`,
                    background: isCompleted ? "#22c55e" : isFailed ? "#ef4444" : "#3b82f6",
                  }}
                />
              </div>
              <p className="text-xs text-[#8c949e] mt-1">{ingestionJob.progress}%</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
