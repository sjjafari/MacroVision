import { EmptyState } from "@/components/states";
import { PageHeader } from "@/components/page-header";

type RoutePlaceholderProps = {
  eyebrow: string;
  title: string;
  description: string;
  phase: number;
  notice: string;
  privateOnly?: boolean;
};

export function RoutePlaceholder({
  eyebrow,
  title,
  description,
  phase,
  notice,
  privateOnly = false,
}: RoutePlaceholderProps) {
  return (
    <div className="page-stack">
      <PageHeader
        eyebrow={eyebrow}
        title={title}
        description={description}
        phase={phase}
        privateOnly={privateOnly}
      />
      <div className="placeholder-grid" aria-label="نمای خالی صفحه">
        <section className="chart-placeholder">
          <div className="chart-placeholder-header">
            <span>نمای داده</span>
            <span>در انتظار اتصال</span>
          </div>
          <div className="chart-lines" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
          </div>
          <p>{notice}</p>
        </section>
        <EmptyState
          title="داده هنوز بارگذاری نشده است"
          description="این پوسته در فاز نخست هیچ مقدار اقتصادی ساختگی نمایش نمی‌دهد."
        />
      </div>
    </div>
  );
}
