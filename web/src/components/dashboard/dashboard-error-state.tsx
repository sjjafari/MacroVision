import { ErrorState } from "@/components/states";
import type { DashboardPageResult } from "@/lib/dashboard/types";

export function DashboardErrorState({
  code,
}: {
  code: Extract<DashboardPageResult, { status: "error" }>["code"];
}) {
  const notFound = code === "not_found" || code === "invalid_dashboard";
  return (
    <div className="page-stack">
      <h1>{notFound ? "داشبورد پیدا نشد" : "داشبورد موقتاً در دسترس نیست"}</h1>
      <ErrorState
        title={notFound ? "کد داشبورد معتبر نیست" : "ارتباط خواندنی برقرار نشد"}
        description={
          notFound
            ? "این داشبورد به مسیر دیگری جایگزین یا هدایت نشده است."
            : "اطلاعات فنی Backend پنهان مانده است؛ بعداً دوباره تلاش کنید."
        }
      />
    </div>
  );
}
