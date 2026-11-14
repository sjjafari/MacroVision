import "server-only";
import { createDecisionTransport,type DecisionTransport } from "./server-transport";

export async function loadDecisionIndex(transport:DecisionTransport=createDecisionTransport()) {
  try {
    const result=await transport.list();
    if (!result.data) return {status:"error" as const};
    return {status:"ready" as const,decisions:result.data};
  } catch { return {status:"error" as const}; }
}

export async function loadDecisionDetail(idText:string,transport:DecisionTransport=createDecisionTransport()) {
  if(!/^[1-9]\d*$/.test(idText)) return {status:"not_found" as const};
  const id=Number(idText);
  try {
    const detail=await transport.detail(id);
    if(detail.status===404) return {status:"not_found" as const};
    if(!detail.data) return {status:"error" as const};
    const history=await transport.history(id);
    if(!history.data) return {status:"error" as const};
    return {status:"ready" as const,decision:detail.data,history:history.data};
  } catch { return {status:"error" as const}; }
}
