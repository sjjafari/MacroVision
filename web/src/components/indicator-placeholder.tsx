import { RoutePlaceholder } from "@/components/route-placeholder";

export function IndicatorPlaceholder({ seriesId }: { seriesId: string }) {
  return (
    <div>
      <div className="series-code-row">
        <span>شناسه سری</span>
        <code className="ltr">{seriesId}</code>
      </div>
      <RoutePlaceholder
        eyebrow="جزئیات شاخص"
        title="مشاهده‌پذیری سری و تاریخچه"
        description="عنوان فارسی، داده جاری، حالت تاریخی، بازبینی‌ها، منبع و روش‌شناسی در فاز سوم متصل می‌شوند."
        phase={3}
        notice="برای این شناسه هنوز داده‌ای بارگذاری نشده است"
      />
    </div>
  );
}
