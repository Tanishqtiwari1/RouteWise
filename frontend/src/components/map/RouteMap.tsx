import { useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Polyline, Rectangle, TileLayer, Tooltip, useMap, useMapEvents, ZoomControl } from "react-leaflet";
import type { LatLngBoundsExpression, LatLngExpression, Map as LeafletMap } from "leaflet";
import "leaflet/dist/leaflet.css";
import { useSettings } from "@/hooks/queries";

export interface MapRoute {
  id: string;
  geometry: [number, number][];
  color: string;
  weight?: number;
  dashed?: boolean;
  opacity?: number;
  label?: string;
  onClick?: () => void;
}

export interface MapMarker {
  id: string;
  lat: number;
  lon: number;
  label: string;
  kind: "warehouse" | "delivery" | "destination" | "point" | "selection";
  index?: number;
}

const MARKER_STYLE: Record<MapMarker["kind"], { color: string; fill: string; r: number }> = {
  warehouse: { color: "#ffffff", fill: "#14161b", r: 10 },
  delivery: { color: "#ffffff", fill: "#f45b1d", r: 8 },
  destination: { color: "#ffffff", fill: "#dc2626", r: 9 },
  point: { color: "#ffffff", fill: "#6b7280", r: 6 },
  selection: { color: "#ffffff", fill: "#f45b1d", r: 7 },
};

function FitBounds({ bounds, version }: { bounds: LatLngBoundsExpression | null; version: string }) {
  const map = useMap();
  useEffect(() => {
    if (bounds) map.fitBounds(bounds, { padding: [32, 32], maxZoom: 17 });
  }, [version]);
  return null;
}

function ClickHandler({ onClick, onMoveEnd }: { onClick?: (lat: number, lon: number) => void; onMoveEnd?: (m: LeafletMap) => void }) {
  const map = useMapEvents({
    click: (e) => onClick?.(e.latlng.lat, e.latlng.lng),
    moveend: () => onMoveEnd?.(map),
  });
  useEffect(() => {
    onMoveEnd?.(map);
  }, []);
  return null;
}

function InvalidateOnResize() {
  const map = useMap();
  useEffect(() => {
    const fix = () => map.invalidateSize();
    const obs = new ResizeObserver(fix);
    obs.observe(map.getContainer());
    window.addEventListener("resize", fix);
    const t = window.setTimeout(fix, 250); // after layout settles (fonts, panels)
    return () => { obs.disconnect(); window.removeEventListener("resize", fix); window.clearTimeout(t); };
  }, [map]);
  return null;
}

export function RouteMap({
  routes = [], markers = [], trace = [], bbox, fallbackBounds, fitKey, onClick, onMoveEnd, className, defaultCenter,
}: {
  routes?: MapRoute[];
  markers?: MapMarker[];
  trace?: { lat: number; lon: number; k: string }[];
  bbox?: [number, number, number, number] | null; // south, west, north, east (drawn)
  fallbackBounds?: [number, number, number, number] | null; // fit-only area when nothing else is shown
  fitKey?: string;
  onClick?: (lat: number, lon: number) => void;
  onMoveEnd?: (m: LeafletMap) => void;
  className?: string;
  defaultCenter?: [number, number];
}) {
  const settings = useSettings();
  const bounds = useMemo<LatLngBoundsExpression | null>(() => {
    const pts: [number, number][] = [];
    routes.forEach((r) => pts.push(...r.geometry));
    markers.forEach((m) => pts.push([m.lat, m.lon]));
    const area = bbox ?? fallbackBounds;
    if (!pts.length && area) return [[area[0], area[1]], [area[2], area[3]]];
    if (!pts.length) return null;
    const lats = pts.map((p) => p[0]);
    const lons = pts.map((p) => p[1]);
    return [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]];
  }, [routes, markers, bbox, fallbackBounds]);
  const center: LatLngExpression = defaultCenter ?? (bbox ? [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2] : [20.5937, 78.9629]);

  return (
    <div className={className}>
      <MapContainer center={center} zoom={bbox || defaultCenter ? 13 : 5} className="h-full w-full" scrollWheelZoom preferCanvas zoomControl={false}>
        <ZoomControl position="topright" />
        <TileLayer
          url={settings.data?.tile_url ?? "https://tile.openstreetmap.org/{z}/{x}/{y}.png"}
          attribution={settings.data?.tile_attribution ?? "&copy; OpenStreetMap contributors"}
          maxZoom={19}
        />
        <InvalidateOnResize />
        <FitBounds bounds={bounds} version={fitKey ?? ""} />
        <ClickHandler onClick={onClick} onMoveEnd={onMoveEnd} />
        {bbox && (
          <Rectangle bounds={[[bbox[0], bbox[1]], [bbox[2], bbox[3]]]} pathOptions={{ color: "#f45b1d", weight: 1.5, fillOpacity: 0.03, dashArray: "6 4" }} />
        )}
        {trace.map((t, i) => (
          <CircleMarker
            key={`t${i}`}
            center={[t.lat, t.lon]}
            radius={t.k === "goal" ? 6 : 2.5}
            pathOptions={{ stroke: false, fillColor: t.k === "stale" ? "#9ca3af" : t.k === "goal" ? "#dc2626" : "#14161b", fillOpacity: t.k === "goal" ? 1 : 0.5 }}
          />
        ))}
        {routes.map((r) => (
          <Polyline
            key={r.id}
            positions={r.geometry}
            pathOptions={{ color: r.color, weight: r.weight ?? 5, opacity: r.opacity ?? 0.9, dashArray: r.dashed ? "6 6" : undefined, lineCap: "round" }}
            eventHandlers={r.onClick ? { click: (e) => { e.originalEvent.stopPropagation(); r.onClick?.(); } } : undefined}
          >
            {r.label && <Tooltip sticky>{r.label}</Tooltip>}
          </Polyline>
        ))}
        {markers.map((m) => {
          const s = MARKER_STYLE[m.kind];
          return (
            <CircleMarker key={m.id} center={[m.lat, m.lon]} radius={s.r} pathOptions={{ color: s.color, weight: 2.5, fillColor: s.fill, fillOpacity: 1 }}>
              <Tooltip direction="top" offset={[0, -6]} permanent={m.index !== undefined}>
                {m.index !== undefined ? <span className="font-semibold">{m.index}</span> : m.label}
              </Tooltip>
            </CircleMarker>
          );
        })}
      </MapContainer>
    </div>
  );
}
