import Link from "next/link";

export default function AboutPage() {
  return <div className="page-stack about-page">
    <header className="indicator-hero"><div><p className="eyebrow">درباره MacroVision</p><h1>زیرساخت شواهد برای تصمیم، نه موتور سیگنال</h1><p>MacroVision برای جمع‌کردن دادهٔ قابل حسابرسی، تحلیل نسخه‌دار و تاریخچهٔ تصمیم طراحی شده است تا فرضیه‌ها با شواهد سنجیده شوند؛ نه برای وعدهٔ پیش‌بینی قطعی یا اجرای معامله.</p></div><span className="preview-badge">v0.8 Web MVP</span></header>
    <section className="principles-grid">
      <article><span className="ltr">01</span><h2>حفظ سرمایه</h2><p>ریسک و شرایط ابطال باید قبل از دنبال‌کردن بازده دیده شوند؛ نقد نیز یک تخصیص معتبر است.</p></article>
      <article><span className="ltr">02</span><h2>احتمال، نه قطعیت</h2><p>فرضیه، شواهد موافق و مخالف، نقد مستقل، احتمال و Confidence از یکدیگر تفکیک می‌شوند.</p></article>
      <article><span className="ltr">03</span><h2>قابلیت بازتولید</h2><p>Vintage، Revision، Definition Version، Run و Lineage نگهداری می‌شوند تا معلوم باشد هر نتیجه با چه دانشی ساخته شده است.</p></article>
      <article><span className="ltr">04</span><h2>تفکیک داده و نمایش</h2><p>محاسبهٔ مالی در Backend انجام می‌شود؛ UI مقدار دقیق را نمایش می‌دهد و فقط هندسهٔ نمودار تقریبی است.</p></article>
    </section>
    <section className="about-scope"><div><p className="eyebrow">دامنهٔ v0.8</p><h2>آنچه این نسخه انجام می‌دهد</h2><ul><li>داشبوردهای فارسی اقتصاد و بازار با دادهٔ ماندگار</li><li>کاتالوگ شاخص، Revision و نمای تاریخی As-of</li><li>مقایسهٔ حداکثر چهار سری با semantics صریح</li><li>Analytics نسخه‌دار و پژوهش با Lineage</li><li>مرز امنیتی Production شامل Authentication ingress، RBAC، CSRF، Rate limiting و TLS topology</li></ul></div><div><p className="eyebrow">خارج از دامنه</p><h2>آنچه عمداً انجام نمی‌دهد</h2><ul><li>سیگنال خرید و فروش یا توصیهٔ خودکار سرمایه‌گذاری</li><li>اتصال به Broker و اجرای معامله</li><li>فرمول دلخواه در Browser</li><li>تبدیل Missing به صفر یا پرکردن پنهان شکاف‌ها</li><li>اجرای ضمنی Provider Sync یا Analytics هنگام GET</li></ul></div></section>
    <section className="about-security"><div><h2>وضعیت انتشار</h2><p>وجود Stack تولید به معنی انتشار خودکار اینترنتی نیست. استقرار واقعی فقط با Secrets اختصاصی، OAuth app معتبر، TLS certificate، PostgreSQL production، Backup/Restore آزموده‌شده و سیاست کاربران مجاز انجام می‌شود.</p></div><div className="about-links"><Link href="/fa/methodology">روش‌شناسی و قرارداد داده</Link><Link href="/fa/indicators">مرور شاخص‌ها</Link><Link href="/fa/research">فضای پژوهش</Link></div></section>
  </div>;
}
