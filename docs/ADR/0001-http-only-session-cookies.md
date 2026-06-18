# ADR 0001: HttpOnly + SameSite=Strict session cookies with CSRF double-submit

- **Status**: Accepted (R10.5.30)
- **Date**: 2026-06-18
- **Deciders**: Backend security track

## Context

The original v1 auth design stored the session JWT in `localStorage` and sent it back via an `Authorization: Bearer <token>` header. Any successful XSS in the React app could read the token, exfiltrate it, and replay it against the API indefinitely — localStorage is fully visible to JS and persists across sessions. This is a well-known anti-pattern called out by OWASP. The repo had no CSP, no DOMPurify hardening across report rendering, and inline `dangerouslySetInnerHTML` paths that depend on the data being safe — so the threat model was real, not theoretical.

We needed a session mechanism that (a) keeps the token out of JS reach, (b) still works for the same-origin SPA, and (c) defends against CSRF without breaking form-based login or the streaming endpoints.

## Decision

Move to **HttpOnly + Secure + SameSite=Strict** session cookies issued by `/api/v1/auth/login`, with CSRF protection via the **double-submit cookie** pattern: a non-HttpOnly `csrf_token` cookie is read by the frontend and echoed back in an `X-CSRF-Token` header on every state-changing request. The server compares the two.

- Cookies are scoped to `Path=/` and `SameSite=Strict` (no cross-site requests at all, including no third-party embeds).
- The login endpoint sets both cookies; logout clears them.
- `GET` requests are not protected — they are idempotent reads. `POST/PUT/PATCH/DELETE` require the matching CSRF header.
- Streaming responses (`/search/stream`, `/report/stream`) carry the cookie automatically because they are same-origin.

## Consequences

**Positive**
- XSS can no longer steal the session token. The token never enters JS memory.
- CSRF is blocked: a cross-origin attacker cannot read the `csrf_token` cookie (SameSite=Strict + non-HttpOnly but same-site only), so the header echo fails.
- One auth surface for both browser and `fetch`-based API consumers.

**Negative**
- Frontend `fetch` calls must use `credentials: 'include'` to send cookies cross-context (mainly relevant if FE and BE ever split domains — they don't today).
- Any future cross-origin integration (embed widgets, third-party apps) needs a rethink — `SameSite=Strict` blocks it.
- Logout / cookie rotation must be tested carefully; a stale token vs. a rotated one is a common foot-gun.
- The `tests/manual/` Playwright scripts had to add `storage_state` handling because the cookie is no longer in `localStorage`.

**Commits**: see `84b6518` (R10.5.30 D3 — HttpOnly cookie session + CSRF double-submit) and the follow-up hardening in the R10.5.30 wave.