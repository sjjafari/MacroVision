import "server-only";

import { createServerApiClient } from "@/lib/api/server-client";
import type { IndicatorQuery } from "@/lib/indicators/types";

type ReadResult<T> = { data: T | null; status: number };

export function createIndicatorTransport() {
  const client = createServerApiClient();
  return {
    async catalog(query: IndicatorQuery) {
      const result = await client.GET("/api/v1/indicator-catalog", { params: { query } });
      return { data: result.data ?? null, status: result.response.status } as ReadResult<NonNullable<typeof result.data>>;
    },
    async detail(seriesId: number) {
      const result = await client.GET("/api/v1/indicator-catalog/{series_id}", { params: { path: { series_id: seriesId } } });
      return { data: result.data ?? null, status: result.response.status };
    },
    async snapshot(seriesId: number, asOf?: string) {
      const result = await client.GET("/api/v1/indicator-catalog/{series_id}/snapshot", { params: { path: { series_id: seriesId }, query: { as_of: asOf } } });
      return { data: result.data ?? null, status: result.response.status };
    },
    async observations(seriesId: number, start: string, end: string, asOf?: string) {
      const path = asOf ? "/api/v1/data-series/{series_id}/observations/as-of" as const : "/api/v1/data-series/{series_id}/observations" as const;
      const query = asOf ? { as_of: asOf, start, end, limit: 200, offset: 0 } : { start, end, limit: 200, offset: 0 };
      const result = await client.GET(path, { params: { path: { series_id: seriesId }, query } });
      return { data: result.data ?? null, status: result.response.status };
    },
    async revisions(seriesId: number, observationId: number) {
      const result = await client.GET("/api/v1/data-series/{series_id}/observations/{observation_id}/revisions", { params: { path: { series_id: seriesId, observation_id: observationId }, query: { limit: 100, offset: 0 } } });
      return { data: result.data ?? null, status: result.response.status };
    },
    async related(seriesId: number) {
      const result = await client.GET("/api/v1/indicator-catalog/{series_id}/related-derived", { params: { path: { series_id: seriesId } } });
      return { data: result.data ?? null, status: result.response.status };
    },
    async lineage(runId: number, observationId: number) {
      const result = await client.GET("/api/v1/analytics-runs/{run_id}/observations/{observation_id}/lineage", { params: { path: { run_id: runId, observation_id: observationId }, query: { limit: 100, offset: 0 } } });
      return { data: result.data ?? null, status: result.response.status };
    },
  };
}

export type IndicatorTransport = ReturnType<typeof createIndicatorTransport>;
