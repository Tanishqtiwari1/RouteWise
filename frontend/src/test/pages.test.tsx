import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import DashboardPage from "@/pages/DashboardPage";
import FleetPage from "@/pages/FleetPage";
import { money, km, duration } from "@/utils/format";
import { ApiError, errorMessage } from "@/services/api";

function renderWithClient(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><MemoryRouter>{ui}</MemoryRouter></QueryClientProvider>);
}

function mockFetch(handler: (url: string) => { status: number; body: unknown } | "network-error") {
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const r = handler(String(input));
    if (r === "network-error") throw new TypeError("Failed to fetch");
    return new Response(JSON.stringify(r.body), { status: r.status, headers: { "Content-Type": "application/json" } });
  }));
}

const emptySummary = {
  currency: "INR", definitions: {}, trend: [], components: [], distance_vs_cost: [], top_locations: [], vehicles: [], recent: [],
  orders_by_status: {}, completion: { recorded: 0, deliveries_completed: 0, deliveries_failed: 0, success_rate: null },
  totals: { committed_plans: 0, calculations: 0, planned_deliveries: 0, estimated_cost: "0.00", avg_estimated_cost_per_delivery: null,
    estimated_savings: "0.00", baseline_cost: "0.00", savings_pct: null, actual_recorded_cost: "0.00", plans_with_actuals: 0,
    estimated_cost_of_plans_with_actuals: "0.00", distance_km: 0, emissions_kg: null },
};

afterEach(() => vi.unstubAllGlobals());

describe("Dashboard", () => {
  it("shows a loading skeleton, then an empty state when there are no committed plans", async () => {
    mockFetch(() => ({ status: 200, body: emptySummary }));
    const { container } = renderWithClient(<DashboardPage />);
    expect(container.querySelector(".animate-pulse")).toBeInTheDocument();
    expect(await screen.findByText("No committed route plans yet")).toBeInTheDocument();
  });

  it("shows an error state with retry when the API is unreachable", async () => {
    mockFetch(() => "network-error");
    renderWithClient(<DashboardPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Cannot reach the RouteWise API/);
    expect(screen.getByRole("button", { name: /retry/i })).toBeInTheDocument();
  });

  it("renders metrics from the API", async () => {
    mockFetch(() => ({ status: 200, body: { ...emptySummary, totals: { ...emptySummary.totals, committed_plans: 2, planned_deliveries: 5, estimated_cost: "1234.50" } } }));
    renderWithClient(<DashboardPage />);
    await waitFor(() => expect(screen.getByText("5")).toBeInTheDocument());
    expect(screen.getByText(money("1234.50", "INR", 0))).toBeInTheDocument();
  });
});

describe("Fleet", () => {
  it("shows an empty state when there are no vehicles", async () => {
    mockFetch((url) => (url.includes("/vehicles") ? { status: 200, body: { items: [], total: 0, page: 1, page_size: 200 } } : { status: 200, body: {} }));
    renderWithClient(<FleetPage />);
    expect(await screen.findByText("No vehicles yet")).toBeInTheDocument();
  });

  it("surfaces structured API errors", async () => {
    mockFetch((url) => (url.includes("/vehicles") ? { status: 500, body: { error: { code: "boom", message: "Database unavailable" } } } : { status: 200, body: {} }));
    renderWithClient(<FleetPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Database unavailable");
  });
});

describe("formatting", () => {
  it("formats distances, durations and currency", () => {
    expect(km(850)).toBe("850 m");
    expect(km(12345)).toBe("12.35 km");
    expect(duration(45)).toBe("45 s");
    expect(duration(3720)).toBe("1 h 2 min");
    expect(money(null)).toBe("—");
    expect(money("100", "INR")).toContain("100.00");
  });

  it("explains validation errors", () => {
    const e = new ApiError(422, "validation_error", "Request validation failed", [{ loc: ["body", "weight_kg"], msg: "must be > 0" }]);
    expect(errorMessage(e)).toBe("weight_kg: must be > 0");
  });
});
