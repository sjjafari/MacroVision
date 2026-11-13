import type { components } from "@/lib/api/generated/schema";

export type IndicatorCatalogItem = components["schemas"]["IndicatorCatalogItem"];
export type IndicatorCatalogPage = components["schemas"]["IndicatorCatalogPage"];
export type IndicatorDetail = components["schemas"]["IndicatorDetail"];
export type IndicatorSnapshot = components["schemas"]["IndicatorSnapshot"];
export type RelatedDerivedRead = components["schemas"]["RelatedDerivedRead"];
export type ObservationRead = components["schemas"]["ObservationRead"];
export type DataRevisionRead = components["schemas"]["DataRevisionRead"];
export type LineagePage = components["schemas"]["DerivedObservationLineagePage"];

export type IndicatorQuery = {
  search?: string;
  category?: components["schemas"]["SeriesCategory"];
  frequency?: components["schemas"]["DataFrequency"];
  geography?: string;
  source_id?: number;
  operational_is_active?: boolean;
  limit: number;
  offset: number;
};

export type IndicatorChart = { status: "ready"; points: ObservationRead[] } | { status: "empty" | "error"; points: [] };

export type RelatedSection =
  | { status: "current_available"; related: RelatedDerivedRead; lineages: Record<string, LineagePage> }
  | { status: "historical_not_supported" }
  | { status: "unavailable" };

export type IndicatorDetailData = {
  detail: IndicatorDetail;
  snapshot: IndicatorSnapshot;
  chart: IndicatorChart;
  revisions: DataRevisionRead[];
  relatedSection: RelatedSection;
  asOf: string | null;
};

export type IndicatorDetailResult =
  | { status: "ready"; data: IndicatorDetailData }
  | { status: "not_found" | "invalid" | "unavailable" };
