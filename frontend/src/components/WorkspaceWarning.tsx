import { AlertTriangle, X } from "lucide-react";

export default function WorkspaceWarning({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div role="status" className="absolute right-4 top-4 z-30 flex max-w-md items-start gap-2
                                  rounded-md border border-[#9b7a31]/35 bg-[#fff9e9]
                                  px-3 py-2 text-xs text-[#5b461c] shadow-sm">
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <span className="leading-relaxed">{message}</span>
      <button onClick={onDismiss} aria-label="Dismiss warning"
              className="rounded p-0.5 hover:bg-[#9b7a31]/10">
        <X className="h-3 w-3" />
      </button>
    </div>
  );
}
