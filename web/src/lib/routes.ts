export type WebRoute = {
  href: string;
  label: string;
  shortLabel: string;
  phase: number;
  navigation: boolean;
};

export const WEB_ROUTES = [
  { href: "/fa", label: "نمای اصلی", shortLabel: "خانه", phase: 2, navigation: true },
  { href: "/fa/markets", label: "بازارها", shortLabel: "بازار", phase: 2, navigation: true },
  { href: "/fa/macro", label: "اقتصاد کلان", shortLabel: "کلان", phase: 2, navigation: true },
  {
    href: "/fa/indicators",
    label: "شاخص‌ها",
    shortLabel: "شاخص",
    phase: 3,
    navigation: true,
  },
  {
    href: "/fa/indicators/[seriesId]",
    label: "جزئیات شاخص",
    shortLabel: "جزئیات",
    phase: 3,
    navigation: false,
  },
  { href: "/fa/compare", label: "مقایسه", shortLabel: "مقایسه", phase: 4, navigation: true },
  {
    href: "/fa/research",
    label: "فضای پژوهش",
    shortLabel: "پژوهش",
    phase: 5,
    navigation: true,
  },
  {
    href: "/fa/methodology",
    label: "روش‌شناسی",
    shortLabel: "روش",
    phase: 3,
    navigation: true,
  },
  { href: "/fa/about", label: "درباره", shortLabel: "درباره", phase: 2, navigation: true },
] as const satisfies readonly WebRoute[];

export const NAVIGATION_ROUTES = WEB_ROUTES.filter((route) => route.navigation);
