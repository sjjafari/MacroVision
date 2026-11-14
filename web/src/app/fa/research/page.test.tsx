import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/research/loader", () => ({
  loadResearch: vi.fn(async () => ({
    status: "ready",
    series: [],
    definitions: { items: [], limit: 100, offset: 0 },
    selectedDefinition: null,
    run: null,
    observations: null,
    lineage: null,
  })),
}));

import ResearchPage from "@/app/fa/research/page";

describe("private research route", () => {
  it("clearly marks the authenticated research mutation boundary", async () => {
    render(await ResearchPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByRole("note")).toHaveTextContent("دسترسی پژوهشی کنترل‌شده");
    expect(screen.getByRole("note")).toHaveTextContent("احراز هویت");
    expect(screen.getByText("Analytics مستند و قابل بازتولید")).toBeInTheDocument();
  });
});
