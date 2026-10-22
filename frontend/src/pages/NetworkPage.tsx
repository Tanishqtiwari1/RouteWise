import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { Map as LeafletMap } from "leaflet";
import { Ban, CheckCircle2, CircleDot, Crop, Download, Network, RefreshCw, Trash2, Upload } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { EmptyState, ErrorState, Notice, Skeleton } from "@/components/ui/feedback";
import { Field, Input } from "@/components/ui/input";
import { KV } from "@/components/ui/misc";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { StatusBadge } from "@/components/StatusBadge";
import { RouteMap, type MapRoute } from "@/components/map/RouteMap";
import { useAction, useClosures, useNetworks } from "@/hooks/queries";
import { api, errorMessage } from "@/services/api";
import type { RerouteEvent, RoadNetwork, Segment } from "@/types/api";
import { cn, dateTime, duration, fromLocalInput, km, money, num } from "@/utils/format";

type BBox = [number, number, number, number];

export default function NetworkPage() {
  const networks = useNetworks();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const nets = networks.data ?? [];
  const selected = nets.find((n) => n.id === selectedId) ?? nets.find((n) => n.is_active) ?? nets[0];
  const [view, setView] = useState<{ bbox: BBox; zoom: number } | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [segError, setSegError] = useState<string | null>(null);
  const [picked, setPicked] = useState<Segment | null>(null);
  const [reroutes, setReroutes] = useState<RerouteEvent[] | null>(null);
  const closures = useClosures(selected?.status === "ready" ? selected.id : undefined);
  const ready = selected?.status === "ready";

  // Load road segments for the visible area when zoomed in enough.
  useEffect(() => {
    if (!ready || !view || view.zoom < 15) { setSegments([]); return; }
    let cancelled = false;
    const [s, w, n, e] = view.bbox;
    api.get<{ segments: Segment[] }>(`/networks/${selected!.id}/segments`, { south: s, west: w, north: n, east: e, limit: 3000 })
      .then((r) => { if (!cancelled) { setSegments(r.segments); setSegError(null); } })
      .catch((err) => !cancelled && setSegError(errorMessage(err)));
    return () => { cancelled = true; };
  }, [ready, selected?.id, selected?.revision, view, closures.data]);

  const onMoveEnd = (m: LeafletMap) => {
    const b = m.getBounds();
    setView({ bbox: [b.getSouth(), b.getWest(), b.getNorth(), b.getEast()], zoom: m.getZoom() });
  };

  const onMapClick = async (lat: number, lon: number) => {
    if (!ready) return;
    try {
      const hits = await api.get<Segment[]>(`/networks/${selected!.id}/segments/nearest`, { lat, lon });
      setPicked(hits[0]);
    } catch (e) {
      setPicked(null);
      setSegError(errorMessage(e));
    }
  };

  const routes = useMemo<MapRoute[]>(() => {
    const r: MapRoute[] = segments.map((s) => ({
      id: `s-${s.id}`, geometry: s.geometry, weight: s.closed ? 5 : 3, opacity: 0.7,
      color: s.closed ? "#dc2626" : s.toll === "yes" ? "#f45b1d" : "#14161b", label: `${s.name ?? s.highway} · ${s.speed_kph} km/h`,
    }));
    (closures.data ?? []).filter((c) => c.active && c.geometry).forEach((c) => r.push({ id: `c-${c.id}`, geometry: c.geometry!, color: "#dc2626", weight: 6, label: `Closed: ${c.road_name ?? ""} ${c.reason ?? ""}` }));
    if (picked) r.push({ id: "picked", geometry: picked.geometry, color: "#f45b1d", weight: 8, opacity: 0.9, label: "Selected segment" });
    return r;
  }, [segments, closures.data, picked]);

  return (
    <div className="relative flex flex-col lg:block lg:h-[calc(100vh-4rem)]">
      <div className="order-2 w-full bg-card lg:absolute lg:bottom-4 lg:left-4 lg:top-4 lg:z-[450] lg:w-[420px] lg:overflow-y-auto lg:rounded-2xl lg:border lg:shadow-float">
        <div className="border-b p-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">OpenStreetMap</p><h1 className="text-xl font-semibold">Road network</h1>
          <p className="mt-1 text-xs text-muted-foreground">Drivable roads from OpenStreetMap, closures and per-segment cost overrides. Closures trigger recalculation of affected saved/dispatched plans.</p>
        </div>
        <Tabs defaultValue="networks" className="p-4">
          <TabsList><TabsTrigger value="networks"><Network /> Networks</TabsTrigger><TabsTrigger value="closures"><Ban /> Closures</TabsTrigger></TabsList>
          <TabsContent value="networks" className="mt-3 space-y-4">
            {networks.isLoading ? <Skeleton className="h-32" /> : networks.isError ? <ErrorState error={networks.error} onRetry={() => networks.refetch()} /> : nets.length === 0 ? (
              <EmptyState icon={Network} title="No road network imported" description="Pan the map to your delivery area and import its roads from OpenStreetMap." className="py-6" />
            ) : (
              <ul className="space-y-2">
                {nets.map((n) => <NetworkItem key={n.id} n={n} selected={selected?.id === n.id} onSelect={() => setSelectedId(n.id)} />)}
              </ul>
            )}
            <ImportForm view={view} />
          </TabsContent>
          <TabsContent value="closures" className="mt-3 space-y-3">
            {!ready ? <p className="text-xs text-muted-foreground">Select a ready network.</p> : (
              <>
                <Notice>Zoom in (level 15+) to see roads, then click a road to close it or set a toll/surcharge.{view && view.zoom < 15 && <b> Current zoom: {view.zoom}.</b>}</Notice>
                {segError && <Notice tone="warning">{segError}</Notice>}
                {picked && <SegmentPanel networkId={selected!.id} seg={picked} onDone={(ev) => { setPicked(null); if (ev) setReroutes(ev); }} />}
                {reroutes && <RerouteSummary events={reroutes} onClose={() => setReroutes(null)} />}
                <ClosureList networkId={selected!.id} />
              </>
            )}
          </TabsContent>
        </Tabs>
      </div>
      <div className="relative order-1 h-[45vh] lg:absolute lg:inset-0 lg:h-auto">
        <RouteMap className="h-full w-full" routes={routes} bbox={selected ? [selected.south, selected.west, selected.north, selected.east] : null}
          fitKey={`net-${selected?.id}`} onClick={onMapClick} onMoveEnd={onMoveEnd} defaultCenter={selected ? undefined : [28.6139, 77.209]} />
        <div className="pointer-events-none absolute bottom-6 right-3 z-[400] rounded-xl border bg-card/95 px-3 py-2 text-[11px] shadow-float">
          <p className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[#14161b] dark:bg-white" />Road</p>
          <p className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-[#f45b1d]" />Tagged toll road</p>
          <p className="flex items-center gap-1.5"><span className="h-0.5 w-4 bg-red-600" />Closed</p>
          <p className="flex items-center gap-1.5"><span className="h-0.5 w-4 border-t border-dashed border-[#f45b1d]" />Network boundary</p>
        </div>
      </div>
    </div>
  );
}

function NetworkItem({ n, selected, onSelect }: { n: RoadNetwork; selected: boolean; onSelect: () => void }) {
  const refresh = useAction(() => api.post(`/networks/${n.id}/refresh`), { invalidate: ["networks"], success: "Refresh started" });
  const activate = useAction(() => api.post(`/networks/${n.id}/activate`), { invalidate: ["networks", "health"], success: `${n.name} is now active` });
  const del = useAction(() => api.del(`/networks/${n.id}`), { invalidate: ["networks", "health"], success: "Network deleted" });
  const busy = ["pending", "downloading", "building"].includes(n.status);
  return (
    <li className={cn("rounded-md border p-3 text-sm", selected && "border-primary/50 bg-accent/40")}>
      <button type="button" className="flex w-full items-center gap-2 text-left" onClick={onSelect}>
        <span className="min-w-0 flex-1 truncate font-medium">{n.name}</span>
        {n.is_active && <Badge tone="info">active</Badge>}
        <StatusBadge status={n.status} />
      </button>
      <p className="mt-1 text-xs text-muted-foreground">
        {n.status === "ready" ? `${num(n.node_count)} nodes · ${num(n.edge_count)} edges · ${n.area_km2} km² · rev. ${n.revision}` : n.status_detail ?? ""}
      </p>
      {n.status === "ready" && <p className="text-[11px] text-muted-foreground">Imported {dateTime(n.imported_at)} · OSM data {dateTime(n.osm_timestamp)}{n.freshness?.stale && <span className="text-warning"> · stale</span>}</p>}
      {n.error && <Notice tone="danger" className="mt-2">{n.error}</Notice>}
      {busy && <div className="mt-2 h-1 overflow-hidden rounded bg-muted"><div className="h-full w-1/3 animate-pulse bg-primary" /></div>}
      {selected && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {n.status === "ready" && !n.is_active && <Button size="sm" variant="outline" onClick={() => activate.mutate(undefined)} loading={activate.isPending}><CheckCircle2 /> Activate</Button>}
          {!busy && n.source !== "openstreetmap-file-upload" && <Button size="sm" variant="outline" onClick={() => refresh.mutate(undefined)} loading={refresh.isPending}><RefreshCw /> {n.status === "failed" ? "Retry" : "Refresh"}</Button>}
          {!busy && <Button size="sm" variant="ghost" onClick={() => confirm(`Delete network ${n.name}? Plans keep their snapshots.`) && del.mutate(undefined)}><Trash2 /> Delete</Button>}
        </div>
      )}
    </li>
  );
}

function ImportForm({ view }: { view: { bbox: BBox; zoom: number } | null }) {
  const [name, setName] = useState("");
  const [bbox, setBbox] = useState<string[]>(["", "", "", ""]);
  const [uploadOpen, setUploadOpen] = useState(false);
  const create = useAction(() => api.post<RoadNetwork>("/networks", { name, south: Number(bbox[0]), west: Number(bbox[1]), north: Number(bbox[2]), east: Number(bbox[3]) }), {
    invalidate: ["networks"], success: "Import queued — downloading from Overpass API", onSuccess: () => setName(""),
  });
  const useView = () => view && setBbox(view.bbox.map((v) => v.toFixed(5)));
  const valid = name.trim() && bbox.every((v) => v !== "" && !Number.isNaN(Number(v))) && Number(bbox[0]) < Number(bbox[2]) && Number(bbox[1]) < Number(bbox[3]);
  return (
    <div className="space-y-3 rounded-md border p-3">
      <p className="text-sm font-medium">Import from OpenStreetMap</p>
      <Field label="Name" htmlFor="n-name"><Input id="n-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. South Delhi" /></Field>
      <div className="grid grid-cols-2 gap-2">
        {["South", "West", "North", "East"].map((l, i) => (
          <Field key={l} label={l} htmlFor={`bb-${i}`}><Input id={`bb-${i}`} inputMode="decimal" value={bbox[i]} onChange={(e) => setBbox(bbox.map((v, j) => (j === i ? e.target.value : v)))} /></Field>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={useView} disabled={!view}><Crop /> Use map view</Button>
        <Button size="sm" onClick={() => create.mutate(undefined)} disabled={!valid} loading={create.isPending}><Download /> Import roads</Button>
        <Button size="sm" variant="ghost" onClick={() => setUploadOpen(true)}><Upload /> Upload file</Button>
      </div>
      <p className="text-[11px] text-muted-foreground">Large areas take longer and may hit the server's area limit. Data © OpenStreetMap contributors, ODbL; downloaded via the configured Overpass endpoint.</p>
      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} />
    </div>
  );
}

function UploadDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const up = useAction(() => {
    const fd = new FormData();
    fd.append("name", name);
    fd.append("file", file!);
    return api.upload<RoadNetwork>("/networks/upload", fd);
  }, { invalidate: ["networks", "health"], success: "Network imported", onSuccess: () => onOpenChange(false) });
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Upload OSM road data" description="Alternative when the Overpass API is unavailable: upload an Overpass JSON export (out:json with way and node elements, e.g. from overpass-turbo)."
      footer={<Button disabled={!file || !name} onClick={() => up.mutate(undefined)} loading={up.isPending}>Upload & build</Button>}>
      <div className="space-y-3">
        <Field label="Name" htmlFor="u-n"><Input id="u-n" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Input type="file" accept=".json,application/json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label="OSM JSON file" className="py-1.5" />
      </div>
    </Dialog>
  );
}

function SegmentPanel({ networkId, seg, onDone }: { networkId: number; seg: Segment; onDone: (ev?: RerouteEvent[]) => void }) {
  const [reason, setReason] = useState("");
  const [endsAt, setEndsAt] = useState("");
  const [toll, setToll] = useState(seg.override?.toll_cost ?? "");
  const [extra, setExtra] = useState(seg.override?.extra_cost ?? "");
  const close = useAction(() => api.post<{ reroutes: RerouteEvent[]; affected_plan_ids: number[] }>(`/networks/${networkId}/closures`, {
    edge_ids: [seg.id], both_directions: true, reason: reason || null, ends_at: fromLocalInput(endsAt),
  }), { invalidate: ["closures", "networks", "routes"], success: (r) => `Road closed · ${r.affected_plan_ids.length} active plan(s) affected`, onSuccess: (r) => onDone(r.reroutes) });
  const override = useAction(() => api.put(`/networks/${networkId}/overrides/${encodeURIComponent(seg.id)}`, {
    toll_cost: toll === "" ? null : toll, extra_cost: extra === "" ? null : extra, both_directions: true,
  }), { invalidate: ["networks"], success: "Segment costs updated", onSuccess: () => onDone() });
  return (
    <div className="space-y-3 rounded-xl border-2 border-primary/40 p-3">
      <div className="flex items-start justify-between">
        <div><p className="text-sm font-medium">{seg.name ?? `Unnamed ${seg.highway}`}</p><p className="font-mono text-[10px] text-muted-foreground">{seg.id}{seg.twin && " (+ reverse)"}</p></div>
        <Button size="sm" variant="ghost" onClick={() => onDone()}>Cancel</Button>
      </div>
      <div className="grid grid-cols-2 gap-x-3 text-xs">
        <KV k="Class" v={seg.highway} /><KV k="Length" v={km(seg.length_m)} />
        <KV k="Speed" v={`${seg.speed_kph} km/h`} /><KV k="Toll tag" v={seg.toll ?? "—"} />
        {seg.maxweight_t != null && <KV k="Max weight" v={`${seg.maxweight_t} t`} />}
        {seg.maxheight_m != null && <KV k="Max height" v={`${seg.maxheight_m} m`} />}
      </div>
      <p className="text-[10px] text-muted-foreground">Speed source: {seg.speed_source}</p>
      <div className="space-y-2 border-t pt-3">
        <p className="text-xs font-medium">Close this road</p>
        <Input placeholder="Reason (e.g. construction)" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Closure reason" />
        <Field label="Reopens automatically at (optional)" htmlFor="c-end"><Input id="c-end" type="datetime-local" value={endsAt} onChange={(e) => setEndsAt(e.target.value)} /></Field>
        <Button size="sm" variant="destructive" onClick={() => close.mutate(undefined)} loading={close.isPending}><Ban /> Close & reroute affected plans</Button>
      </div>
      <div className="space-y-2 border-t pt-3">
        <p className="text-xs font-medium">Cost overrides (both directions)</p>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Toll amount" htmlFor="o-t"><Input id="o-t" inputMode="decimal" value={toll} onChange={(e) => setToll(e.target.value)} /></Field>
          <Field label="Surcharge" htmlFor="o-x"><Input id="o-x" inputMode="decimal" value={extra} onChange={(e) => setExtra(e.target.value)} /></Field>
        </div>
        <Button size="sm" variant="outline" onClick={() => override.mutate(undefined)} loading={override.isPending}>Save overrides</Button>
      </div>
    </div>
  );
}

function RerouteSummary({ events, onClose }: { events: RerouteEvent[]; onClose: () => void }) {
  return (
    <div className="space-y-2 rounded-md border p-3">
      <div className="flex justify-between"><p className="text-sm font-medium">Recalculation results</p><Button size="sm" variant="ghost" onClick={onClose}>Dismiss</Button></div>
      {events.length === 0 ? <p className="text-xs text-muted-foreground">No saved or dispatched plans used this road.</p> : events.map((e) => (
        <div key={e.id} className={cn("rounded px-2 py-1.5 text-xs", e.outcome === "rerouted" ? "bg-muted" : "bg-destructive/10")}>
          <p className="font-medium">Plan #{e.original_plan_id} → {e.outcome === "rerouted" ? <Link className="underline" to={`/history?plan=${e.new_plan_id}`}>#{e.new_plan_id}</Link> : "no alternative"}</p>
          {e.outcome === "rerouted" ? <p className="tabular">+{km(e.delta_distance_m ?? 0)} · {duration(e.delta_duration_s ?? 0)} · {money(e.delta_cost)}</p> : <p>{e.message}</p>}
        </div>
      ))}
    </div>
  );
}

function ClosureList({ networkId }: { networkId: number }) {
  const closures = useClosures(networkId);
  const reopen = useAction((id: number) => api.post(`/networks/${networkId}/closures/${id}/reopen`), { invalidate: ["closures", "networks"], success: "Road reopened" });
  const items = closures.data ?? [];
  return (
    <div>
      <p className="mb-2 text-sm font-medium">Closures</p>
      {closures.isLoading ? <Skeleton className="h-16" /> : items.length === 0 ? <p className="text-xs text-muted-foreground">No closures recorded.</p> : (
        <ul className="divide-y rounded-md border text-xs">
          {items.map((c) => (
            <li key={c.id} className="flex items-center gap-2 px-2.5 py-2">
              <CircleDot className={cn("h-3.5 w-3.5", c.active ? "text-destructive" : "text-muted-foreground")} />
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{c.road_name ?? "Unnamed road"}{c.reason && <span className="font-normal text-muted-foreground"> · {c.reason}</span>}</p>
                <p className="text-muted-foreground">{c.active ? `Closed ${dateTime(c.created_at)}${c.ends_at ? ` until ${dateTime(c.ends_at)}` : ""}` : `Reopened ${dateTime(c.reopened_at)}`}</p>
              </div>
              {c.active && <Button size="sm" variant="outline" onClick={() => reopen.mutate(c.id)}>Reopen</Button>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
