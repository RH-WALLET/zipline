import { statusClass } from "@/lib/format";

const TONE: Record<string, string> = { green: "success", red: "danger", amber: "warning", blue: "info", "": "" };

/** Small monospaced tags for states: ACTIVE, WATCH, DISABLED, CONFIRMED, DRY RUN … */
export function Chip({ children, tone }: { children: string; tone?: string }) {
  const t = tone ?? statusClass(children);
  return <span className={`tag ${TONE[t] ?? ""}`}>{children}</span>;
}
