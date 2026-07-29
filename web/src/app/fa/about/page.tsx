import { PageHeader } from "@/components/page-header";

export default function AboutPage() {
  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="درباره MacroVision"
        title="هوش تصمیم‌گیری سرمایه‌گذاری"
        description="MacroVision برای صورت‌بندی فرضیه، سنجش شواهد و حفظ تاریخچه تصمیم ساخته می‌شود؛ نه برای تولید سیگنال قطعی."
        phase={2}
      />
      <section className="principles-grid">
        <article>
          <span className="ltr">01</span>
          <h2>حفظ سرمایه</h2>
          <p>حفظ سرمایه پیش از بازده قرار می‌گیرد و نقد یک تخصیص معتبر است.</p>
        </article>
        <article>
          <span className="ltr">02</span>
          <h2>احتمال، نه قطعیت</h2>
          <p>تصمیم‌ها با احتمال و اعتماد مستند می‌شوند، نه ادعای پیش‌بینی قطعی.</p>
        </article>
        <article>
          <span className="ltr">03</span>
          <h2>شواهد قابل حسابرسی</h2>
          <p>یادگیری تنها از دفتر پژوهش و تاریخچه مستند داده و تحلیل انجام می‌شود.</p>
        </article>
      </section>
    </div>
  );
}
