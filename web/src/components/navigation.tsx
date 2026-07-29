"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Fragment } from "react";

import { NAVIGATION_ROUTES } from "@/lib/routes";

export function isNavigationRouteActive(currentPath: string, routePath: string): boolean {
  if (routePath === "/fa") {
    return currentPath === routePath;
  }
  if (routePath === "/fa/indicators") {
    return currentPath === routePath || currentPath.startsWith(`${routePath}/`);
  }
  return currentPath === routePath;
}

export function NavigationLinks({ mobile = false }: { mobile?: boolean }) {
  const currentPath = usePathname();

  return NAVIGATION_ROUTES.map((route, index) => {
    const active = isNavigationRouteActive(currentPath, route.href);
    const link = (
      <Link
        className={active ? "navigation-link-active" : undefined}
        href={route.href}
        aria-current={active ? "page" : undefined}
        key={route.href}
      >
        <span className={mobile ? "mobile-nav-marker" : "nav-index ltr"} aria-hidden="true">
          {mobile ? "•" : String(index + 1).padStart(2, "0")}
        </span>
        <span>{mobile ? route.shortLabel : route.label}</span>
      </Link>
    );
    return mobile ? <Fragment key={route.href}>{link}</Fragment> : <li key={route.href}>{link}</li>;
  });
}
