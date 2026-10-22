import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/utils/format";
import { Button } from "./button";

export function PageHeader({ title, description, actions, eyebrow }: { title: string; description?: string; actions?: React.ReactNode; eyebrow?: string }) {
  return (
    <div className="mb-6 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow && <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">{eyebrow}</p>}
        <h1 className="text-2xl font-semibold sm:text-[28px]">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, sub, className, accent }: { label: string; value: React.ReactNode; sub?: React.ReactNode; className?: string; accent?: boolean }) {
  return (
    <div className={cn("rounded-xl border bg-card px-4 py-4", accent && "border-transparent bg-[hsl(var(--ink))] text-background", className)}>
      <p className={cn("text-[11px] font-semibold uppercase tracking-wider", accent ? "text-background/70" : "text-muted-foreground")}>{label}</p>
      <p className="mt-2 font-num text-2xl font-semibold">{value}</p>
      {sub && <p className={cn("mt-1 text-xs", accent ? "text-background/70" : "text-muted-foreground")}>{sub}</p>}
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="flex items-center justify-between border-t px-4 py-2.5 text-xs text-muted-foreground">
      <span className="tabular">{from}–{to} of {total}</span>
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="icon" className="h-7 w-7" disabled={page <= 1} onClick={() => onPage(page - 1)} aria-label="Previous page"><ChevronLeft /></Button>
        <span className="tabular">{page} / {pages}</span>
        <Button variant="ghost" size="icon" className="h-7 w-7" disabled={page >= pages} onClick={() => onPage(page + 1)} aria-label="Next page"><ChevronRight /></Button>
      </div>
    </div>
  );
}

export function KV({ k, v, className }: { k: React.ReactNode; v: React.ReactNode; className?: string }) {
  return (
    <div className={cn("flex items-baseline justify-between gap-3 py-1 text-sm", className)}>
      <span className="text-muted-foreground">{k}</span>
      <span className="text-right font-medium tabular">{v}</span>
    </div>
  );
}
