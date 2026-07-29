import { describe, expect, it } from "vitest";

import { rewriteUpstreamRedirect } from "@/lib/api/redirect";

describe("upstream redirect policy", () => {
  const backendUrl = new URL("http://127.0.0.1:8100/backend");
  const requestUrl = new URL("http://127.0.0.1:8100/backend/api/v1/series/current");

  it("rewrites relative and same-origin absolute API redirects", () => {
    expect(rewriteUpstreamRedirect("next?limit=20", requestUrl, backendUrl)).toBe(
      "/api/v1/series/next?limit=20",
    );
    expect(
      rewriteUpstreamRedirect(
        "http://127.0.0.1:8100/backend/api/v1/series/next?cursor=abc",
        requestUrl,
        backendUrl,
      ),
    ).toBe("/api/v1/series/next?cursor=abc");
  });

  it.each([
    "https://attacker.invalid/api/v1/collect",
    "http://user:secret@127.0.0.1:8100/backend/api/v1/collect",
    "http://127.0.0.1:8100/private",
    "http://127.0.0.1:8100/backend/api/v10/not-v1",
  ])("rejects unsafe redirect %s", (location) => {
    expect(rewriteUpstreamRedirect(location, requestUrl, backendUrl)).toBeNull();
  });

  it("uses the configured base path as the exact API boundary", () => {
    const unusualBase = new URL("http://127.0.0.1:8100/prefix-api/v1-shadow");
    const unusualRequest = new URL(
      "http://127.0.0.1:8100/prefix-api/v1-shadow/api/v1/series/current",
    );
    expect(
      rewriteUpstreamRedirect(
        "/prefix-api/v1-shadow/api/v1/series/next",
        unusualRequest,
        unusualBase,
      ),
    ).toBe("/api/v1/series/next");
  });
});
