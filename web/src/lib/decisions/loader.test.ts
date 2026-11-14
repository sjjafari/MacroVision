import { describe,expect,it,vi } from "vitest";
import { loadDecisionDetail,loadDecisionIndex } from "./loader";
import type { DecisionTransport } from "./server-transport";

const decision={id:7,title:"تز تورم",question:"آیا تورم پایدار می‌ماند؟",context:"",rationale:"شواهد اولیه",probability:"0.650000",confidence:"0.700000",status:"under_review" as const,current_version:2,created_at:"2026-01-01T00:00:00Z",updated_at:"2026-02-01T00:00:00Z",hypotheses:[],supporting_evidence:[],opposing_evidence:[],critic_reviews:[],invalidation_rules:[],outcome:null};

describe("decision reader loader",()=>{
 it("lists without mutation",async()=>{const t={list:vi.fn(async()=>({status:200,data:[decision]}))} as unknown as DecisionTransport;const r=await loadDecisionIndex(t);expect(r.status).toBe("ready");expect(t.list).toHaveBeenCalledOnce();});
 it("rejects invalid ids before transport",async()=>{const detail=vi.fn();const t={detail} as unknown as DecisionTransport;expect((await loadDecisionDetail("../7",t)).status).toBe("not_found");expect(detail).not.toHaveBeenCalled();});
 it("loads detail and immutable history",async()=>{const t={detail:vi.fn(async()=>({status:200,data:decision})),history:vi.fn(async()=>({status:200,data:[{id:1,decision_id:7,version:1,event:"created",status:"draft",probability:"0.500000",confidence:"0.500000",rationale:"اولیه",change_summary:"created",created_at:"2026-01-01T00:00:00Z"}]}))} as unknown as DecisionTransport;const r=await loadDecisionDetail("7",t);expect(r.status).toBe("ready");expect(t.history).toHaveBeenCalledWith(7);});
 it("preserves backend 404 as not found",async()=>{const t={detail:vi.fn(async()=>({status:404,data:null}))} as unknown as DecisionTransport;expect((await loadDecisionDetail("99",t)).status).toBe("not_found");});
});
