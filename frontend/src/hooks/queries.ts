import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { api, errorMessage } from "@/services/api";
import type {
  AnalyticsSummary, Closure, Customer, Order, Page, RoadNetwork, RoutePlan, Settings, Vehicle, Warehouse,
} from "@/types/api";

type Q = Record<string, string | number | boolean | null | undefined | (string | number)[]>;

export const useSettings = () => useQuery({ queryKey: ["settings"], queryFn: () => api.get<Settings>("/settings"), staleTime: 60_000 });
export const useHealth = () => useQuery({ queryKey: ["health"], queryFn: () => api.get<{ status: string; active_network: { id: number; name: string } | null }>("/health"), refetchInterval: 60_000 });

export const useWarehouses = (q: Q = {}) =>
  useQuery({ queryKey: ["warehouses", q], queryFn: () => api.get<Page<Warehouse>>("/warehouses", { page_size: 200, ...q }), placeholderData: keepPreviousData });
export const useVehicles = (q: Q = {}) =>
  useQuery({ queryKey: ["vehicles", q], queryFn: () => api.get<Page<Vehicle>>("/vehicles", { page_size: 200, ...q }), placeholderData: keepPreviousData });
export const useCustomers = (q: Q = {}) =>
  useQuery({ queryKey: ["customers", q], queryFn: () => api.get<Page<Customer>>("/customers", q), placeholderData: keepPreviousData });
export const useOrders = (q: Q = {}) =>
  useQuery({ queryKey: ["orders", q], queryFn: () => api.get<Page<Order>>("/orders", q), placeholderData: keepPreviousData });
export const useNetworks = () =>
  useQuery({
    queryKey: ["networks"],
    queryFn: () => api.get<RoadNetwork[]>("/networks"),
    refetchInterval: (q) => (q.state.data?.some((n) => ["pending", "downloading", "building"].includes(n.status)) ? 3000 : false),
  });
export const useClosures = (networkId: number | undefined) =>
  useQuery({ queryKey: ["closures", networkId], queryFn: () => api.get<Closure[]>(`/networks/${networkId}/closures`), enabled: !!networkId });
export const useRoutes = (q: Q = {}) =>
  useQuery({ queryKey: ["routes", q], queryFn: () => api.get<Page<RoutePlan>>("/routes", q), placeholderData: keepPreviousData });
export const useRoute = (id: number | null) =>
  useQuery({ queryKey: ["route", id], queryFn: () => api.get<RoutePlan>(`/routes/${id}`), enabled: id !== null });
export const useAnalytics = (q: Q = {}) =>
  useQuery({ queryKey: ["analytics", q], queryFn: () => api.get<AnalyticsSummary>("/analytics/summary", q), placeholderData: keepPreviousData });

/** Mutation with toast feedback and cache invalidation. */
export function useAction<TVars, TResult = unknown>(
  fn: (v: TVars) => Promise<TResult>,
  opts: { invalidate?: string[]; success?: string | ((r: TResult) => string); onSuccess?: (r: TResult) => void; silentError?: boolean } = {},
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (r) => {
      opts.invalidate?.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
      if (opts.success) toast.success(typeof opts.success === "function" ? opts.success(r) : opts.success);
      opts.onSuccess?.(r);
    },
    onError: (e) => {
      if (!opts.silentError) toast.error(errorMessage(e));
    },
  });
}
