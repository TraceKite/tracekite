import type { ReactNode } from "react";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";

import { useCollapsibleSidebar } from "@/hooks/useCollapsibleSidebar";

interface Props {
  /** Names the region for screen readers and reads down the collapsed rail. */
  label: string;
  width?: string;
  zIndex?: string;
  children: ReactNode;
}

const SHELL =
  "flex-shrink-0 border-r border-[#c9c3b7] bg-[#f4f1e9] flex flex-col overflow-hidden shadow-sm";
const BUTTON =
  "text-[#5c6370] transition-colors hover:bg-[#eae6da] hover:text-[#1a1d23] " +
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#315b47]";

export default function SidebarPanel({
  label,
  width = "w-72",
  zIndex = "z-10",
  children,
}: Props) {
  const { collapsed, toggle, automatic } = useCollapsibleSidebar();

  if (collapsed) {
    return (
      <aside className={`w-11 ${zIndex} ${SHELL}`} aria-label={label}>
        <button
          type="button"
          onClick={toggle}
          aria-expanded={false}
          aria-label={`Expand ${label}`}
          title={automatic
            ? `Expand ${label} — collapsed to leave the canvas room`
            : `Expand ${label}`}
          className={`flex h-full w-full flex-col items-center gap-3 py-3 ${BUTTON}`}
        >
          <PanelLeftOpen className="h-4 w-4 flex-shrink-0" />
          <span className="text-2xs font-semibold uppercase tracking-widest [writing-mode:vertical-rl]">
            {label}
          </span>
        </button>
      </aside>
    );
  }

  return (
    <aside className={`${width} ${zIndex} ${SHELL}`} aria-label={label}>
      <div className="flex items-center justify-end border-b border-[#dcd6c8] px-2 py-1">
        <button
          type="button"
          onClick={toggle}
          aria-expanded
          aria-label={`Collapse ${label}`}
          title={`Collapse ${label}`}
          className={`rounded p-1 ${BUTTON}`}
        >
          <PanelLeftClose className="h-4 w-4" />
        </button>
      </div>
      {children}
    </aside>
  );
}
