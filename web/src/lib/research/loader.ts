import "server-only";
import { createServerApiClient } from "@/lib/api/server-client";

function positive(value: string | string[] | undefined) {
  const raw=Array.isArray(value)?value[0]:value;
  if(!raw||!/^[1-9]\d*$/.test(raw)) return null;
  const id=Number(raw); return Number.isSafeInteger(id)?id:null;
}
export async function loadResearch(params: Record<string,string|string[]|undefined>) {
  const client=createServerApiClient();
  const definitionId=positive(params.definition_id), runId=positive(params.run_id), observationId=positive(params.observation_id);
  try {
    const [series,definitions]=await Promise.all([
      client.GET("/api/v1/data-series",{params:{query:{limit:100,offset:0,is_active:true}}}),
      client.GET("/api/v1/derived-series",{params:{query:{limit:100,offset:0}}}),
    ]);
    if(!series.data||!definitions.data) return {status:"error" as const};
    let selectedDefinition=null, run=null, observations=null, lineage=null;
    if(definitionId){
      const detail=await client.GET("/api/v1/derived-series/{definition_id}",{params:{path:{definition_id:definitionId}}});
      selectedDefinition=detail.data??null;
    }
    if(runId){
      const [runResult,observationResult]=await Promise.all([
        client.GET("/api/v1/analytics-runs/{run_id}",{params:{path:{run_id:runId}}}),
        client.GET("/api/v1/analytics-runs/{run_id}/observations",{params:{path:{run_id:runId},query:{limit:200,offset:0}}}),
      ]);
      run=runResult.data??null; observations=observationResult.data??null;
      if(observationId){
        const l=await client.GET("/api/v1/analytics-runs/{run_id}/observations/{observation_id}/lineage",{params:{path:{run_id:runId,observation_id:observationId},query:{limit:100,offset:0}}});
        lineage=l.data??null;
      }
    }
    return {status:"ready" as const,series:series.data,definitions:definitions.data,selectedDefinition,run,observations,lineage,definitionId,runId,observationId};
  } catch { return {status:"error" as const}; }
}
