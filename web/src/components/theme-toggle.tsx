"use client";

import { useState } from "react";

export function ThemeToggle() {
  const [theme, setTheme] = useState<"system" | "light">("system");

  function toggleTheme() {
    const nextTheme = theme === "system" ? "light" : "system";
    setTheme(nextTheme);
    if (nextTheme === "light") {
      document.documentElement.dataset.theme = "light";
    } else {
      delete document.documentElement.dataset.theme;
    }
  }

  return (
    <button
      className="theme-toggle"
      type="button"
      onClick={toggleTheme}
      aria-pressed={theme === "light"}
      aria-label={theme === "light" ? "بازگشت به پوسته سیستم" : "نمایش پوسته روشن"}
    >
      <span aria-hidden="true">{theme === "light" ? "◐" : "○"}</span>
      <span>{theme === "light" ? "سیستم" : "روشن"}</span>
    </button>
  );
}
