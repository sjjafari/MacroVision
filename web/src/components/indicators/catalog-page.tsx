import Link from "next/link";
import type { IndicatorCatalogPage, IndicatorQuery } from "@/lib/indicators/types";
import { categoryLabels, faDate, frequencyLabels, stateLabels } from "./labels";

function pageHref(query: IndicatorQuery, page: number) {
  const p = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) if (value !== undefined && key !== "limit" && key !== "offset") p.set(key === "operational_is_active" ? "active" : key, String(value));
  p.set("page", String(page)); return `?${p}`;
}
export function CatalogPage({ data, query }: { data: IndicatorCatalogPage; query: IndicatorQuery }) {
  const page = Math.floor(query.offset / query.limit) + 1, pages = Math.max(1, Math.ceil(data.total / query.limit));
  return <div className="page-stack indicator-catalog">
    <header className="indicator-hero"><div><p className="eyebrow">کتابخانهٔ داده‌های منتخب</p><h1>کاتالوگ شاخص‌های اقتصاد کلان</h1><p>شاخص‌های بازبینی‌شده برای پژوهش تصمیم‌محور؛ بدون سیگنال خرید و فروش.</p></div><span className="preview-badge">پیش‌نمایش خصوصی</span></header>
    <form className="indicator-filters" method="get" aria-label="فیلتر شاخص‌ها">
      <label>جست‌وجو<input name="search" defaultValue={query.search} placeholder="نام، کد یا توضیح" /></label>
      <label>دسته<select name="category" defaultValue={query.category ?? ""}><option value="">همه</option>{Object.entries(categoryLabels).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
      <label>دوره<select name="frequency" defaultValue={query.frequency ?? ""}><option value="">همه</option>{Object.entries(frequencyLabels).map(([v,l])=><option key={v} value={v}>{l}</option>)}</select></label>
      <label>جغرافیا<input name="geography" defaultValue={query.geography} placeholder="برای نمونه US" /></label>
      <label>شناسه منبع<input name="source_id" inputMode="numeric" defaultValue={query.source_id} /></label>
      <label>وضعیت عملیاتی<select name="active" defaultValue={query.operational_is_active === undefined ? "" : String(query.operational_is_active)}><option value="">همه</option><option value="true">فعال</option><option value="false">غیرفعال</option></select></label>
      <div className="filter-actions"><button type="submit">اعمال فیلترها</button><Link href="/fa/indicators">پاک‌کردن</Link></div>
    </form>
    <div className="catalog-summary" role="status"><strong>{data.total.toLocaleString("fa-IR")}</strong> شاخص مطابق فیلترها</div>
    {data.items.length ? <section className="indicator-list" aria-label="نتایج شاخص‌ها">{data.items.map(item => <article className={`indicator-row ${item.availability !== "available" ? "unavailable" : ""}`} key={item.series_code}>
      <div><div className="badge-row"><span className="metric-state">{categoryLabels[item.category ?? ""] ?? "سایر"}</span><span className="metric-state">{frequencyLabels[item.frequency ?? ""] ?? "نامشخص"}</span><span className="metric-state">{item.operational_is_active === true ? "فعال" : item.operational_is_active === false ? "غیرفعال" : "نامشخص"}</span></div><h2>{item.display_name_fa}</h2><p className="latin-name" dir="ltr">{item.original_name ?? item.series_code}</p><p>{item.description_fa}</p></div>
      <dl><dt>کد</dt><dd><code>{item.series_code}</code></dd><dt>جغرافیا</dt><dd>{item.geography ?? "—"}</dd><dt>واحد</dt><dd>{item.localized_unit_label ?? item.unit ?? "—"}</dd><dt>منبع</dt><dd>{item.source?.source_name ?? "—"}</dd><dt>بازبینی</dt><dd>{faDate(item.editorial_updated_at)}</dd></dl>
      <div className="indicator-row-action">{item.availability === "available" && item.series_id ? <Link href={`/fa/indicators/${item.series_id}`}>مشاهدهٔ پژوهش ←</Link> : <span>{stateLabels[item.availability]}</span>}</div>
    </article>)}</section> : <section className="state-card" role="status"><span className="state-symbol">۰</span><div><h2>شاخصی پیدا نشد</h2><p>فیلترها را تغییر دهید یا همهٔ فیلترها را پاک کنید.</p></div></section>}
    <nav className="catalog-pagination" aria-label="صفحه‌بندی"><Link aria-disabled={page <= 1} href={pageHref(query, Math.max(1,page-1))}>صفحهٔ قبل</Link><span>صفحه {page.toLocaleString("fa-IR")} از {pages.toLocaleString("fa-IR")}</span><Link aria-disabled={page >= pages} href={pageHref(query, Math.min(pages,page+1))}>صفحهٔ بعد</Link></nav>
  </div>;
}
