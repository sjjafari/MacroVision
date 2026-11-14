export const dynamic = "force-dynamic";

import { DecisionIndex } from "@/components/decisions/decision-index";
import { loadDecisionIndex } from "@/lib/decisions/loader";

export default async function DecisionsPage({searchParams=Promise.resolve({})}:{searchParams?:Promise<Record<string,string|string[]|undefined>>}){
 const result=await loadDecisionIndex(); const params=await searchParams; const raw=Array.isArray(params.error)?params.error[0]:params.error;
 if(result.status==="error") return <section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h1>پرونده‌های تصمیم در دسترس نیستند</h1><p>جزئیات خطای خصوصی نمایش داده نمی‌شود.</p></div></section>;
 return <DecisionIndex decisions={result.decisions} error={raw?.slice(0,240)}/>;
}
