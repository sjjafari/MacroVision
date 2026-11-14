import Link from "next/link";
import type { ReactNode } from "react";

import { NavigationLinks } from "@/components/navigation";
import { ThemeToggle } from "@/components/theme-toggle";

export function GlobalHeader() {
  return (
    <header className="global-header">
      <Link className="brand" href="/fa" aria-label="MacroVision، نمای اصلی">
        <span className="brand-mark" aria-hidden="true">
          M
        </span>
        <span>
          <strong>MacroVision</strong>
          <small>دید کلان، تصمیم مستند</small>
        </span>
      </Link>
      <div className="header-actions">
        <span className="release-badge ltr">v0.8.0</span>
        <ThemeToggle />
      </div>
    </header>
  );
}

export function Sidebar() {
  return (
    <aside className="sidebar" aria-label="پیمایش اصلی">
      <nav>
        <p className="nav-heading">فضای پژوهش</p>
        <ul>
          <NavigationLinks />
        </ul>
      </nav>
      <div className="sidebar-note">
        <strong>سرمایه‌گذاری آگاهانه</strong>
        <p>این محصول سیگنال خرید یا فروش ارائه نمی‌کند.</p>
      </div>
    </aside>
  );
}

export function MobileNavigation() {
  return (
    <nav className="mobile-navigation" aria-label="پیمایش موبایل">
      <NavigationLinks mobile />
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        پرش به محتوای اصلی
      </a>
      <GlobalHeader />
      <Sidebar />
      <main id="main-content" tabIndex={-1} className="main-content">
        {children}
      </main>
      <footer className="site-footer">
        <span>MacroVision v0.8 — پلتفرم پژوهش اقتصاد کلان</span>
        <span>داده و تحلیل از تفسیر جدا می‌مانند.</span>
      </footer>
      <MobileNavigation />
    </div>
  );
}
