import type { ComparisonRead, DerivedSeriesPage, IndicatorCatalogPage } from "@/lib/compare/types";
import { ComparisonChart } from "./comparison-chart";

const frequency: Record<string,string> = {daily:"روزانه",weekly:"هفتگی",monthly:"ماهانه",quarterly:"فصلی",annual:"سالانه",irregular:"نامنظم"};

export function ComparePageView({catalog,definitions,comparison,query}:{catalog:IndicatorCatalogPage;definitions:DerivedSeriesPage;comparison:ComparisonRead|null;query:{items:string[];start:string;end:string;asOf?:string}|null}) {
  const selected=new Set(query?.items ?? []);
  return <div className="page-stack compare-page">
    <header className="indicator-hero"><div><p className="eyebrow">آزمایشگاه مقایسه</p><h1>مقایسهٔ شفاف سری‌های اقتصادی</h1><p>حداکثر چهار سری خام یا مشتق را بدون تبدیل ضمنی تناوب، interpolation یا محاسبهٔ مرورگر کنار هم ببینید.</p></div><span className="preview-badge">پژوهش خصوصی</span></header>
    <form className="compare-builder" method="get">
      <fieldset><legend>سری‌های خام بازبینی‌شده</legend><div className="compare-options">{catalog.items.filter(x=>x.availability==="available"&&x.series_id).map(item=><label key={item.series_code}><input type="checkbox" name="items" value={`raw:${item.series_id}`} defaultChecked={selected.has(`raw:${item.series_id}`)} /><span><strong>{item.display_name_fa}</strong><small dir="ltr">{item.series_code}</small></span></label>)}</div></fieldset>
      <fieldset><legend>سری‌های مشتق ذخیره‌شده</legend><div className="compare-options">{definitions.items.map(item=><label key={item.id}><input type="checkbox" name="items" value={`derived:${item.id}`} defaultChecked={selected.has(`derived:${item.id}`)} /><span><strong>{item.title}</strong><small dir="ltr">{item.code}</small></span></label>)}</div></fieldset>
      <div className="compare-dates"><label>از تاریخ<input type="date" name="start" required defaultValue={query?.start.slice(0,10) ?? "2016-01-01"} /></label><label>تا تاریخ<input type="date" name="end" required defaultValue={query?.end.slice(0,10) ?? "2026-12-31"} /></label><label>برش تاریخی اختیاری<input type="date" name="as_of" defaultValue={query?.asOf?.slice(0,10) ?? ""} /></label><button type="submit">اجرای مقایسه</button></div>
      <p className="compare-rule">انتخاب باید بین ۱ تا ۴ سری باشد. Ratio، Spread و سایر تبدیل‌ها فقط از Analytics ذخیره‌شده خوانده می‌شوند.</p>
    </form>
    {!comparison ? <section className="state-card"><span className="state-symbol">۴</span><div><h2>سری‌ها را انتخاب کنید</h2><p>پس از انتخاب، قرارداد چندسری Backend داده‌ها را به‌صورت مستقل و قابل حسابرسی برمی‌گرداند.</p></div></section> : <>
      <section className={comparison.mode==="historical_as_of"?"historical-cutoff":"catalog-summary"}><strong>{comparison.mode==="historical_as_of"?"نمای تاریخی دانش":"نمای جاری"}</strong>{comparison.requested_as_of&&<span dir="ltr">{comparison.requested_as_of}</span>}</section>
      {comparison.warnings.length>0&&<section className="compare-warnings" role="status">{comparison.frequency_mismatch&&<p><strong>هشدار اختلاف تناوب:</strong> سری‌ها هم‌دوره نیستند و هیچ resampling انجام نشده است.</p>}{comparison.axis_count>1&&<p><strong>چند محور:</strong> واحدهای متفاوت روی محورهای مستقل و برچسب‌دار نمایش داده می‌شوند.</p>}</section>}
      <ComparisonChart data={comparison} />
      <section className="compare-series-grid">{comparison.series.map(series=><article key={`${series.kind}:${series.resource_id}`}><header><div><h2>{series.title}</h2><code>{series.code}</code></div><span>{frequency[series.frequency]??series.frequency}</span></header><dl><dt>نوع</dt><dd>{series.kind==="raw"?"خام":"مشتق"}</dd><dt>واحد</dt><dd>{series.unit}</dd><dt>جغرافیا</dt><dd>{series.geography}</dd><dt>محور</dt><dd>{series.axis_id}</dd>{series.run_id&&<><dt>Run</dt><dd dir="ltr">{series.run_id}</dd></>}</dl><details className="chart-table"><summary>داده‌های دقیق ({series.points.length.toLocaleString("fa-IR")})</summary><div className="chart-table-scroll"><table><thead><tr><th>زمان</th><th>مقدار دقیق</th><th>وضعیت</th></tr></thead><tbody>{series.points.map((point,index)=><tr key={`${point.observed_at}:${index}`}><td dir="ltr">{point.observed_at}</td><td dir="ltr">{point.value??"—"}</td><td>{point.status==="present"?"موجود":"مفقود"}</td></tr>)}</tbody></table></div></details></article>)}</section>
    </>}
  </div>;
}
