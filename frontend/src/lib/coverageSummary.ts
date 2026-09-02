export interface CoverageCounter {
  label: string;
  value: number;
}

const PRIMARY_KEYS = new Set(["files_seen", "files_parsed", "claims"]);

export function summarizeCoverage(totals: Record<string, number>) {
  const filesSeen = Math.max(0, Number(totals.files_seen ?? 0));
  const filesParsed = Math.max(0, Number(totals.files_parsed ?? 0));
  const percentage = filesSeen > 0
    ? Math.min(100, Math.round((filesParsed / filesSeen) * 100))
    : null;
  const counters: CoverageCounter[] = Object.entries(totals)
    .filter(([key, value]) => !PRIMARY_KEYS.has(key) && Number(value) > 0)
    .map(([key, value]) => ({
      label: key.replaceAll("_", " "),
      value: Number(value),
    }))
    .sort((left, right) => right.value - left.value || left.label.localeCompare(right.label));
  return { filesSeen, filesParsed, percentage, counters };
}
