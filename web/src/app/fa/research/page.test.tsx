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
  it("clearly marks the trusted-network mutation boundary", async () => {
    render(await ResearchPage({ searchParams: Promise.resolve({}) }));
    expect(screen.getByRole("alert")).toHaveTextContent("فقط شبکهٔ مورد اعتماد");
    expect(screen.getByRole("alert")).toHaveTextContent("Authentication");
    expect(screen.getByText("Analytics مستند و قابل بازتولید")).toBeInTheDocument();
  });
});
