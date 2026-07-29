import { RoutePlaceholder } from "@/components/route-placeholder";

export default function IndicatorsPage() {
  return (
    <RoutePlaceholder
      eyebrow="فهرست شاخص‌ها"
      title="کاتالوگ شاخص‌های قابل انتشار"
      description="فعال بودن یک سری به‌معنای مجوز انتشار نیست؛ این فهرست پس از تکمیل لایه گزینش عمومی فعال می‌شود."
      phase={3}
      notice="کاتالوگ عمومی هنوز تأیید نشده است"
    />
  );
}
