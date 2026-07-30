import "server-only";

import { createApiClient } from "@/lib/api/client";
import { getBackendUrl } from "@/lib/api/backend-url";

export const DASHBOARD_REQUEST_TIMEOUT_MS = 5_000;

async function privateReadFetch(
  input: URL | RequestInfo,
  init?: RequestInit,
): Promise<Response> {
  const request = new Request(input, init);
  if (request.method !== "GET") {
    throw new Error("Private dashboard transport permits GET requests only.");
  }
  const signal = AbortSignal.any([
    request.signal,
    AbortSignal.timeout(DASHBOARD_REQUEST_TIMEOUT_MS),
  ]);
  return fetch(
    new Request(request, {
      cache: "no-store",
      redirect: "manual",
      signal,
    }),
  );
}

export function createServerApiClient() {
  return createApiClient(getBackendUrl().toString(), privateReadFetch);
}
