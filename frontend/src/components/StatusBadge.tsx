import { Badge } from "@/components/ui/badge";
import { STATUS_TONE } from "@/utils/format";

export function StatusBadge({ status }: { status: string | null | undefined }) {
  if (!status) return <Badge tone="muted">—</Badge>;
  return <Badge tone={STATUS_TONE[status] ?? "default"}>{status.replace(/_/g, " ")}</Badge>;
}
