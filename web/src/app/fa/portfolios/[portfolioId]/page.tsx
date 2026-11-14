export const dynamic="force-dynamic";
import { notFound } from "next/navigation";
import { PortfolioDetail } from "@/components/portfolios/portfolio-detail";
import { loadPortfolioDetail } from "@/lib/portfolios/loader";
export default async function PortfolioPage({params}:{params:Promise<{portfolioId:string}>}){const {portfolioId}=await params;const r=await loadPortfolioDetail(portfolioId);if(r.status==="not_found")notFound();if(r.status==="error")return <section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h1>پرتفو در دسترس نیست</h1><p>داده ناقص به‌عنوان ارزش‌گذاری معتبر نمایش داده نمی‌شود.</p></div></section>;return <PortfolioDetail portfolio={r.portfolio} summary={r.summary} transactions={r.transactions} snapshots={r.snapshots}/>;}
