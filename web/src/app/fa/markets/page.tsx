import { DashboardRoute } from "@/components/dashboard/dashboard-route";

export const dynamic = "force-dynamic";

export default function MarketsPage() {
  return (
    <DashboardRoute
      code="markets"
      eyebrow="بازارها"
      title="نبض بازار، بدون عدد ساختگی"
      description="ارز، کالا، انرژی و شرایط مالی از قراردادهای خواندنی و ماندگاریافته"
    />
  );
}
