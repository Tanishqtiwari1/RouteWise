import * as T from "@radix-ui/react-tabs";
import { cn } from "@/utils/format";

export const Tabs = T.Root;
export const TabsContent = T.Content;

export function TabsList({ className, ...p }: T.TabsListProps) {
  return <T.List className={cn("inline-flex h-10 items-center gap-5 border-b", className)} {...p} />;
}
export function TabsTrigger({ className, ...p }: T.TabsTriggerProps) {
  return (
    <T.Trigger
      className={cn("-mb-px inline-flex h-10 items-center gap-1.5 border-b-2 border-transparent text-[13px] font-semibold text-muted-foreground transition-colors hover:text-foreground data-[state=active]:border-primary data-[state=active]:text-foreground [&_svg]:size-3.5", className)}
      {...p}
    />
  );
}
