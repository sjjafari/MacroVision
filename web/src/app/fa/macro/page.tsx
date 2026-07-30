import { DashboardRoute } from "@/components/dashboard/dashboard-route";

export const dynamic = "force-dynamic";

export default function MacroPage() {
  return (
    <DashboardRoute
      code="macro"
      eyebrow="اقتصاد کلان"
      title="تصویر کلان اقتصاد"
      description="تورم، نرخ بهره، بازار کار، رشد و نقدینگی در گروه‌های قطعی و مرورشده"
    />
  );
}
