import { DashboardErrorState } from "@/components/dashboard/dashboard-error-state";
import { DashboardPage } from "@/components/dashboard/dashboard-page";
import { loadDashboardPage } from "@/lib/dashboard/loader";
import type { DashboardCode } from "@/lib/dashboard/types";

export async function DashboardRoute({
  code,
  eyebrow,
  title,
  description,
}: {
  code: DashboardCode;
  eyebrow: string;
  title: string;
  description: string;
}) {
  const result = await loadDashboardPage(code);
  if (result.status === "error") return <DashboardErrorState code={result.code} />;
  return (
    <DashboardPage
      data={result.data}
      eyebrow={eyebrow}
      title={title}
      description={description}
    />
  );
}
