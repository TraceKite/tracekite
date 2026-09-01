import { useGraphStore } from "@/store/graphStore";
import WorkspaceWarning from "@/components/WorkspaceWarning";

export default function GraphDataWarning() {
  const { error, nodes, setError } = useGraphStore();
  if (!error || nodes.length === 0) return null;
  return <WorkspaceWarning message={error} onDismiss={() => setError(null)} />;
}
