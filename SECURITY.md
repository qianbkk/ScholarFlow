# Security Policy

## Supported Versions

| Version | Supported          | Notes |
|---------|--------------------|-------|
| 1.0.x   | :white_check_mark: | 首个稳定 release, 包含 R1-R8.3 全部安全硬化 + R10.5 多用户认证 |
| 0.1.x   | :x:                | 仅 pre-release 快照, 不再 backport 安全修复 |

## Reporting a Vulnerability

Please report security vulnerabilities via [GitHub Security Advisories](https://github.com/qianbkk/ScholarFlow/security/advisories/new).

We will:
- Acknowledge within 48 hours
- Investigate and provide a fix timeline within 7 days
- Credit you in the fix release (unless you prefer anonymity)

## Security Architecture (Round 5-10.5 Hardening)

- **Input sanitization**: 6-layer (NFKC + Cyrillic/Greek/Math alphabet homoglyph + 0-width + CJK injection denylist + XML tag isolation + max_length=2000)
- **Output XSS**: synthesis_agent denylist + HTML entity decode + DOMPurify
- **Credential safety**: scrub_sensitive() in logs
- **HTTP hardening**: 7 security headers (X-Content-Type-Options / X-Frame-Options / X-XSS-Protection / Referrer-Policy / Permissions-Policy / HSTS / CSP)
- **Rate limiting**: slowapi 5/minute;20/hour on /search + /search/stream; 30/minute on /providers
- **CORS**: strict whitelist, no wildcard, methods/headers restricted
- **Request ID**: 12-char UUID4 + 128-char length cap + `[A-Za-z0-9_-]` charset (DoS prevention)
- **Error responses**: 422 input redacted, 500 stack trace redacted
- **LLM prompt injection**: layer 0 (sanitize) + layer 1 (XML tag) + layer 2 (LLM-aware system suffix)
- **Frontend URL validation**: `^https?://` protocol whitelist + noopener noreferrer
- **Auth (R10.5)**: API Key (sha256 摘要, 不存明文), 多用户 budget 隔离, OPEN_MODE 后门 (本地开发用)

## Known CVEs (Tracked)

This section lists CVEs that **affect** this project but are **not yet patched**, with explicit mitigation plans. Each entry is reflected in `.github/workflows/ci.yml` `--ignore-vuln` whitelist.

| CVE / Advisory       | Package                  | Affected Versions | Mitigation Plan | Mitigation Status |
|----------------------|--------------------------|-------------------|------------------|--------------------|
| PYSEC-2024-38        | langgraph                | 0.6.11            | Upgrade to 1.0.0 (breaking API change — full StateGraph rewrite needed) | **R11+ planned** |
| GHSA-9hjg-9rjm-9j3p  | langgraph-checkpoint     | 3.0.1             | Bump to 4.0.0 alongside langgraph 1.0 migration | **R11+ planned**  |

CI runs `pip-audit` on every push with these CVEs explicitly whitelisted via `--ignore-vuln`. Any **new** CVE will fail the build. To upgrade: open a tracked issue, then remove the `--ignore-vuln` flag for that CVE.

## Runtime Security Hardening Details

- **API Key storage**: SHA-256 hashed, never plaintext. Salted via per-key random (R10.5+).
- **Per-user budget isolation**: dev-user shares one budget pool; multi-user mode isolates per `user_id`.
- **OPEN_MODE**: dev/CI only. **Never set OPEN_MODE=true in production.**
- **EXPOSE_DOCS env**: Set to `false` in production to hide `/docs` and `/openapi.json` (schema enumeration attack surface).

## Known Limitations

- No CSRF token on POST endpoints (assumes same-origin via reverse proxy)
- API keys transmitted via `X-API-Key` header; EventSource clients (SSE) pass via `?api_key=` query param (limitation of browser EventSource API). R11+ will add cookie-based auth.
- `/docs` + `/openapi.json` gated by `EXPOSE_DOCS` env, default ON in dev
- See [GitHub Issues](https://github.com/qianbkk/ScholarFlow/issues) for tracked improvements
