import { DataFreshnessBadge, SourceBadge } from "@/components/badges";
import { PageHeader } from "@/components/page-header";

const placeholders = [
  {
    label: "چشم‌انداز تورم",
    text: "داده هنوز بارگذاری نشده است",
    detail: "منبع پس از اتصال رابط داده نمایش داده می‌شود",
  },
  {
    label: "شرایط پولی",
    text: "آخرین به‌روزرسانی موجود نیست",
    detail: "مبنای مقایسه توسط سامانه پشتیبان تعیین می‌شود",
  },
  {
    label: "ریسک بازار",
    text: "داده هنوز بارگذاری نشده است",
    detail: "هیچ مقدار صفر جایگزین داده گمشده نمی‌شود",
  },
];

export default function PersianHomePage() {
  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="مرکز پژوهش اقتصاد کلان"
        title="شواهد روشن برای تصمیم‌های سنجیده"
        description="پوسته نخست MacroVision برای مشاهده داده، منبع، تازگی و روش‌شناسی؛ بدون سیگنال معاملاتی یا توصیه سرمایه‌گذاری."
        phase={2}
      />

      <section className="metric-grid" aria-label="نمونه کارت‌های وضعیت">
        {placeholders.map((item, index) => (
          <article className="metric-card" key={item.label}>
            <div className="metric-card-top">
              <span className="metric-number ltr">{String(index + 1).padStart(2, "0")}</span>
              <DataFreshnessBadge>بدون داده</DataFreshnessBadge>
            </div>
            <h2>{item.label}</h2>
            <strong className="unavailable-value">—</strong>
            <p>{item.text}</p>
            <small>{item.detail}</small>
          </article>
        ))}
      </section>

      <section className="home-panel-grid">
        <article className="featured-panel">
          <div>
            <p className="eyebrow">نمودار منتخب</p>
            <h2>روندها پس از اتصال قرارداد داده نمایش داده می‌شوند</h2>
          </div>
          <div className="chart-canvas" aria-label="جایگاه خالی نمودار">
            <span className="chart-axis chart-axis-x" />
            <span className="chart-axis chart-axis-y" />
            <p>داده‌ای برای نمایش وجود ندارد</p>
          </div>
        </article>
        <aside className="evidence-panel">
          <p className="eyebrow">شفافیت داده</p>
          <h2>هر عدد باید قابل پیگیری باشد</h2>
          <ul>
            <li>هویت نقطه و سری</li>
            <li>زمان مشاهده و برش دانشی</li>
            <li>واحد، تناوب و مبنای مقایسه</li>
            <li>منبع و نسخه اجرای تحلیل</li>
          </ul>
          <div className="badge-row">
            <SourceBadge>منبع: متصل نیست</SourceBadge>
            <DataFreshnessBadge>تازگی: نامشخص</DataFreshnessBadge>
          </div>
        </aside>
      </section>
    </div>
  );
}
