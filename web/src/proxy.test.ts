import { describe, expect, it } from "vitest";
import { isPublicPath } from "./proxy";

describe("publication route boundary", () => {
  it("allows only reviewed static and indicator routes", () => {
    expect(isPublicPath("/fa/about")).toBe(true);
    expect(isPublicPath("/fa/methodology")).toBe(true);
    expect(isPublicPath("/fa/indicators")).toBe(true);
    expect(isPublicPath("/fa/indicators/11")).toBe(true);
  });
  it("keeps dashboards, comparison and research authenticated", () => {
    expect(isPublicPath("/fa")).toBe(false);
    expect(isPublicPath("/fa/macro")).toBe(false);
    expect(isPublicPath("/fa/compare")).toBe(false);
    expect(isPublicPath("/fa/research")).toBe(false);
    expect(isPublicPath("/fa/magazine")).toBe(false);
  });
});
