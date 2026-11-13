import { describe, expect, it } from "vitest";

import { NAVIGATION_ROUTES, WEB_ROUTES } from "@/lib/routes";

describe("route registry after Phase 7", () => {
  it("preserves the original nine routes and adds only the deferred magazine pair", () => {
    expect(WEB_ROUTES.map((route) => route.href)).toEqual([
      "/fa",
      "/fa/markets",
      "/fa/macro",
      "/fa/indicators",
      "/fa/indicators/[seriesId]",
      "/fa/compare",
      "/fa/research",
      "/fa/methodology",
      "/fa/about",
      "/fa/magazine",
      "/fa/magazine/[slug]",
    ]);
    expect(WEB_ROUTES).toHaveLength(11);
  });

  it("adds the Phase 7 magazine to navigation without exposing article templates", () => {
    expect(NAVIGATION_ROUTES.map((route) => route.label)).toContain("اقتصاد کلان");
    expect(NAVIGATION_ROUTES.map((route) => route.label)).toContain("مجله");
    expect(NAVIGATION_ROUTES).toHaveLength(9);
    expect(NAVIGATION_ROUTES.every((route) => route.navigation)).toBe(true);
    expect(NAVIGATION_ROUTES.some((route) => route.href.includes("[slug]"))).toBe(false);
  });
});
