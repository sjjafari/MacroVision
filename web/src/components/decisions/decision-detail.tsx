import Link from "next/link";
import { DECISION_STATUS_FA,decisionCompleteness,type DecisionCase,type DecisionRevision } from "@/lib/decisions/types";

const sourceFa:Record<string,string>={research_paper:"مقاله پژوهشی",financial_statement:"صورت مالی",market_data:"داده بازار",news:"خبر",expert_opinion:"نظر متخصص",internal_analysis:"تحلیل داخلی",other:"سایر"};
const eventFa:Record<string,string>={created:"ایجاد",review_started:"شروع بررسی",revised:"بازنگری",activated:"فعال‌سازی",invalidated:"ابطال",closed:"بستن"};
function when(value:string){return new Intl.DateTimeFormat("fa-IR",{dateStyle:"medium",timeStyle:"short",timeZone:"UTC"}).format(new Date(value));}

export function DecisionDetail({decision:d,history}:{decision:DecisionCase;history:DecisionRevision[]}) {
 const checks=decisionCompleteness(d);
 return <div className="page-stack decision-detail">
  <div className="breadcrumb-row"><Link href="/fa/decisions">پرونده‌های تصمیم</Link><span>/</span><span className="ltr">#{d.id}</span></div>
  <header className="indicator-hero"><div><p className="eyebrow">پرونده تصمیم · نسخه <span className="ltr">{d.current_version}</span></p><h1>{d.title}</h1><p>{d.question}</p></div><span className={"decision-status decision-status-"+d.status}>{DECISION_STATUS_FA[d.status]}</span></header>
  <section className="decision-summary-grid"><article><span>احتمال</span><strong className="ltr">{d.probability}</strong></article><article><span>اطمینان</span><strong className="ltr">{d.confidence}</strong></article><article><span>آخرین تغییر</span><strong className="ltr">{when(d.updated_at)}</strong></article></section>
  <section className="evidence-section"><header><p className="eyebrow">تز تصمیم</p><h2>منطق و زمینه</h2></header>{d.context&&<p>{d.context}</p>}<h3>منطق فعلی</h3><p>{d.rationale}</p><h3>فرضیه‌ها</h3>{d.hypotheses.length?d.hypotheses.map(h=><article className="evidence-item" key={h.id}><strong>{h.statement}</strong>{h.rationale&&<p>{h.rationale}</p>}</article>):<p className="muted">فرضیه‌ای ثبت نشده است.</p>}</section>
  <section className="decision-evidence-columns">
   <div className="evidence-section evidence-support"><header><p className="eyebrow">موافق</p><h2>شواهد پشتیبان</h2></header>{d.supporting_evidence.length?d.supporting_evidence.map(e=><article className="evidence-item" key={e.id}><strong>{e.source_title}</strong><p>{sourceFa[e.source_type]??e.source_type} · اعتبار <span className="ltr">{e.reliability_score}</span> · ارتباط <span className="ltr">{e.relevance_score}</span></p>{e.notes&&<p>{e.notes}</p>}</article>):<p className="muted">شاهد موافق ثبت نشده است.</p>}</div>
   <div className="evidence-section evidence-oppose"><header><p className="eyebrow">مخالف</p><h2>شواهد نقض‌کننده</h2></header>{d.opposing_evidence.length?d.opposing_evidence.map(e=><article className="evidence-item" key={e.id}><strong>{e.source_title}</strong><p>{sourceFa[e.source_type]??e.source_type} · اعتبار <span className="ltr">{e.reliability_score}</span> · ارتباط <span className="ltr">{e.relevance_score}</span></p>{e.notes&&<p>{e.notes}</p>}</article>):<p className="muted">شاهد مخالف ثبت نشده است.</p>}</div>
  </section>
  <section className="decision-evidence-columns">
   <div className="evidence-section"><header><p className="eyebrow">Critic</p><h2>نقد مستقل</h2></header>{d.critic_reviews.length?d.critic_reviews.map(r=><article className="evidence-item" key={r.id}><strong>{r.reviewer}</strong><p>{r.analysis}</p><h3>ریسک‌های کلیدی</h3><p>{r.key_risks}</p><h3>جمع‌بندی منتقد</h3><p>{r.recommendation}</p></article>):<p className="muted">نقد مستقلی ثبت نشده است.</p>}</div>
   <div className="evidence-section"><header><p className="eyebrow">ابطال‌پذیری</p><h2>شرایط ابطال</h2></header>{d.invalidation_rules.length?d.invalidation_rules.map(r=><article className="evidence-item" key={r.id}><strong>{r.condition}</strong><p>منبع مشاهده: {r.observation_source}</p>{r.notes&&<p>{r.notes}</p>}</article>):<p className="muted">شرط ابطالی ثبت نشده است.</p>}</div>
  </section>
  <section className="evidence-section"><header><p className="eyebrow">گیت فعال‌سازی</p><h2>کامل‌بودن پرونده</h2></header><div className="decision-completeness decision-completeness-large">{checks.map(x=><span key={x.key} className={x.complete?"complete":undefined}>{x.complete?"✓":"○"} {x.label}</span>)}</div><p className="muted">این نمایش فقط آینهٔ قواعد فعلی Backend است؛ تصمیم نهایی برای فعال‌سازی همیشه با Backend است.</p></section>
  <section className="evidence-section"><header><p className="eyebrow">Audit trail</p><h2>تاریخچه تغییرناپذیر</h2></header><ol className="decision-timeline">{history.map(h=><li key={h.id}><div><strong>نسخه <span className="ltr">{h.version}</span> · {eventFa[h.event]??h.event}</strong><span className="ltr">{when(h.created_at)}</span></div><p>{h.change_summary}</p><small>احتمال <span className="ltr">{h.probability}</span> · اطمینان <span className="ltr">{h.confidence}</span> · {DECISION_STATUS_FA[h.status]}</small></li>)}</ol></section>
  {d.outcome&&<section className="evidence-section decision-outcome"><header><p className="eyebrow">Outcome</p><h2>نتیجه و درس‌آموخته</h2></header><p>{d.outcome.outcome}</p><h3>درس‌آموخته</h3><p>{d.outcome.lessons_learned}</p><p>ارزیابی دقت: <span className="ltr">{d.outcome.accuracy_assessment}</span></p></section>}
 </div>;
}
