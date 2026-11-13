import { ComparePageView } from "@/components/compare/compare-page";
import { loadComparePage } from "@/lib/compare/loader";

export default async function ComparePage({ searchParams }: { searchParams: Promise<Record<string,string|string[]|undefined>> }) {
  const result = await loadComparePage(await searchParams);
  if (result.status === "error") return <section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h1>فضای مقایسه موقتاً در دسترس نیست</h1><p>جزئیات خطای خصوصی نمایش داده نمی‌شود.</p></div></section>;
  if (result.status === "comparison_error") return <div className="page-stack"><ComparePageView catalog={result.catalog} definitions={result.definitions} comparison={null} query={result.query} /><section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h2>مقایسه اجرا نشد</h2><p>انتخاب، بازهٔ زمانی یا دسترسی داده را بررسی کنید.</p></div></section></div>;
  return <ComparePageView catalog={result.catalog} definitions={result.definitions} comparison={result.comparison} query={result.query} />;
}
