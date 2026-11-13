import "server-only";

import { createServerApiClient } from "@/lib/api/server-client";
import type { CompareQuery } from "./types";

export function createCompareTransport() {
  const client = createServerApiClient();
  return {
    async catalog() {
      const result = await client.GET("/api/v1/indicator-catalog", { params: { query: { limit: 100, offset: 0 } } });
      return { data: result.data ?? null, status: result.response.status };
    },
    async definitions() {
      const result = await client.GET("/api/v1/derived-series", { params: { query: { limit: 100, offset: 0, enabled: true } } });
      return { data: result.data ?? null, status: result.response.status };
    },
    async comparison(query: CompareQuery) {
      const result = await client.GET("/api/v1/comparison", { params: { query: { items: query.items.join(","), start: query.start, end: query.end, as_of: query.asOf } } });
      return { data: result.data ?? null, status: result.response.status };
    },
  };
}
export type CompareTransport = ReturnType<typeof createCompareTransport>;
