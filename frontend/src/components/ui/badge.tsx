import { cn } from "@/utils/format";

const tones = {
  default: "bg-muted text-foreground",
  muted: "bg-muted text-muted-foreground",
  success: "bg-success/10 text-success",
  warning: "bg-warning/10 text-warning",
  danger: "bg-destructive/10 text-destructive",
  info: "bg-accent text-accent-foreground",
} as const;

export type Tone = keyof typeof tones;

export function Badge({ tone = "default", className, children }: { tone?: Tone; className?: string; children: React.ReactNode }) {
  return <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize", tones[tone], className)}>{children}</span>;
}
