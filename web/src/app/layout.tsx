import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "MacroVision | پیش‌نمایش خصوصی",
    template: "%s | MacroVision",
  },
  description:
    "پیش‌نمایش خصوصی رابط پژوهش اقتصاد کلان MacroVision؛ بدون سیگنال معاملاتی.",
  robots: {
    index: false,
    follow: false,
    nocache: true,
    googleBot: {
      index: false,
      follow: false,
      noimageindex: true,
    },
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fa" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
