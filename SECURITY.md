# Security Policy

## Supported Versions

| Version | Supported          | Notes |
|---------|--------------------|-------|
| 1.0.x   | :white_check_mark: | 首个稳定 release, 包含 R1-R8.3 全部安全硬化 |
| 0.1.x   | :x:                | 仅 pre-release 快照, 不再 backport 安全修复 |

## Reporting a Vulnerability

Please report security vulnerabilities via [GitHub Security Advisories](https://github.com/qianbkk/ScholarFlow/security/advisories/new).

We will:
- Acknowledge within 48 hours
- Investigate and provide a fix timeline within 7 days
- Credit you in the fix release (unless you prefer anonymity)

## Security Architecture (Round 5-6 Hardening)

- **Input sanitization**: 6-layer (NFKC + Cyrillic/Greek/Math alphabet homoglyph + 0-width + CJK injection denylist + XML tag isolation + max_length=2000)
- **Output XSS**: synthesis_agent denylist + HTML entity decode + DOMPurify
- **Credential safety**: scrub_sensitive() in logs
- **HTTP hardening**: 7 security headers (X-Content-Type-Options / X-Frame-Options / X-XSS-Protection / Referrer-Policy / Permissions-Policy / HSTS / CSP)
- **Rate limiting**: slowapi 5/minute;20/hour on /search + /search/stream
- **CORS**: strict whitelist, no wildcard, methods/headers restricted
- **Request ID**: 12-char UUID4 + 128-char length cap + `[A-Za-z0-9_-]` charset (DoS prevention)
- **Error responses**: 422 input redacted, 500 stack trace redacted
- **LLM prompt injection**: layer 0 (sanitize) + layer 1 (XML tag) + layer 2 (LLM-aware system suffix)
- **Frontend URL validation**: `^https?://` protocol whitelist + noopener noreferrer
- **Auth**: TODO (FUTURE_TASKS #6 / #37)

## Known Limitations

- No authentication (deploy behind reverse proxy with auth in production)
- No CSRF token on POST endpoints (assumes same-origin via reverse proxy)
- `/docs` + `/openapi.json` gated by `EXPOSE_DOCS` env, default ON in dev
- See `docs/FUTURE_TASKS.md` for tracked improvements
