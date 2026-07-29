import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { IndicatorPlaceholder } from "@/components/indicator-placeholder";

describe("indicator placeholder", () => {
  it("renders the supplied series identifier as an isolated LTR code", () => {
    render(<IndicatorPlaceholder seriesId="DEMO.SERIES" />);
    const code = screen.getByText("DEMO.SERIES");
    expect(code.tagName).toBe("CODE");
    expect(code).toHaveClass("ltr");
  });
});
