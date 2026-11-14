import "server-only";
import { createServerApiClient } from "@/lib/api/server-client";

export function createDecisionTransport() {
  const client=createServerApiClient();
  return {
    async list(limit=100,offset=0) {
      const result=await client.GET("/api/v1/decisions",{params:{query:{limit,offset}}});
      return {data:result.data??null,status:result.response.status};
    },
    async detail(id:number) {
      const result=await client.GET("/api/v1/decisions/{decision_id}",{params:{path:{decision_id:id}}});
      return {data:result.data??null,status:result.response.status};
    },
    async history(id:number) {
      const result=await client.GET("/api/v1/decisions/{decision_id}/history",{params:{path:{decision_id:id},query:{limit:100,offset:0}}});
      return {data:result.data??null,status:result.response.status};
    },
  };
}
export type DecisionTransport=ReturnType<typeof createDecisionTransport>;
