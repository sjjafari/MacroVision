import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createServerApiClient,
  DASHBOARD_REQUEST_TIMEOUT_MS,
} from "@/lib/api/server-client";

describe("server-only dashboard API client", () => {
  beforeEach(() => {
    process.env.MACROVISION_BACKEND_URL = "http://private-backend.test:8100";
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.MACROVISION_BACKEND_URL;
  });

  it("uses the configured backend directly with GET, no-store, and a bounded signal", async () => {
    const fetchMock = vi.fn(async (request: Request) => {
      expect(request.url).toBe(
        "http://private-backend.test:8100/api/v1/dashboards/home",
      );
      expect(request.method).toBe("GET");
      expect(request.cache).toBe("no-store");
      expect(request.redirect).toBe("manual");
      expect(request.signal).toBeInstanceOf(AbortSignal);
      return new Response(
        JSON.stringify({
          dashboard_code: "home",
          title_fa: "خانه",
          description_fa: null,
          groups: [],
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    const response = await createServerApiClient().GET(
      "/api/v1/dashboards/{dashboard_code}",
      { params: { path: { dashboard_code: "home" } } },
    );

    expect(response.response.status).toBe(200);
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(DASHBOARD_REQUEST_TIMEOUT_MS).toBe(5_000);
  });

  it("rejects mutation methods before any request reaches the backend", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const client = createServerApiClient();

    await expect(
      client.POST("/api/v1/data-sources", {
        body: {
          code: "UNSAFE",
          name: "Unsafe",
          description: "Unsafe test payload",
          base_url: null,
        },
      }),
    ).rejects.toThrow("GET requests only");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
