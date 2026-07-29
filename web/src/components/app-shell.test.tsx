import { render, screen } from "@testing-library/react";
import { axe } from "jest-axe";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/app-shell";

const pathname = vi.hoisted(() => ({ value: "/fa" }));
vi.mock("next/navigation", () => ({
  usePathname: () => pathname.value,
}));

describe("AppShell", () => {
  beforeEach(() => {
    pathname.value = "/fa";
  });

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

  it("exposes every destination in desktop and mobile navigation", () => {
    render(<AppShell>محتوا</AppShell>);

    const navigationLinks = screen.getAllByRole("link").filter((link) => {
      const href = link.getAttribute("href");
      return href?.startsWith("/fa");
    });
    expect(navigationLinks).toHaveLength(17);
    for (const href of [
      "/fa",
      "/fa/markets",
      "/fa/macro",
      "/fa/indicators",
      "/fa/compare",
      "/fa/research",
      "/fa/methodology",
      "/fa/about",
    ]) {
      expect(navigationLinks.filter((link) => link.getAttribute("href") === href)).toHaveLength(
        href === "/fa" ? 3 : 2,
      );
    }
  });

  it.each([
    ["/fa", "/fa"],
    ["/fa/markets", "/fa/markets"],
    ["/fa/indicators", "/fa/indicators"],
    ["/fa/indicators/DEMO.SERIES", "/fa/indicators"],
  ])("marks %s active in desktop and mobile navigation", (currentPath, activeHref) => {
    pathname.value = currentPath;
    render(<AppShell>محتوا</AppShell>);

    const activeLinks = screen
      .getAllByRole("link")
      .filter((link) => link.getAttribute("aria-current") === "page");
    expect(activeLinks).toHaveLength(2);
    expect(activeLinks.every((link) => link.getAttribute("href") === activeHref)).toBe(true);
    expect(activeLinks.every((link) => link.classList.contains("navigation-link-active"))).toBe(true);
  });

  it("does not keep home active on nested or unknown routes", () => {
    pathname.value = "/fa/unknown";
    render(<AppShell>محتوا</AppShell>);

    expect(
      screen
        .getAllByRole("link")
        .filter((link) => link.getAttribute("aria-current") === "page"),
    ).toHaveLength(0);
  });
});
