import "@testing-library/jest-dom/vitest";
import { expect } from "vitest";
import { toHaveNoViolations } from "jest-axe";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

expect.extend(toHaveNoViolations);
afterEach(cleanup);
