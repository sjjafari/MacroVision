import { describe, expect, it } from "vitest";

import { NAVIGATION_ROUTES, WEB_ROUTES } from "@/lib/routes";

describe("approved route registry", () => {
  it("contains the v0.8 routes plus protected v0.9 decision routes", () => {
    expect(WEB_ROUTES.map((route) => route.href)).toEqual([
      "/fa",
      "/fa/markets",
      "/fa/macro",
      "/fa/indicators",
      "/fa/indicators/[seriesId]",
      "/fa/compare",
      "/fa/decisions",
      "/fa/decisions/[decisionId]",
      "/fa/portfolios",
      "/fa/portfolios/[portfolioId]",
      "/fa/research",
      "/fa/methodology",
      "/fa/about",
    ]);
    expect(WEB_ROUTES).toHaveLength(13);
  });

  it("contains Persian labels and no magazine route", () => {
    expect(NAVIGATION_ROUTES.map((route) => route.label)).toContain("اقتصاد کلان");
    expect(NAVIGATION_ROUTES.map((route) => route.label)).toContain("تصمیم‌ها");
    expect(NAVIGATION_ROUTES.map((route) => route.label)).toContain("پرتفوها");
    expect(NAVIGATION_ROUTES).toHaveLength(10);
    expect(NAVIGATION_ROUTES.every((route) => route.navigation)).toBe(true);
    expect(WEB_ROUTES.some((route) => route.href.includes("magazine"))).toBe(false);
  });
});
