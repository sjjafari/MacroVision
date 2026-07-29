import { RoutePlaceholder } from "@/components/route-placeholder";

export default function ResearchPage() {
  return (
    <div className="private-route">
      <div className="private-warning" role="alert">
        <strong>فضای خصوصی و غیرفعال</strong>
        <p>
          احراز هویت هنوز وجود ندارد؛ اجرای تحلیل و هرگونه عملیات تغییردهنده در این
          پیش‌نمایش مسدود است.
        </p>
      </div>
      <RoutePlaceholder
        eyebrow="فضای پژوهش"
        title="آزمایشگاه تحلیل مستند"
        description="اجرای تبدیل‌های تحلیلی، مشاهده خروجی و تبار داده تنها پس از تکمیل مرزهای امنیتی در محیط خصوصی ارائه می‌شود."
        phase={5}
        privateOnly
        notice="اجرای پژوهش در فاز نخست مجاز نیست"
      />
    </div>
  );
}
