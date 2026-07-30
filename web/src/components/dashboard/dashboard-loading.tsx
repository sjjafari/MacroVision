import { SkeletonState } from "@/components/states";

export function DashboardLoading() {
  return (
    <div className="page-stack" aria-label="در حال بارگذاری داشبورد">
      <SkeletonState label="در حال بارگذاری سربرگ داشبورد" />
      <section className="dashboard-metric-grid" aria-label="در حال بارگذاری شاخص‌ها">
        <SkeletonState />
        <SkeletonState />
        <SkeletonState />
      </section>
      <SkeletonState label="در حال بارگذاری نمودار" />
    </div>
  );
}
