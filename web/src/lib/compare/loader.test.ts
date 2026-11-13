import { describe, expect, it } from "vitest";
import { normalizeCompareQuery } from "./loader";

describe("comparison URL contract", () => {
  it("accepts one to four unique typed selections and UTC day bounds", () => {
    expect(normalizeCompareQuery({
      items: ["raw:11", "derived:31"],
      start: "2026-01-01",
      end: "2026-06-30",
      as_of: "2026-06-30",
    })).toEqual({
      items: ["raw:11", "derived:31"],
      start: "2026-01-01T00:00:00.000Z",
      end: "2026-06-30T23:59:59.999Z",
      asOf: "2026-06-30T23:59:59.999Z",
    });
  });
  it("rejects duplicates, malformed ids, too many selections and invalid ranges", () => {
    expect(normalizeCompareQuery({items:["raw:1","raw:1"],start:"2026-01-01",end:"2026-02-01"})).toBeNull();
    expect(normalizeCompareQuery({items:"raw:0",start:"2026-01-01",end:"2026-02-01"})).toBeNull();
    expect(normalizeCompareQuery({items:["raw:1","raw:2","raw:3","raw:4","raw:5"],start:"2026-01-01",end:"2026-02-01"})).toBeNull();
    expect(normalizeCompareQuery({items:"raw:1",start:"2026-03-01",end:"2026-02-01"})).toBeNull();
  });
  it("returns no execution query until a selection exists", () => {
    expect(normalizeCompareQuery({start:"2026-01-01",end:"2026-02-01"})).toBeNull();
  });
});
