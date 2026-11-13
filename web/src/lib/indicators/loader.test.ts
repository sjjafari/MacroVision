import { describe, expect, it } from "vitest";
import { chartWindow, historicalCutoff, loadIndicatorDetail, normalizeCatalogQuery, visibleRevisionsAtCutoff } from "./loader";
import type { IndicatorTransport } from "./server-transport";
import type { DataRevisionRead } from "./types";
import { vi } from "vitest";

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

  it("filters historical revisions against canonical UTC timestamps", () => {
    const revision = (id: number, timestamp: string, value: string): DataRevisionRead => ({ id, observation_id:21, sequence:id, previous_value:"1.00000000", revised_value:value, previous_status:"present", revised_status:"present", revision_timestamp:timestamp, reason:"source_revision", source_reference:null, import_batch_id:null, publication_timestamp:null, provider_vintage_start:null, provider_vintage_end:null, provider_metadata:{} });
    const revisions = [revision(1,"2026-06-29T00:00:00Z","2.10000000"), revision(2,"2026-06-30T23:59:59.999Z","2.20000000"), revision(3,"2026-07-01T00:00:00Z","9.90000000"), revision(4,"invalid","8.80000000")];
    expect(visibleRevisionsAtCutoff(revisions,"2026-06-30T23:59:59.999Z").map(item=>item.revised_value)).toEqual(["2.10000000","2.20000000"]);
    expect(visibleRevisionsAtCutoff(revisions,null)).toBe(revisions);
  });

  it("never reads current related-derived or lineage in historical mode", async () => {
    const related = vi.fn(); const lineage = vi.fn();
    const transport = {
      detail: vi.fn(async()=>({status:200,data:{curation:{curation_status:"reviewed_private"},canonical:{series_id:11},presentation:{},source:{}}})),
      snapshot: vi.fn(async()=>({status:200,data:{frequency:"monthly",observed_at:"2026-06-01T00:00:00Z",observation_identity:{observation_id:21,revision_count:1}}})),
      observations: vi.fn(async()=>({status:200,data:[]})),
      revisions: vi.fn(async()=>({status:200,data:[{id:1,observation_id:21,sequence:1,previous_value:"1.00000000",revised_value:"2.00000000",previous_status:"present",revised_status:"present",revision_timestamp:"2026-06-01T00:00:00Z",reason:"source_revision",source_reference:null,import_batch_id:null,publication_timestamp:null,provider_vintage_start:null,provider_vintage_end:null,provider_metadata:{}}]})),
      related, lineage,
    } as unknown as IndicatorTransport;
    const result = await loadIndicatorDetail("11","2026-06-30",transport);
    expect(result.status).toBe("ready");
    if(result.status === "ready") expect(result.data.relatedSection.status).toBe("historical_not_supported");
    expect(related).not.toHaveBeenCalled(); expect(lineage).not.toHaveBeenCalled();
  });

  it("keeps current related-derived and eligible lineage reads", async () => {
    const related = vi.fn(async()=>({status:200,data:{series_id:11,series_code:"FRED.CPI",items:[{run_id:41,observation_id:51}]}}));
    const lineage = vi.fn(async()=>({status:200,data:{run_id:41,observation_id:51,limit:100,offset:0,items:[]}}));
    const transport = {
      detail: vi.fn(async()=>({status:200,data:{curation:{curation_status:"reviewed_private"},canonical:{series_id:11},presentation:{},source:{}}})),
      snapshot: vi.fn(async()=>({status:200,data:{frequency:"monthly",observed_at:null,observation_identity:null}})),
      observations:vi.fn(), revisions:vi.fn(), related, lineage,
    } as unknown as IndicatorTransport;
    const result=await loadIndicatorDetail("11",undefined,transport);
    expect(result.status).toBe("ready"); expect(related).toHaveBeenCalledOnce(); expect(lineage).toHaveBeenCalledWith(41,51);
  });
});
