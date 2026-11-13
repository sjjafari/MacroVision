"use server";

import { redirect } from "next/navigation";
import type { components } from "@/lib/api/generated/schema";
import { createResearchMutationClient } from "./mutation-client";
import { requireMutationRole } from "@/lib/security/request-auth";

type Transformation = components["schemas"]["TransformationType"];
type CreatePayload = components["schemas"]["DerivedSeriesCreate"];

const unary = new Set<Transformation>(["difference","percent_change","year_over_year_percent_change","moving_average","rolling_standard_deviation","rolling_z_score","rebase_index"]);
const binaryAliases: Record<string,[string,string]> = { ratio:["numerator","denominator"], spread:["minuend","subtrahend"] };

function text(form: FormData,key:string,max:number){const value=String(form.get(key)??"").trim();return value&&value.length<=max?value:null;}
function positive(form:FormData,key:string){const raw=text(form,key,20);if(!raw||!/^\d+$/.test(raw))return null;const n=Number(raw);return Number.isSafeInteger(n)&&n>0?n:null;}
function day(value:string|null,end=false){if(!value||!/^\d{4}-\d{2}-\d{2}$/.test(value))return null;const d=new Date(`${value}T${end?"23:59:59.999":"00:00:00.000"}Z`);return Number.isFinite(d.getTime())&&d.toISOString().startsWith(value)?d.toISOString():null;}
function fail(message:string): never {redirect(`/fa/research?error=${encodeURIComponent(message)}`);}

export async function createDefinitionAction(form:FormData) {
  const actor=await requireMutationRole("research");
  const code=text(form,"code",120),title=text(form,"title",240),transformation=text(form,"transformation",80) as Transformation|null;
  const first=positive(form,"source_1"),second=positive(form,"source_2");
  if(!code||!title||!transformation||(!unary.has(transformation)&&!binaryAliases[transformation])||!first) fail("ورودی تعریف تحلیلی معتبر نیست.");
  const aliases=unary.has(transformation)?["value"]:binaryAliases[transformation]!;
  const ids=aliases.length===1?[first]:[first,second];
  if(ids.some(id=>id===null)) fail("این تبدیل به دو سری منبع نیاز دارد.");
  let parameters: CreatePayload["initial_version"]["parameters"];
  if(["moving_average","rolling_standard_deviation","rolling_z_score"].includes(transformation)){
    const window=positive(form,"window"); if(!window||window<2||window>1000) fail("پنجره باید بین ۲ و ۱۰۰۰ باشد.");
    parameters={transformation_type:transformation as "moving_average"|"rolling_standard_deviation"|"rolling_z_score",window};
  } else if(transformation==="rebase_index"){
    const base=day(text(form,"base_date",10)); const baseValue=text(form,"base_value",80)??"100.00000000";
    if(!base||!/^\d+(\.\d+)?$/.test(baseValue)||Number(baseValue)<=0) fail("پارامترهای Rebase معتبر نیست.");
    parameters={transformation_type:"rebase_index",base_timestamp:base,base_value:baseValue};
  } else {
    parameters={transformation_type:transformation as "difference"|"percent_change"|"year_over_year_percent_change"|"ratio"|"spread"};
  }
  const payload:CreatePayload={code,title,description:text(form,"description",2000),enabled:true,initial_version:{inputs:aliases.map((alias,index)=>({alias,source_series_id:ids[index]!})),parameters,change_note:"Created from private Web research workspace"}};
  const client=createResearchMutationClient();
  const result=await client.POST("/api/v1/derived-series",{body:payload});
  if(!result.data) fail("تعریف تحلیلی ایجاد نشد.");
  console.info(JSON.stringify({event:"research_definition_created",actor:actor.user,role:actor.role,definition_id:result.data.id}));
  redirect(`/fa/research?definition_id=${result.data.id}`);
}

export async function executeResearchAction(form:FormData) {
  const actor=await requireMutationRole("research");
  const definitionId=positive(form,"definition_id"),version=positive(form,"definition_version");
  const start=day(text(form,"start",10)),end=day(text(form,"end",10),true),asOfRaw=text(form,"as_of",10),asOf=asOfRaw?day(asOfRaw,true):null;
  if(!definitionId||!start||!end||start>end||(asOfRaw&&!asOf)) fail("بازهٔ اجرای پژوهش معتبر نیست.");
  const client=createResearchMutationClient();
  const result=await client.POST("/api/v1/derived-series/{definition_id}/runs",{params:{path:{definition_id:definitionId}},body:{definition_version:version??undefined,requested_start_at:start,requested_end_at:end,as_of:asOf??undefined,retry_of_run_id:undefined}});
  if(!result.data) fail("اجرای Analytics انجام نشد.");
  console.info(JSON.stringify({event:"research_run_created",actor:actor.user,role:actor.role,definition_id:definitionId,run_id:result.data.run.id}));
  redirect(`/fa/research?definition_id=${definitionId}&run_id=${result.data.run.id}`);
}
