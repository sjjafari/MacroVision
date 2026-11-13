import { describe, expect, it } from "vitest";
import { projectComparisonDecimal } from "./comparison-chart";

describe("comparison chart geometry", () => {
  it("projects exact strings only for finite canvas geometry", () => {
    expect(projectComparisonDecimal("123.45000000")).toBe(123.45);
    expect(projectComparisonDecimal(null)).toBeNull();
    expect(projectComparisonDecimal("not-a-number")).toBeNull();
  });
});
