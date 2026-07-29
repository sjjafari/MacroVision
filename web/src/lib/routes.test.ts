import { describe, expect, it } from "vitest";

import { NAVIGATION_ROUTES, WEB_ROUTES } from "@/lib/routes";

describe("approved route registry", () => {
  it("contains exactly the nine approved routes", () => {
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
    ]);
    expect(WEB_ROUTES).toHaveLength(9);
  });

  it("contains Persian labels and no magazine route", () => {
    expect(NAVIGATION_ROUTES.map((route) => route.label)).toContain("اقتصاد کلان");
    expect(WEB_ROUTES.some((route) => route.href.includes("magazine"))).toBe(false);
  });
});
