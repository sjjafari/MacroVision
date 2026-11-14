import { notFound } from "next/navigation";
import { DecisionDetail } from "@/components/decisions/decision-detail";
import { loadDecisionDetail } from "@/lib/decisions/loader";

export default async function DecisionDetailPage({params}:{params:Promise<{decisionId:string}>}){
 const {decisionId}=await params; const result=await loadDecisionDetail(decisionId);
 if(result.status==="not_found") notFound();
 if(result.status==="error") return <section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h1>پرونده تصمیم در دسترس نیست</h1><p>دادهٔ ناقص به‌عنوان پروندهٔ معتبر نمایش داده نمی‌شود.</p></div></section>;
 return <DecisionDetail decision={result.decision} history={result.history}/>;
}
