import Link from "next/link";

const pillars = [
  ["01","دادهٔ دقیق","مقادیر مالی و اقتصاد کلان در قراردادهای API به‌صورت Decimal رشته‌ای نگهداری و نمایش داده می‌شوند. تبدیل به Number فقط برای هندسهٔ نمودار مجاز است."],
  ["02","زمان دانش","زمان مشاهده با زمان در دسترس‌شدن اطلاعات یکی نیست. نماهای As-of فقط شواهدی را می‌بینند که تا Cutoff انتخاب‌شده شناخته شده بوده‌اند."],
  ["03","Revision","بازنگری داده، مقدار قبلی را از تاریخ حذف نمی‌کند. Observation و Revision جدا نگهداری می‌شوند تا مسیر تغییر داده قابل حسابرسی بماند."],
  ["04","No look-ahead","اجرای تاریخی Analytics ورودی را در همان Vintage قابل‌دسترس در Cutoff می‌خواند؛ داده یا بازنگری آینده نباید به گذشته نشت کند."],
  ["05","Missing ≠ Zero","نبود داده هرگز به صفر تبدیل نمی‌شود. Missingness و علت آن بخشی از شواهد خروجی است و در نمودار نیز شکاف باقی می‌ماند."],
  ["06","تحلیل نسخه‌دار","تعریف‌های Analytics نسخه‌دار و Runها ماندگارند. خروجی مشتق به Definition Version، Run و Lineage ورودی‌هایش متصل می‌ماند."],
] as const;

export default function MethodologyPage() {
  return <div className="page-stack methodology-page">
    <header className="indicator-hero"><div><p className="eyebrow">روش‌شناسی MacroVision</p><h1>عدد بدون زمان، منبع و روش شاهد کامل نیست</h1><p>این صفحه قرارداد پژوهشی محصول را توضیح می‌دهد: چه چیزی دقیق نگهداری می‌شود، نماهای تاریخی چگونه از اطلاعات آینده محافظت می‌شوند و تبدیل‌های تحلیلی چگونه قابل بازتولید باقی می‌مانند.</p></div><span className="preview-badge">Reviewed methodology</span></header>
    <section className="methodology-grid">{pillars.map(([n,title,body])=><article key={n}><span className="ltr">{n}</span><h2>{title}</h2><p>{body}</p></article>)}</section>
    <section className="methodology-flow" aria-labelledby="method-flow-title"><header><p className="eyebrow">زنجیرهٔ شواهد</p><h2 id="method-flow-title">از منبع تا خروجی پژوهش</h2></header><ol><li><strong>Source</strong><span>هویت منبع، مرجع و متادیتای سری ثبت می‌شود.</span></li><li><strong>Observation + Vintage</strong><span>مقدار، زمان مشاهده، زمان انتشار/ورود و بازنگری‌ها مستقل ثبت می‌شوند.</span></li><li><strong>Definition Version</strong><span>تبدیل فقط از مجموعهٔ محدود و ثبت‌شدهٔ Analytics با ورودی‌های مشخص ساخته می‌شود.</span></li><li><strong>Immutable Run</strong><span>بازه، Cutoff، نسخهٔ Engine و وضعیت Missingness همراه Run ثبت می‌شوند.</span></li><li><strong>Lineage</strong><span>هر خروجی قابل ردیابی به Observation/Revisionهای ورودی است.</span></li></ol></section>
    <section className="methodology-notes"><article><h2>مقایسهٔ چندسری</h2><p>صفحهٔ مقایسه سری‌ها را مستقل نگه می‌دارد. اختلاف تناوب و واحد صریح اعلام می‌شود و Reader هیچ Resampling، Fill، Interpolation، Ratio یا Spread ضمنی انجام نمی‌دهد.</p><Link href="/fa/compare">رفتن به مقایسه</Link></article><article><h2>پژوهش محاسباتی</h2><p>Ratio، Spread، تغییرات، Rolling statistics و Rebase فقط از Analytics نسخه‌دار اجرا می‌شوند. اجرای پژوهش یک Mutation صریح و سطح دسترسی‌دار است؛ GET صفحه Run جدید ایجاد نمی‌کند.</p><Link href="/fa/research">رفتن به پژوهش</Link></article></section>
    <section className="methodology-limitations"><h2>مرز تفسیر</h2><p>MacroVision کیفیت منبع بیرونی را تضمین نمی‌کند و خروجی آن توصیهٔ خرید یا فروش نیست. «Current»، «Stale»، «Missing» و «Incomparable» وضعیت‌های متفاوت‌اند و نباید به یکدیگر تبدیل شوند. تاریخ شمسی یا برچسب فارسی فقط لایهٔ نمایش است؛ زمان مرجع سیستم UTC باقی می‌ماند.</p></section>
  </div>;
}
