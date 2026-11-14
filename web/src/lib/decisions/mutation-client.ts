import "server-only";
import { createApiClient } from "@/lib/api/client";
import { getBackendUrl } from "@/lib/api/backend-url";

async function mutationFetch(input:URL|RequestInfo,init?:RequestInit){
 const request=new Request(input,init);
 if(request.method!=="POST") throw new Error("Decision mutation transport permits POST only.");
 const signal=AbortSignal.any([request.signal,AbortSignal.timeout(15_000)]);
 return fetch(new Request(request,{cache:"no-store",redirect:"manual",signal}));
}
export function createDecisionMutationClient(){return createApiClient(getBackendUrl().toString(),mutationFetch);}
