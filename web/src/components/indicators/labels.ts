export const categoryLabels: Record<string, string> = { inflation: "تورم", employment: "بازار کار", growth: "رشد اقتصادی", interest_rate: "نرخ بهره", currency: "ارز", commodity: "کالا", equity_index: "شاخص سهام", volatility: "نوسان", liquidity: "نقدینگی", custom: "سفارشی" };
export const frequencyLabels: Record<string, string> = { daily: "روزانه", weekly: "هفتگی", monthly: "ماهانه", quarterly: "فصلی", annual: "سالانه", irregular: "نامنظم" };
export const stateLabels: Record<string, string> = { available: "در دسترس", stale: "نیازمند به‌روزرسانی", missing: "داده موجود نیست", configured_series_missing: "سری هنوز متصل نشده", definition_missing: "تعریف تحلیلی موجود نیست", persisted_result_missing: "نتیجهٔ محاسبه‌شده موجود نیست", definition_disabled: "تعریف غیرفعال است" };
export const reasonLabels: Record<string, string> = {
  definition_source_mismatch: "منبع نتیجه با شاخص بازبینی‌شده یکسان نیست.",
  persisted_result_missing: "نتیجهٔ ماندگار برای این رابطه موجود نیست.",
  definition_missing: "تعریف تحلیلی این رابطه موجود نیست.",
  definition_disabled: "تعریف تحلیلی این رابطه غیرفعال است.",
};
export function relatedReasonLabel(reason: string | null) { return reason ? reasonLabels[reason] ?? "دلیل در دسترس نبودن نتیجه به‌صورت امن ثبت شده است." : "نتیجه‌ای برای نمایش موجود نیست."; }
export const seasonalLabels: Record<string, string> = { seasonally_adjusted: "تعدیل‌شده فصلی", not_seasonally_adjusted: "تعدیل‌نشده فصلی", not_applicable: "نامرتبط", unknown: "نامشخص" };
export function faDate(value: string | null) { return value ? new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }).format(new Date(value)) : "—"; }
export function safeExternalUrl(value: string | null) { if (!value) return null; try { const url = new URL(value); return url.protocol === "https:" ? url.toString() : null; } catch { return null; } }
