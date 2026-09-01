import { useEffect, type RefObject } from "react";
interface ShortcutsProps {
  toggleShowLabels: () => void;
  onBack: () => void;
  containerRef: RefObject<HTMLElement | null>;
}

export function useGraph3DShortcuts({
  toggleShowLabels,
  onBack,
  containerRef,
}: ShortcutsProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (["INPUT", "TEXTAREA"].includes((e.target as HTMLElement)?.tagName)) return;
      if (!containerRef.current?.contains(document.activeElement)) return;
      if (e.key.toLowerCase() === "l") {
        toggleShowLabels();
      } else if (e.key === "Escape") {
        onBack();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleShowLabels, onBack, containerRef]);
}
