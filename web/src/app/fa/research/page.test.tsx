import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ResearchPage from "@/app/fa/research/page";

describe("private research route", () => {
  it("clearly marks the unavailable unauthenticated surface", () => {
    render(<ResearchPage />);
    expect(screen.getByRole("alert")).toHaveTextContent("فضای خصوصی و غیرفعال");
    expect(screen.getByRole("alert")).toHaveTextContent("احراز هویت هنوز وجود ندارد");
  });
});
