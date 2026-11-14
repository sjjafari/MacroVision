import Link from "next/link";
import { DECISION_STATUS_FA,decisionCompleteness,type DecisionCase } from "@/lib/decisions/types";

export function DecisionIndex({decisions}:{decisions:DecisionCase[]}) {
  return <div className="page-stack decision-page">
    <header className="indicator-hero"><div><p className="eyebrow">Decision Intelligence · v0.9</p><h1>پرونده‌های تصمیم</h1><p>فرضیه، شواهد موافق و مخالف، نقد مستقل و شرایط ابطال را پیش از فعال‌کردن یک تصمیم کنار هم ببینید.</p></div><span className="preview-badge">محافظت‌شده</span></header>
    {decisions.length===0?<section className="state-card"><span className="state-symbol">○</span><div><h2>هنوز پرونده‌ای ثبت نشده است</h2><p>این Reader فقط پرونده‌های ماندگار Decision Engine را نمایش می‌دهد و هنگام بازشدن چیزی ایجاد نمی‌کند.</p></div></section>:
    <section className="decision-list" aria-label="فهرست پرونده‌های تصمیم">{decisions.map(d=>{
      const checks=decisionCompleteness(d),done=checks.filter(x=>x.complete).length;
      return <article className="decision-card" key={d.id}>
        <header><div><span className={"decision-status decision-status-"+d.status}>{DECISION_STATUS_FA[d.status]}</span><h2>{d.title}</h2><p>{d.question}</p></div><span className="ltr decision-version">v{d.current_version}</span></header>
        <dl className="decision-score-grid"><div><dt>احتمال</dt><dd className="ltr">{d.probability}</dd></div><div><dt>اطمینان</dt><dd className="ltr">{d.confidence}</dd></div><div><dt>شواهد موافق</dt><dd className="ltr">{d.supporting_evidence.length}</dd></div><div><dt>شواهد مخالف</dt><dd className="ltr">{d.opposing_evidence.length}</dd></div></dl>
        <div className="decision-completeness" aria-label={"تکمیل "+done+" از ۵"}>{checks.map(x=><span key={x.key} className={x.complete?"complete":undefined}>{x.complete?"✓":"○"} {x.label}</span>)}</div>
        <Link className="primary-link" href={"/fa/decisions/"+d.id}>مشاهده پرونده</Link>
      </article>;
    })}</section>}
  </div>;
}
