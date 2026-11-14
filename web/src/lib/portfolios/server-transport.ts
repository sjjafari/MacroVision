import "server-only";
import { createServerApiClient } from "@/lib/api/server-client";
export function createPortfolioTransport(){const client=createServerApiClient();return {
 async list(){const r=await client.GET("/api/v1/portfolios",{params:{query:{limit:100,offset:0}}});return {data:r.data??null,status:r.response.status};},
 async detail(id:number){const r=await client.GET("/api/v1/portfolios/{portfolio_id}",{params:{path:{portfolio_id:id}}});return {data:r.data??null,status:r.response.status};},
 async summary(id:number){const r=await client.GET("/api/v1/portfolios/{portfolio_id}/summary",{params:{path:{portfolio_id:id}}});return {data:r.data??null,status:r.response.status};},
 async transactions(id:number){const r=await client.GET("/api/v1/portfolios/{portfolio_id}/transactions",{params:{path:{portfolio_id:id},query:{limit:100,offset:0}}});return {data:r.data??null,status:r.response.status};},
 async snapshots(id:number){const r=await client.GET("/api/v1/portfolios/{portfolio_id}/snapshots",{params:{path:{portfolio_id:id},query:{limit:100,offset:0}}});return {data:r.data??null,status:r.response.status};},
};}
export type PortfolioTransport=ReturnType<typeof createPortfolioTransport>;
