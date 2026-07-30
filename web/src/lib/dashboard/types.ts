import type { components } from "@/lib/api/generated/schema";

export type DashboardCode = components["schemas"]["DashboardCode"];
export type DashboardDefinition = components["schemas"]["DashboardDefinition"];
export type DashboardSummary = components["schemas"]["DashboardSummary"];
export type DashboardMetricDefinition =
  components["schemas"]["DashboardMetricDefinition"];
export type DashboardMetricSummary = components["schemas"]["DashboardMetricSummary"];
export type DashboardComparison = components["schemas"]["DashboardComparison"];
export type DashboardFreshness = components["schemas"]["DashboardFreshness"];
export type ObservationRead = components["schemas"]["ObservationRead"];
export type DerivedObservationRead =
  components["schemas"]["DerivedObservationRead"];
export type DerivedObservationPage =
  components["schemas"]["DerivedObservationPage"];
export type AnalyticsRunObservationPage =
  components["schemas"]["DerivedObservationPage"];

export type ChartPoint = {
  observedAt: string;
  exactValue: string | null;
  status: "present" | "missing";
};

export type FeaturedChartData =
  | {
      status: "available";
      metricKey: string;
      title: string;
      sourceLabel: string | null;
      start: string;
      end: string;
      points: ChartPoint[];
    }
  | {
      status: "empty" | "error";
      reason: string;
    };

export type DashboardPageData = {
  definition: DashboardDefinition;
  summary: DashboardSummary;
  featuredChart: FeaturedChartData;
};

export type DashboardPageResult =
  | { status: "ready"; data: DashboardPageData }
  | {
      status: "error";
      code: "invalid_dashboard" | "not_found" | "unavailable" | "invalid_contract";
    };
