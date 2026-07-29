type StateProps = {
  title: string;
  description: string;
};

export function EmptyState({ title, description }: StateProps) {
  return (
    <section className="state-card" aria-labelledby="empty-state-title">
      <span className="state-symbol" aria-hidden="true">
        —
      </span>
      <div>
        <h2 id="empty-state-title">{title}</h2>
        <p>{description}</p>
      </div>
    </section>
  );
}

export function ErrorState({ title, description }: StateProps) {
  return (
    <section className="state-card state-card-error" role="alert">
      <span className="state-symbol" aria-hidden="true">
        !
      </span>
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
    </section>
  );
}

export function SkeletonState({ label = "در حال آماده‌سازی" }: { label?: string }) {
  return (
    <div className="skeleton-card" role="status" aria-label={label}>
      <span className="skeleton-line skeleton-line-short" />
      <span className="skeleton-line" />
      <span className="skeleton-line skeleton-line-medium" />
    </div>
  );
}
