type BadgeProps = {
  children: React.ReactNode;
};

export function PrivatePreviewBadge() {
  return (
    <span className="preview-badge" role="status">
      <span aria-hidden="true" className="status-dot" />
      پیش‌نمایش خصوصی
    </span>
  );
}

export function DataFreshnessBadge({ children }: BadgeProps) {
  return <span className="freshness-badge">{children}</span>;
}

export function SourceBadge({ children }: BadgeProps) {
  return <span className="source-badge">{children}</span>;
}
