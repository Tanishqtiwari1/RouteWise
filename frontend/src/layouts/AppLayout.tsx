import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import {
  BarChart3, History, KeyRound, LayoutGrid, Map, MoreHorizontal, Moon, Network, Package, Settings, Sun, Truck,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, Sheet } from "@/components/ui/dialog";
import { Field, Input } from "@/components/ui/input";
import { useHealth, useSettings } from "@/hooks/queries";
import { useTheme } from "@/hooks/useTheme";
import { getAdminToken, setAdminToken } from "@/services/api";
import { DEMO_MODE, REPO_URL } from "@/services/demo";
import { cn } from "@/utils/format";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutGrid },
  { to: "/planner", label: "Plan", icon: Map },
  { to: "/deliveries", label: "Deliveries", icon: Package },
  { to: "/fleet", label: "Fleet", icon: Truck },
  { to: "/network", label: "Roads", icon: Network },
  { to: "/history", label: "History", icon: History },
  { to: "/analytics", label: "Insights", icon: BarChart3 },
  { to: "/settings", label: "Settings", icon: Settings },
];
const MOBILE_PRIMARY = NAV.slice(0, 4);

function Wordmark() {
  return (
    <NavLink to="/" className="flex shrink-0 items-center gap-2.5" aria-label="RouteWise home">
      <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" className="h-8 w-8" />
      <span className="font-display text-lg font-semibold tracking-tight">Route<span className="text-primary">Wise</span></span>
    </NavLink>
  );
}

export function AppLayout() {
  const [moreOpen, setMoreOpen] = useState(false);
  const [tokenOpen, setTokenOpen] = useState(false);
  const [token, setToken] = useState(getAdminToken() ?? "");
  const { theme, toggle } = useTheme();
  const settings = useSettings();
  const health = useHealth();
  const location = useLocation();
  const fullBleed = location.pathname.startsWith("/planner") || location.pathname.startsWith("/network");
  const net = health.data?.active_network;

  const status = health.isError ? { tone: "bg-destructive", text: "API offline" }
    : net ? { tone: "bg-success", text: net.name }
    : health.isLoading ? { tone: "bg-muted-foreground", text: "Connecting…" }
    : { tone: "bg-warning", text: "No road network" };

  return (
    <div className="flex min-h-screen flex-col">
      {DEMO_MODE && (
        <div role="note" className="z-[510] bg-primary px-4 py-2 text-center text-xs font-semibold text-primary-foreground">
          Read-only demo · a snapshot of sample Delhi data produced by the real RouteWise engine. Calculating routes and editing need the full app —{" "}
          <a href={REPO_URL} className="underline underline-offset-2" target="_blank" rel="noreferrer">run it from GitHub</a>.
        </div>
      )}
      <header className="sticky top-0 z-[500] border-b bg-background/90 backdrop-blur-md">
        <div className="flex h-16 items-center gap-6 px-4 sm:px-6">
          <Wordmark />
          <nav className="hidden items-center gap-1 lg:flex" aria-label="Main">
            {NAV.map(({ to, label }) => (
              <NavLink key={to} to={to} end={to === "/"}
                className={({ isActive }) => cn(
                  "rounded-full px-3.5 py-1.5 text-[13px] font-semibold text-muted-foreground transition-colors hover:text-foreground",
                  isActive && "bg-[hsl(var(--ink))] text-background hover:text-background",
                )}>
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1.5">
            <span className="hidden items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium md:inline-flex" title={settings.data?.workspace_name}>
              <span className={cn("h-2 w-2 rounded-full", status.tone)} aria-hidden />
              <span className="max-w-[180px] truncate">{status.text}</span>
            </span>
            <Button variant="ghost" size="icon" onClick={() => setTokenOpen(true)} aria-label="Administrator token" title="Administrator token">
              <KeyRound className={getAdminToken() ? "text-primary" : undefined} />
            </Button>
            <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">{theme === "dark" ? <Sun /> : <Moon />}</Button>
          </div>
        </div>
      </header>

      <main className={cn("flex-1 pb-20 lg:pb-0", fullBleed ? "" : "mx-auto w-full max-w-7xl px-4 py-8 sm:px-6")}>
        <Outlet />
      </main>

      {!fullBleed && (
        <footer className="hidden border-t px-6 py-4 text-xs text-muted-foreground lg:block">
          Map data © OpenStreetMap contributors (ODbL). Costs are model estimates unless marked actual.
        </footer>
      )}

      {/* Mobile bottom tab bar */}
      <nav className="fixed inset-x-0 bottom-0 z-[600] grid grid-cols-5 border-t bg-background/95 backdrop-blur-md lg:hidden" aria-label="Main">
        {MOBILE_PRIMARY.map(({ to, label, icon: Icon }) => (
          <NavLink key={to} to={to} end={to === "/"}
            className={({ isActive }) => cn("flex flex-col items-center gap-0.5 py-2 text-[10px] font-semibold text-muted-foreground", isActive && "text-primary")}>
            <Icon className="h-5 w-5" />{label}
          </NavLink>
        ))}
        <button type="button" onClick={() => setMoreOpen(true)} className="flex flex-col items-center gap-0.5 py-2 text-[10px] font-semibold text-muted-foreground">
          <MoreHorizontal className="h-5 w-5" />More
        </button>
      </nav>
      <Sheet open={moreOpen} onOpenChange={setMoreOpen} side="right" title="More">
        <div className="p-4"><Wordmark /></div>
        <nav className="flex flex-col gap-1 px-3" aria-label="More">
          {NAV.slice(4).map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} onClick={() => setMoreOpen(false)}
              className={({ isActive }) => cn("flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-semibold", isActive ? "bg-accent text-accent-foreground" : "hover:bg-muted")}>
              <Icon className="h-4 w-4" />{label}
            </NavLink>
          ))}
        </nav>
        <p className="px-6 pt-6 text-xs text-muted-foreground">Status: {status.text}</p>
      </Sheet>

      <Dialog open={tokenOpen} onOpenChange={setTokenOpen} title="Administrator token"
        description="Required for road closures, network imports and settings when the server sets ROUTEWISE_ADMIN_TOKEN. Stored only in this browser."
        footer={<>
          <Button variant="outline" onClick={() => { setAdminToken(null); setToken(""); setTokenOpen(false); }}>Clear</Button>
          <Button onClick={() => { setAdminToken(token || null); setTokenOpen(false); }}>Save</Button>
        </>}>
        <Field label="Token" htmlFor="admin-token">
          <Input id="admin-token" type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
        </Field>
      </Dialog>
    </div>
  );
}
