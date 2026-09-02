import { AlertTriangle, SearchX } from "lucide-react";

export default function GraphCanvasMessage({ title, detail, warning = false }: {
  title: string;
  detail?: string;
  warning?: boolean;
}) {
  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center bg-[#fbfaf6] p-6">
      <div className="max-w-md space-y-3 text-center text-[#252821]">
        {warning
          ? <AlertTriangle className="mx-auto h-7 w-7 text-[#9b7a31]" />
          : <SearchX className="mx-auto h-7 w-7 text-[#8a8e84]" />}
        <h3 className="text-base font-semibold">{title}</h3>
        {detail && <p className="text-sm leading-relaxed text-[#6e7168]">{detail}</p>}
      </div>
    </div>
  );
}
