import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { describe, expect, it } from "vitest";

import { AppShell } from "@/components/app-shell";

describe("AppShell", () => {
  it("provides Persian navigation and semantic landmarks", () => {
    render(
      <AppShell>
        <h1>محتوای آزمون</h1>
      </AppShell>,
    );

    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveAttribute("id", "main-content");
    expect(screen.getByRole("contentinfo")).toBeInTheDocument();
    expect(screen.getAllByRole("navigation").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("link", { name: "پرش به محتوای اصلی" })).toHaveAttribute(
      "href",
      "#main-content",
    );
    expect(screen.getAllByText("اقتصاد کلان").length).toBeGreaterThan(0);
  });

  it("has no detectable accessibility violations", async () => {
    const { container } = render(
      <AppShell>
        <h1>محتوای آزمون</h1>
      </AppShell>,
    );

    expect(await axe(container)).toHaveNoViolations();
  });
});
