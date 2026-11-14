"use server";

import { redirect } from "next/navigation";
import type { components } from "@/lib/api/generated/schema";
import { requireMutationRole } from "@/lib/security/request-auth";
import { createDecisionMutationClient } from "./mutation-client";

type SourceType=components["schemas"]["EvidenceSourceType"];
type Side=components["schemas"]["EvidenceSide"];

function text(form:FormData,key:string,max=4000){const value=String(form.get(key)??"").trim();return value&&value.length<=max?value:null;}
function positive(form:FormData,key:string){const raw=text(form,key,20);if(!raw||!/^\d+$/.test(raw))return null;const n=Number(raw);return Number.isSafeInteger(n)&&n>0?n:null;}
function score(form:FormData,key:string){const raw=text(form,key,20);if(!raw||!/^(?:0(?:\.\d{1,6})?|1(?:\.0{1,6})?)$/.test(raw))return null;return raw;}
function optionalDate(form:FormData,key:string){const raw=String(form.get(key)??"").trim();if(!raw)return undefined;if(!/^\d{4}-\d{2}-\d{2}$/.test(raw))return null;const d=new Date(raw+"T00:00:00Z");return Number.isFinite(d.getTime())&&d.toISOString().startsWith(raw)?raw:null;}
function confirmed(form:FormData){return form.get("confirm")==="yes";}
function fail(path:string,message:string):never{redirect(path+(path.includes("?")?"&":"?")+"error="+encodeURIComponent(message));}
function detailPath(id:number){return "/fa/decisions/"+id;}
function log(event:string,actor:{user:string;role:string},decisionId:number){console.info(JSON.stringify({event,actor:actor.user,role:actor.role,decision_id:decisionId}));}
async function postOrFail<T>(path:string,operation:()=>Promise<{data?:T|null;response:Response}>,message:string){try{const result=await operation();if(!result.data)fail(path,result.response.status===409?"پرونده همزمان تغییر کرده است؛ صفحه را بازخوانی و دوباره ارزیابی کنید.":message);return result.data;}catch(error){if(error instanceof Error&&error.message==="NEXT_REDIRECT")throw error;fail(path,message);}}

export async function createDecisionAction(form:FormData){
 const actor=await requireMutationRole("research");const title=text(form,"title",180),question=text(form,"question"),context=text(form,"context")??"",rationale=text(form,"rationale"),probability=score(form,"probability"),confidence=score(form,"confidence");
 if(!title||!question||!rationale||!probability||!confidence)fail("/fa/decisions","فیلدهای پرونده تصمیم معتبر نیستند.");
 const client=createDecisionMutationClient();const data=await postOrFail("/fa/decisions",()=>client.POST("/api/v1/decisions",{body:{title,question,context,rationale,probability,confidence}}),"پرونده تصمیم ایجاد نشد.");
 log("decision_created",actor,data.id);redirect(detailPath(data.id));
}
export async function addHypothesisAction(form:FormData){
 const actor=await requireMutationRole("research"),id=positive(form,"decision_id"),statement=text(form,"statement"),rationale=text(form,"rationale")??"";if(!id||!statement)fail("/fa/decisions","فرضیه معتبر نیست.");
 const path=detailPath(id),client=createDecisionMutationClient();await postOrFail(path,()=>client.POST("/api/v1/decisions/{decision_id}/hypotheses",{params:{path:{decision_id:id}},body:{statement,rationale}}),"فرضیه ثبت نشد.");log("decision_hypothesis_added",actor,id);redirect(path);
}
export async function addEvidenceAction(form:FormData){
 const actor=await requireMutationRole("research"),id=positive(form,"decision_id"),side=text(form,"side",20) as Side|null,source_title=text(form,"source_title",240),source_type=text(form,"source_type",40) as SourceType|null,publication_date=optionalDate(form,"publication_date"),reference=text(form,"reference",500),reliability_score=score(form,"reliability_score"),relevance_score=score(form,"relevance_score"),notes=text(form,"notes")??"";
 const sides=new Set(["supporting","opposing"]),types=new Set(["research_paper","financial_statement","market_data","news","expert_opinion","internal_analysis","other"]);
 if(!id||!side||!sides.has(side)||!source_title||!source_type||!types.has(source_type)||publication_date===null||!reliability_score||!relevance_score)fail(id?detailPath(id):"/fa/decisions","شاهد واردشده معتبر نیست.");
 const path=detailPath(id),client=createDecisionMutationClient();await postOrFail(path,()=>client.POST("/api/v1/decisions/{decision_id}/evidence",{params:{path:{decision_id:id}},body:{side,source_title,source_type,publication_date,reference,reliability_score,relevance_score,notes}}),"شاهد ثبت نشد.");log("decision_evidence_added",actor,id);redirect(path);
}
export async function addCriticAction(form:FormData){
 const actor=await requireMutationRole("research"),id=positive(form,"decision_id"),reviewer=text(form,"reviewer",160),analysis=text(form,"analysis"),key_risks=text(form,"key_risks"),recommendation=text(form,"recommendation");if(!id||!reviewer||!analysis||!key_risks||!recommendation)fail(id?detailPath(id):"/fa/decisions","نقد مستقل کامل نیست.");
 const path=detailPath(id),client=createDecisionMutationClient();await postOrFail(path,()=>client.POST("/api/v1/decisions/{decision_id}/critic-reviews",{params:{path:{decision_id:id}},body:{reviewer,analysis,key_risks,recommendation}}),"نقد مستقل ثبت نشد.");log("decision_critic_added",actor,id);redirect(path);
}
export async function addInvalidationRuleAction(form:FormData){
 const actor=await requireMutationRole("research"),id=positive(form,"decision_id"),condition=text(form,"condition"),observation_source=text(form,"observation_source",300),notes=text(form,"notes")??"";if(!id||!condition||!observation_source)fail(id?detailPath(id):"/fa/decisions","شرط ابطال معتبر نیست.");
 const path=detailPath(id),client=createDecisionMutationClient();await postOrFail(path,()=>client.POST("/api/v1/decisions/{decision_id}/invalidation-rules",{params:{path:{decision_id:id}},body:{condition,observation_source,notes}}),"شرط ابطال ثبت نشد.");log("decision_invalidation_rule_added",actor,id);redirect(path);
}
export async function reviseDecisionAction(form:FormData){
 const actor=await requireMutationRole("research"),id=positive(form,"decision_id"),probability=score(form,"probability"),confidence=score(form,"confidence"),rationale=text(form,"rationale"),change_summary=text(form,"change_summary");if(!id||!probability||!confidence||!rationale||!change_summary)fail(id?detailPath(id):"/fa/decisions","بازنگری معتبر نیست.");
 const path=detailPath(id),client=createDecisionMutationClient();await postOrFail(path,()=>client.POST("/api/v1/decisions/{decision_id}/revise",{params:{path:{decision_id:id}},body:{probability,confidence,rationale,change_summary}}),"بازنگری ثبت نشد.");log("decision_revised",actor,id);redirect(path);
}
export async function activateDecisionAction(form:FormData){
 const actor=await requireMutationRole("research"),id=positive(form,"decision_id");if(!id||!confirmed(form))fail(id?detailPath(id):"/fa/decisions","فعال‌سازی باید صریحاً تأیید شود.");
 const path=detailPath(id),client=createDecisionMutationClient();await postOrFail(path,()=>client.POST("/api/v1/decisions/{decision_id}/activate",{params:{path:{decision_id:id}}}),"پرونده فعال نشد؛ گیت‌های کامل‌بودن را بررسی کنید.");log("decision_activated",actor,id);redirect(path);
}
export async function invalidateDecisionAction(form:FormData){
 const actor=await requireMutationRole("research"),id=positive(form,"decision_id"),reason=text(form,"reason"),rule_id=positive(form,"rule_id");if(!id||!reason||!confirmed(form))fail(id?detailPath(id):"/fa/decisions","ابطال باید با دلیل و تأیید صریح انجام شود.");
 const path=detailPath(id),client=createDecisionMutationClient();await postOrFail(path,()=>client.POST("/api/v1/decisions/{decision_id}/invalidate",{params:{path:{decision_id:id}},body:{reason,rule_id:rule_id??undefined}}),"پرونده باطل نشد.");log("decision_invalidated",actor,id);redirect(path);
}
export async function closeDecisionAction(form:FormData){
 const actor=await requireMutationRole("research"),id=positive(form,"decision_id"),outcome=text(form,"outcome"),lessons_learned=text(form,"lessons_learned"),accuracy_assessment=score(form,"accuracy_assessment");if(!id||!outcome||!lessons_learned||!accuracy_assessment||!confirmed(form))fail(id?detailPath(id):"/fa/decisions","بستن پرونده نیازمند نتیجه، درس‌آموخته، ارزیابی دقت و تأیید صریح است.");
 const path=detailPath(id),client=createDecisionMutationClient();await postOrFail(path,()=>client.POST("/api/v1/decisions/{decision_id}/close",{params:{path:{decision_id:id}},body:{outcome,lessons_learned,accuracy_assessment}}),"پرونده بسته نشد.");log("decision_closed",actor,id);redirect(path);
}
