import type { components } from "@/lib/api/generated/schema";

export type ComparisonRead = components["schemas"]["ComparisonRead"];
export type ComparisonSeries = components["schemas"]["ComparisonSeries"];
export type IndicatorCatalogPage = components["schemas"]["IndicatorCatalogPage"];
export type DerivedSeriesPage = components["schemas"]["DerivedSeriesPage"];

export type CompareQuery = {
  items: string[];
  start: string;
  end: string;
  asOf?: string;
};
