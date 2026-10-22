import { lazy, Suspense } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AppLayout } from "@/layouts/AppLayout";
import { EmptyState, Skeleton } from "@/components/ui/feedback";
import { Button } from "@/components/ui/button";

const DashboardPage = lazy(() => import("@/pages/DashboardPage"));
const PlannerPage = lazy(() => import("@/pages/PlannerPage"));
const DeliveriesPage = lazy(() => import("@/pages/DeliveriesPage"));
const FleetPage = lazy(() => import("@/pages/FleetPage"));
const NetworkPage = lazy(() => import("@/pages/NetworkPage"));
const HistoryPage = lazy(() => import("@/pages/HistoryPage"));
const AnalyticsPage = lazy(() => import("@/pages/AnalyticsPage"));
const SettingsPage = lazy(() => import("@/pages/SettingsPage"));

const page = (el: React.ReactNode) => <Suspense fallback={<div className="p-6"><Skeleton className="h-64" /></div>}>{el}</Suspense>;

function NotFound() {
  return <EmptyState title="Page not found" action={<Button asChild variant="outline"><a href="/">Back to dashboard</a></Button>} />;
}

const router = createBrowserRouter([
  {
    element: <AppLayout />,
    errorElement: <NotFound />,
    children: [
      { path: "/", element: page(<DashboardPage />) },
      { path: "/planner", element: page(<PlannerPage />) },
      { path: "/deliveries", element: page(<DeliveriesPage />) },
      { path: "/fleet", element: page(<FleetPage />) },
      { path: "/network", element: page(<NetworkPage />) },
      { path: "/history", element: page(<HistoryPage />) },
      { path: "/analytics", element: page(<AnalyticsPage />) },
      { path: "/settings", element: page(<SettingsPage />) },
      { path: "*", element: <NotFound /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}
