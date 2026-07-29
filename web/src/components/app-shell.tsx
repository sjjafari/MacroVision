import Link from "next/link";
import type { ReactNode } from "react";

import { PrivatePreviewBadge } from "@/components/badges";
import { ThemeToggle } from "@/components/theme-toggle";
import { NAVIGATION_ROUTES } from "@/lib/routes";

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
        <ThemeToggle />
        <PrivatePreviewBadge />
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
          {NAVIGATION_ROUTES.map((route, index) => (
            <li key={route.href}>
              <Link href={route.href}>
                <span className="nav-index ltr" aria-hidden="true">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <span>{route.label}</span>
              </Link>
            </li>
          ))}
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
  const mobileRoutes = NAVIGATION_ROUTES.slice(0, 5);
  return (
    <nav className="mobile-navigation" aria-label="پیمایش موبایل">
      {mobileRoutes.map((route) => (
        <Link key={route.href} href={route.href}>
          <span aria-hidden="true">•</span>
          {route.shortLabel}
        </Link>
      ))}
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
        <span>MacroVision v0.8 — زیرساخت نمای وب</span>
        <span>داده و تحلیل از تفسیر جدا می‌مانند.</span>
      </footer>
      <MobileNavigation />
    </div>
  );
}
