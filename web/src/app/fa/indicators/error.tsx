"use client";
export default function ErrorState({ reset }: { reset(): void }) { return <section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h1>کاتالوگ موقتاً در دسترس نیست</h1><p>جزئیات فنی نمایش داده نمی‌شود. کمی بعد دوباره تلاش کنید.</p><button onClick={reset}>تلاش دوباره</button></div></section>; }
