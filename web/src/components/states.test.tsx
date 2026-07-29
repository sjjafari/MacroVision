import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EmptyState, ErrorState, SkeletonState } from "@/components/states";

describe("shared states", () => {
  it("renders an explicit empty state", () => {
    render(<EmptyState title="داده موجود نیست" description="مقداری جایگزین نمی‌شود." />);
    expect(screen.getByRole("heading", { name: "داده موجود نیست" })).toBeInTheDocument();
    expect(screen.getByText("مقداری جایگزین نمی‌شود.")).toBeInTheDocument();
  });

  it("renders an announced error state", () => {
    render(<ErrorState title="خطا" description="دوباره تلاش کنید." />);
    expect(screen.getByRole("alert")).toHaveTextContent("دوباره تلاش کنید.");
  });

  it("renders a labeled skeleton state", () => {
    render(<SkeletonState label="در حال دریافت" />);
    expect(screen.getByRole("status", { name: "در حال دریافت" })).toBeInTheDocument();
  });
});
