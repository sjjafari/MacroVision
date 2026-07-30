import createClient from "openapi-fetch";

import type { paths } from "@/lib/api/generated/schema";

export function createApiClient(
  baseUrl = "",
  fetchImplementation: typeof globalThis.fetch = globalThis.fetch,
) {
  return createClient<paths>({ baseUrl, fetch: fetchImplementation });
}

export const apiClient = createApiClient();
