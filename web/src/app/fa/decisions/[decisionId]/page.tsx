export const dynamic = "force-dynamic";

import { notFound } from "next/navigation";
import { DecisionDetail } from "@/components/decisions/decision-detail";
import { DecisionPortfolioContext } from "@/components/decisions/decision-portfolio-context";
import { loadDecisionDetail } from "@/lib/decisions/loader";
import { loadDecisionPortfolioContext } from "@/lib/decisions/portfolio-context";

export default async function DecisionDetailPage({params,searchParams=Promise.resolve({})}:{params:Promise<{decisionId:string}>;searchParams?:Promise<Record<string,string|string[]|undefined>>}){
 const {decisionId}=await params; const query=await searchParams; const raw=Array.isArray(query.error)?query.error[0]:query.error; const portfolioRaw=Array.isArray(query.portfolio_id)?query.portfolio_id[0]:query.portfolio_id; const result=await loadDecisionDetail(decisionId);
 if(result.status==="not_found") notFound();
 if(result.status==="error") return <section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h1>پرونده تصمیم در دسترس نیست</h1><p>دادهٔ ناقص به‌عنوان پروندهٔ معتبر نمایش داده نمی‌شود.</p></div></section>;
 const context=await loadDecisionPortfolioContext(portfolioRaw);
 return <div className="page-stack"><DecisionDetail decision={result.decision} history={result.history} error={raw?.slice(0,240)}/><DecisionPortfolioContext decisionId={result.decision.id} context={context}/></div>;
}
