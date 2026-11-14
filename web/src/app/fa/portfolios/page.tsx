export const dynamic="force-dynamic";
import { PortfolioIndex } from "@/components/portfolios/portfolio-index";
import { loadPortfolioIndex } from "@/lib/portfolios/loader";
export default async function PortfoliosPage(){const r=await loadPortfolioIndex();if(r.status==="error")return <section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h1>پرتفوها در دسترس نیستند</h1><p>جزئیات خطای خصوصی نمایش داده نمی‌شود.</p></div></section>;return <PortfolioIndex portfolios={r.portfolios}/>;}
