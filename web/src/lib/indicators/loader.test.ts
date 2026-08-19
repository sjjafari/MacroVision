import { describe, expect, it } from "vitest";
import { chartWindow, historicalCutoff, normalizeCatalogQuery } from "./loader";

describe("indicator URL contract", () => {
  it("normalizes bounded filters and deterministic pagination", () => {
    expect(normalizeCatalogQuery({ search: "  تورم  ", category: "inflation", frequency: "monthly", geography: " us ", source_id: "7", active: "false", page: "3" })).toEqual({ search:"تورم", category:"inflation", frequency:"monthly", geography:"us", source_id:7, operational_is_active:false, limit:12, offset:24 });
  });
  it("rejects invalid filters instead of forwarding them", () => {
    expect(normalizeCatalogQuery({ category:"private", frequency:"hourly", source_id:"-1", active:"maybe", page:"bad" })).toEqual({ search:undefined, geography:undefined, category:undefined, frequency:undefined, source_id:undefined, operational_is_active:undefined, limit:12, offset:0 });
  });
  it("constructs one aware UTC end-of-day cutoff", () => {
    expect(historicalCutoff("2026-06-30")).toBe("2026-06-30T23:59:59.999Z");
    expect(historicalCutoff("2026-02-30")).toBeNull();
    expect(historicalCutoff("30/06/2026")).toBeNull();
  });
  it("uses bounded frequency-aware chart windows", () => {
    expect(chartWindow("monthly","2026-06-01T00:00:00Z")).toEqual({start:"2016-06-01T00:00:00.000Z",end:"2026-06-01T00:00:00.000Z"});
  });
});
