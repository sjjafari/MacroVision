import Link from "next/link";
import { createDefinitionAction, executeResearchAction } from "@/lib/research/actions";
import type { AnalyticsRunRead, DataSeriesRead, DerivedObservationLineagePage, DerivedObservationPage, DerivedSeriesPage, DerivedSeriesRead } from "@/lib/research/types";

const transformations=[
["difference","تفاضل دوره‌ای"],["percent_change","درصد تغییر"],["year_over_year_percent_change","درصد تغییر سالانه"],["ratio","نسبت"],["spread","اسپرد"],["moving_average","میانگین متحرک"],["rolling_standard_deviation","انحراف معیار متحرک"],["rolling_z_score","Z-Score متحرک"],["rebase_index","بازپایه‌گذاری شاخص"],
] as const;

export function ResearchWorkspace({series,definitions,selectedDefinition,run,observations,lineage,error,csrfToken}:{series:DataSeriesRead[];definitions:DerivedSeriesPage;selectedDefinition:DerivedSeriesRead|null;run:AnalyticsRunRead|null;observations:DerivedObservationPage|null;lineage:DerivedObservationLineagePage|null;error?:string;csrfToken?:string}) {
  return <div className="page-stack research-workspace">
    <header className="indicator-hero"><div><p className="eyebrow">آزمایشگاه پژوهش خصوصی</p><h1>Analytics مستند و قابل بازتولید</h1><p>تعریف تبدیل، اجرای محدود، خروجی دقیق و Lineage نقطه‌ای؛ بدون فرمول دلخواه و بدون اجرای پنهانی.</p></div><span className="preview-badge">Private / Mutation</span></header>
    <div className="private-warning" role="alert"><strong>فقط شبکهٔ مورد اعتماد</strong><p>این سطح Mutation تا تکمیل Authentication، RBAC، Session، CSRF و Rate Limit نباید عمومی شود.</p></div>
    {error&&<section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h2>عملیات انجام نشد</h2><p>{error}</p></div></section>}
    <section className="research-columns">
      <form action={createDefinitionAction} className="research-form"><input type="hidden" name="csrf" value={csrfToken??""} /><h2>۱. تعریف تحلیل</h2>
        <label>کد<input name="code" required pattern="[A-Za-z][A-Za-z0-9_.-]{0,119}" placeholder="RESEARCH.CPI.MA" /></label>
        <label>عنوان<input name="title" required maxLength={240} /></label>
        <label>توضیح<textarea name="description" maxLength={2000} /></label>
        <label>تبدیل<select name="transformation" required>{transformations.map(([v,l])=><option value={v} key={v}>{l}</option>)}</select></label>
        <label>سری منبع اول<select name="source_1" required><option value="">انتخاب</option>{series.map(s=><option value={s.id} key={s.id}>{s.code} — {s.name}</option>)}</select></label>
        <label>سری منبع دوم <small>فقط Ratio/Spread</small><select name="source_2"><option value="">—</option>{series.map(s=><option value={s.id} key={s.id}>{s.code} — {s.name}</option>)}</select></label>
        <label>Window <small>۲ تا ۱۰۰۰ برای Rolling</small><input name="window" type="number" min="2" max="1000" defaultValue="12" /></label>
        <label>تاریخ پایه Rebase<input name="base_date" type="date" /></label>
        <label>مقدار پایه Rebase<input name="base_value" inputMode="decimal" defaultValue="100.00000000" /></label>
        <button type="submit">ایجاد تعریف نسخه‌دار</button>
      </form>
      <form action={executeResearchAction} className="research-form"><input type="hidden" name="csrf" value={csrfToken??""} /><h2>۲. اجرای محدود</h2>
        <label>تعریف<select name="definition_id" required defaultValue={selectedDefinition?.id??""}><option value="">انتخاب</option>{definitions.items.map(d=><option value={d.id} key={d.id}>{d.code} — {d.title}</option>)}</select></label>
        <label>نسخه <small>خالی = آخرین نسخه</small><input name="definition_version" type="number" min="1" defaultValue={selectedDefinition?.current_version.version??""} /></label>
        <label>شروع<input name="start" type="date" required defaultValue="2025-01-01" /></label>
        <label>پایان<input name="end" type="date" required defaultValue="2026-12-31" /></label>
        <label>As-of اختیاری<input name="as_of" type="date" /></label>
        <button type="submit">اجرای Analytics</button>
        <p className="compare-rule">اجرای POST صریح است؛ GETهای صفحه هیچ Analytics جدیدی ایجاد نمی‌کنند.</p>
      </form>
    </section>
    <section className="evidence-section"><h2>تعریف‌های موجود</h2><div className="research-definition-list">{definitions.items.map(d=><Link key={d.id} className={selectedDefinition?.id===d.id?"active":""} href={`/fa/research?definition_id=${d.id}`}><strong>{d.title}</strong><code>{d.code}</code><span>نسخه {d.current_version.version.toLocaleString("fa-IR")} · {d.enabled?"فعال":"غیرفعال"}</span></Link>)}</div></section>
    {run&&<section className="snapshot-panel"><header><div><p className="eyebrow">Run #{run.id}</p><h2>نتیجهٔ اجرای Analytics</h2></div><span className="metric-state">{run.status}</span></header><div className="snapshot-grid"><dl><dt>Definition</dt><dd>{run.definition_id}</dd><dt>Version</dt><dd>{run.definition_version}</dd><dt>Cutoff</dt><dd dir="ltr">{run.calculation_cutoff}</dd><dt>ورودی بررسی‌شده</dt><dd>{run.inputs_examined.toLocaleString("fa-IR")}</dd></dl><dl><dt>خروجی موجود</dt><dd>{run.outputs_present.toLocaleString("fa-IR")}</dd><dt>خروجی مفقود</dt><dd>{run.outputs_missing.toLocaleString("fa-IR")}</dd><dt>Lineage links</dt><dd>{run.lineage_links.toLocaleString("fa-IR")}</dd><dt>Engine</dt><dd>{run.engine_version}</dd></dl></div></section>}
    {observations&&<section className="evidence-section"><h2>خروجی دقیق</h2><div className="table-scroll"><table><thead><tr><th>زمان</th><th>مقدار</th><th>وضعیت</th><th>علت Missing</th><th>Lineage</th></tr></thead><tbody>{observations.items.map(o=><tr key={o.id}><td dir="ltr">{o.observed_at}</td><td dir="ltr">{o.value??"—"}</td><td>{o.status}</td><td>{o.missing_reason??"—"}</td><td><Link href={`/fa/research?definition_id=${run?.definition_id??""}&run_id=${observations.run_id}&observation_id=${o.id}`}>شواهد</Link></td></tr>)}</tbody></table></div></section>}
    {lineage&&<section className="evidence-section"><h2>Lineage نقطهٔ انتخاب‌شده</h2>{lineage.items.length?<div className="related-grid">{lineage.items.map(item=><article key={item.id}><dl className="lineage"><dt>Alias</dt><dd>{item.input_alias}</dd><dt>Observation</dt><dd>{item.source_observation_id}</dd><dt>Revision</dt><dd>{item.source_revision_id??"original"}</dd><dt>Knowledge</dt><dd dir="ltr">{item.source_knowledge_timestamp}</dd></dl></article>)}</div>:<p className="empty-note">Lineage ثبت‌شده‌ای برای این نقطه وجود ندارد.</p>}</section>}
  </div>;
}
