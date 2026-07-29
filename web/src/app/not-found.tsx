import Link from "next/link";

export default function NotFound() {
  return (
    <main className="standalone-state" dir="rtl">
      <p className="eyebrow">خطای ۴۰۴</p>
      <h1>این صفحه پیدا نشد</h1>
      <p>نشانی واردشده در فهرست مسیرهای تأییدشده MacroVision نیست.</p>
      <Link className="primary-link" href="/fa">
        بازگشت به نمای اصلی
      </Link>
    </main>
  );
}
