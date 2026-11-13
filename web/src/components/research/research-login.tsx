export function ResearchLogin({invalid=false}:{invalid?:boolean}) {
  return <div className="page-stack"><header className="indicator-hero"><div><p className="eyebrow">دسترسی کنترل‌شده</p><h1>ورود به آزمایشگاه پژوهش</h1><p>Mutation و داده‌های عملیاتی پژوهش فقط برای نقش مجاز در دسترس است.</p></div><span className="preview-badge">RBAC</span></header>
    {invalid&&<section className="state-card state-card-error" role="alert"><span className="state-symbol">!</span><div><h2>ورود ناموفق</h2><p>نام کاربری یا گذرواژه معتبر نیست.</p></div></section>}
    <form action="/api/web/session" method="post" className="research-form auth-form"><input type="hidden" name="action" value="login" /><label>نام کاربری<input name="username" autoComplete="username" required maxLength={120} /></label><label>گذرواژه<input name="password" type="password" autoComplete="current-password" required maxLength={512} /></label><button type="submit">ورود امن</button><p className="compare-rule">نشست با Cookie امن، HttpOnly و SameSite=Strict صادر می‌شود.</p></form>
  </div>;
}
