import "server-only";

import { createServerApiClient } from "@/lib/api/server-client";
import type {
  DashboardCode,
  DashboardDefinition,
  DashboardSummary,
  DerivedObservationPage,
  ObservationRead,
} from "@/lib/dashboard/types";

type ReadResult<T> = { data: T; status: number } | { data: null; status: number };

export type DashboardReadTransport = {
  definition(code: DashboardCode): Promise<ReadResult<DashboardDefinition>>;
  summary(code: DashboardCode): Promise<ReadResult<DashboardSummary>>;
  rawObservations(
    seriesId: number,
    start: string,
    end: string,
  ): Promise<ReadResult<ObservationRead[]>>;
  derivedObservations(
    definitionId: number,
    start: string,
    end: string,
  ): Promise<ReadResult<DerivedObservationPage>>;
};

export function createDashboardReadTransport(): DashboardReadTransport {
  const client = createServerApiClient();
  return {
    async definition(code) {
      const result = await client.GET("/api/v1/dashboards/{dashboard_code}", {
        params: { path: { dashboard_code: code } },
      });
      return { data: result.data ?? null, status: result.response.status };
    },
    async summary(code) {
      const result = await client.GET(
        "/api/v1/dashboards/{dashboard_code}/summary",
        { params: { path: { dashboard_code: code } } },
      );
      return { data: result.data ?? null, status: result.response.status };
    },
    async rawObservations(seriesId, start, end) {
      const result = await client.GET(
        "/api/v1/data-series/{series_id}/observations",
        {
          params: {
            path: { series_id: seriesId },
            query: { start, end, limit: 200, offset: 0 },
          },
        },
      );
      return { data: result.data ?? null, status: result.response.status };
    },
    async derivedObservations(definitionId, start, end) {
      const result = await client.GET(
        "/api/v1/derived-series/{definition_id}/observations",
        {
          params: {
            path: { definition_id: definitionId },
            query: { start, end, limit: 200, offset: 0 },
          },
        },
      );
      return { data: result.data ?? null, status: result.response.status };
    },
  };
}
