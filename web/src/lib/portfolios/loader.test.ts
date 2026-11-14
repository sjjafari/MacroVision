import { describe,expect,it,vi } from "vitest";
import { loadPortfolioDetail,loadPortfolioIndex } from "./loader";
import type { PortfolioTransport } from "./server-transport";
const p={id:4,investor_id:null,name:"سبد اصلی",base_currency:"USD",lock_version:3,created_at:"2026-01-01T00:00:00Z",positions:[],cash_balances:[]};
describe("portfolio reader loader",()=>{
 it("lists without mutation",async()=>{const t={list:vi.fn(async()=>({status:200,data:[p]}))} as unknown as PortfolioTransport;expect((await loadPortfolioIndex(t)).status).toBe("ready");});
 it("rejects malformed ids before transport",async()=>{const detail=vi.fn();const t={detail} as unknown as PortfolioTransport;expect((await loadPortfolioDetail("-4",t)).status).toBe("not_found");expect(detail).not.toHaveBeenCalled();});
 it("loads summary ledger and snapshots together",async()=>{const t={detail:vi.fn(async()=>({status:200,data:p})),summary:vi.fn(async()=>({status:200,data:{portfolio_id:4,valuation_currency:"USD",total_value:"100.00000000",position_value:"0.00000000",base_cash_balance:"100.00000000",total_cost_basis:"0.00000000",realized_pl:"0.00000000",unrealized_pl:"0.00000000",allocations:{},cash_balances:{USD:"100.00000000"},unconverted_cash_currencies:[]}})),transactions:vi.fn(async()=>({status:200,data:[]})),snapshots:vi.fn(async()=>({status:200,data:[]}))} as unknown as PortfolioTransport;const r=await loadPortfolioDetail("4",t);expect(r.status).toBe("ready");expect(t.transactions).toHaveBeenCalledWith(4);expect(t.snapshots).toHaveBeenCalledWith(4);});
});
