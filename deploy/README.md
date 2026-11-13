# MacroVision Stage B production security

This stack is the supported production boundary for v0.8. Do not publish the
FastAPI or Next.js containers directly.

## Boundary

- NGINX is the only Internet-facing container and terminates TLS.
- OAuth2 Proxy uses GitHub OAuth and Redis-backed encrypted sessions.
- OAuth2 Proxy owns login/session and OAuth CSRF cookies.
- NGINX uses `auth_request`, overwrites identity headers, injects a private
  `X-MacroVision-Proxy-Secret`, and applies IP rate limits.
- Next.js independently verifies the trusted ingress secret and maps GitHub
  usernames to reader/research/operator roles.
- Research Server Actions re-check the research role at the mutation/data
  boundary; Proxy is only an optimistic outer check.
- The same-origin `/api/v1/*` proxy requires reader auth for GET/HEAD and
  research auth for mutation methods in production mode.
- FastAPI and PostgreSQL are reachable only on the internal Docker network.

## Publication status

Stage B deliberately keeps data-bearing Persian routes authenticated. Only
`/fa/about` and `/fa/methodology` may be served without application data
authorization. `reviewed_private` is not publication eligibility. A future
public reader surface must consume an explicit public-eligibility contract;
do not bypass this gate by exposing current dashboard or indicator APIs.

## Required secrets

Copy `deploy/.env.production.example` outside the repository and populate it.
Secrets must come from a deployment secret manager or protected host file and
must never be committed.

`MACROVISION_TRUSTED_PROXY_SECRET` must contain at least 32 random bytes.
`OAUTH2_PROXY_COOKIE_SECRET` must satisfy OAuth2 Proxy's cookie-secret
requirements. Configure a GitHub OAuth application callback as:

`https://<MACROVISION_HOST>/oauth2/callback`

Place the TLS certificate and key at:

- `deploy/certs/fullchain.pem`
- `deploy/certs/privkey.pem`

The certificate directory is intentionally not provided by the repository.

## Role mapping

Comma-separated GitHub usernames:

- `MACROVISION_READER_USERS`: authenticated read access.
- `MACROVISION_RESEARCH_USERS`: reader + research mutations.
- `MACROVISION_OPERATOR_USERS`: full current Web role.

Use least privilege. The same username should normally appear only in its
highest role list.

## Start

`docker compose --env-file /secure/path/macrovision.env -f docker-compose.production.yml up -d --build`

Before serving traffic, verify migrations, HTTPS, OAuth login, 401/403 behavior,
rate-limit 429 behavior, backup/restore of PostgreSQL, and that ports 3000,
4180, 5432, and 8000 are not exposed by the host firewall.

## Operational gates

- Back up PostgreSQL before upgrades and test restore periodically.
- Rotate OAuth client secret, cookie secret, DB password, and trusted proxy
  secret through the deployment secret manager.
- Keep Next.js and production dependencies behind the CI production-audit gate.
- Monitor 401/403/429/5xx rates and container restarts.
- Never log OAuth tokens, cookies, provider credentials, or the trusted proxy
  secret.
