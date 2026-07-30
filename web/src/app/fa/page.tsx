import { DashboardRoute } from "@/components/dashboard/dashboard-route";

export const dynamic = "force-dynamic";

export default function PersianHomePage() {
  return (
    <DashboardRoute
      code="home"
      eyebrow="مرکز پژوهش اقتصاد کلان"
      title="شواهد روشن برای تصمیم‌های سنجیده"
      description="نمای خصوصی داده، منبع، تازگی و محاسبات ماندگاریافته؛ بدون سیگنال معاملاتی یا توصیه سرمایه‌گذاری"
    />
  );
}
